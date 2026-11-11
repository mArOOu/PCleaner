"""Interactive transparency modals: File Inspector, Pre-Delete Confirmation, and Audit Report."""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Literal

import customtkinter as ctk

from core.models import CleanCategory, CleanItem, CleanResult
from gui import theme
from utils.formatting import format_age, format_bytes


def open_in_explorer(path: str) -> None:
    """Open a folder or highlight a file in Windows File Explorer."""
    abs_path = os.path.abspath(path)
    try:
        if os.path.isfile(abs_path):
            subprocess.Popen(["explorer", "/select,", abs_path])
        elif os.path.isdir(abs_path):
            subprocess.Popen(["explorer", abs_path])
        else:
            parent = os.path.dirname(abs_path)
            if os.path.isdir(parent):
                subprocess.Popen(["explorer", parent])
    except Exception:
        pass


class InspectorModal(ctk.CTkToplevel):
    """Modal allowing user to inspect every file/folder inside a category and toggle individually."""

    def __init__(
        self,
        parent,
        category: CleanCategory,
        on_update: Callable[[], None],
        on_whitelist: Callable[[str], None],
    ):
        super().__init__(parent)
        self.category = category
        self.on_update = on_update
        self.on_whitelist = on_whitelist
        self.item_vars: list[tuple[CleanItem, ctk.BooleanVar]] = []
        self._limit = 40

        self.title(f"Inspect Contents — {category.name}")
        self.geometry("920x620")
        self.minsize(760, 480)
        self.configure(fg_color=theme.BG_DARK)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._render_items()

    def _build_ui(self) -> None:
        # Header info
        hdr = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=10)
        hdr.pack(fill="x", padx=16, pady=(16, 10))

        title_row = ctk.CTkFrame(hdr, fg_color="transparent")
        title_row.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            title_row,
            text=self.category.name,
            font=(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")

        self.summary_lbl = ctk.CTkLabel(
            title_row,
            text="",
            font=(theme.FONT_FAMILY, 13, "bold"),
            text_color=theme.ACCENT_GREEN,
        )
        self.summary_lbl.pack(side="right")

        ctk.CTkLabel(
            hdr,
            text=f"What's inside: {self.category.what_it_has}",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
            wraplength=860,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 2))

        ctk.CTkLabel(
            hdr,
            text=f"Deletion impact: {self.category.delete_impact}",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.ACCENT_AMBER if "Review" in self.category.safety else theme.TEXT_MUTED,
            anchor="w",
            wraplength=860,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 10))

        # Toolbar: Filter + Select all/none
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=16, pady=(0, 8))

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._render_items())
        search_entry = ctk.CTkEntry(
            toolbar,
            textvariable=self.search_var,
            placeholder_text="Filter by file or folder name...",
            width=280,
            fg_color=theme.BG_CARD,
            border_color=theme.BORDER_SUBTLE,
        )
        search_entry.pack(side="left")

        ctk.CTkButton(
            toolbar,
            text="Select All",
            width=95,
            height=30,
            fg_color=theme.BG_ELEVATED,
            hover_color=theme.ACCENT_BLUE,
            command=lambda: self._set_all(True),
        ).pack(side="left", padx=(10, 6))

        ctk.CTkButton(
            toolbar,
            text="Deselect All",
            width=95,
            height=30,
            fg_color=theme.BG_ELEVATED,
            hover_color=theme.ACCENT_BLUE,
            command=lambda: self._set_all(False),
        ).pack(side="left")

        if self.category.paths:
            ctk.CTkButton(
                toolbar,
                text="Open Folder",
                width=110,
                height=30,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_BLUE,
                command=lambda: open_in_explorer(self.category.paths[0]),
            ).pack(side="right")

        # Scrollable list
        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color=theme.BG_SIDEBAR, corner_radius=10
        )
        self.scroll.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        # Bottom close bar
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 14))

        self.count_note = ctk.CTkLabel(
            bottom,
            text="",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_MUTED,
        )
        self.count_note.pack(side="left")

        ctk.CTkButton(
            bottom,
            text="Apply & Close",
            width=140,
            height=36,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=(theme.FONT_FAMILY, 13, "bold"),
            command=self._close,
        ).pack(side="right")

    def _update_summary(self) -> None:
        sel = self.category.selected_items
        sel_sz = sum(i.size_bytes for i in sel)
        self.summary_lbl.configure(
            text=f"Selected: {format_bytes(sel_sz)} ({len(sel)} / {len(self.category.items)} items)"
        )
        self.on_update()

    def _set_all(self, value: bool) -> None:
        for item in self.category.items:
            item.selected = value
        for _, var in self.item_vars:
            var.set(value)
        self._update_summary()

    def _render_items(self) -> None:
        for w in self.scroll.winfo_children():
            w.destroy()
        self.item_vars.clear()

        query = self.search_var.get().strip().lower()
        filtered = [
            i
            for i in self.category.items
            if not query or query in i.name.lower() or query in i.path.lower() or query in i.description.lower()
        ]

        if not filtered:
            ctk.CTkLabel(
                self.scroll,
                text="No items found matching filter (or category is empty).",
                font=(theme.FONT_FAMILY, 13),
                text_color=theme.TEXT_MUTED,
            ).pack(pady=30)
            self.count_note.configure(text="")
            self._update_summary()
            return

        shown = filtered[: self._limit]
        for item in shown:
            row = ctk.CTkFrame(self.scroll, fg_color=theme.BG_CARD, corner_radius=8)
            row.pack(fill="x", padx=6, pady=3)

            var = ctk.BooleanVar(value=item.selected)
            self.item_vars.append((item, var))

            def _toggle(it=item, v=var):
                it.selected = bool(v.get())
                self._update_summary()

            cb = ctk.CTkCheckBox(
                row,
                text="",
                variable=var,
                width=24,
                command=_toggle,
            )
            cb.pack(side="left", padx=(10, 4), pady=8)

            info_col = ctk.CTkFrame(row, fg_color="transparent")
            info_col.pack(side="left", fill="x", expand=True, padx=4, pady=6)

            kind_tag = "[Folder]" if item.is_dir else "[File]"
            title_lbl = ctk.CTkLabel(
                info_col,
                text=f"{kind_tag} {item.name}",
                font=(theme.FONT_FAMILY, 12, "bold"),
                text_color=theme.TEXT_PRIMARY,
                anchor="w",
            )
            title_lbl.pack(fill="x")

            meta_text = (
                f"{item.description or 'Cached file'}  •  {item.file_count:,} file(s)  •  "
                f"Modified {format_age(item.mtime)}\n{item.path}"
            )
            ctk.CTkLabel(
                info_col,
                text=meta_text,
                font=(theme.FONT_MONO, 10),
                text_color=theme.TEXT_SECONDARY,
                anchor="w",
                justify="left",
            ).pack(fill="x")

            right_col = ctk.CTkFrame(row, fg_color="transparent")
            right_col.pack(side="right", padx=10, pady=6)

            ctk.CTkLabel(
                right_col,
                text=format_bytes(item.size_bytes),
                font=(theme.FONT_FAMILY, 13, "bold"),
                text_color=theme.ACCENT_BLUE if item.size_bytes > 100 * 1024 * 1024 else theme.TEXT_PRIMARY,
            ).pack(side="left", padx=(0, 8))

            ctk.CTkButton(
                right_col,
                text="Open",
                width=55,
                height=26,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_BLUE,
                font=(theme.FONT_FAMILY, 11),
                command=lambda p=item.path: open_in_explorer(p),
            ).pack(side="left", padx=2)

            ctk.CTkButton(
                right_col,
                text="Keep Forever",
                width=92,
                height=26,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_GREEN,
                font=(theme.FONT_FAMILY, 11),
                command=lambda it=item: self._whitelist_item(it),
            ).pack(side="left", padx=2)

        if len(filtered) > self._limit:
            more_btn = ctk.CTkButton(
                self.scroll,
                text=f"Show More ({len(filtered) - self._limit} remaining items)",
                fg_color=theme.BG_ELEVATED,
                command=self._show_more,
            )
            more_btn.pack(pady=10)

        self.count_note.configure(
            text=f"Showing {len(shown)} of {len(filtered)} items (sorted largest first)."
        )
        self._update_summary()

    def _show_more(self) -> None:
        self._limit += 60
        self._render_items()

    def _whitelist_item(self, item: CleanItem) -> None:
        item.selected = False
        self.on_whitelist(item.path)
        self.category.items = [i for i in self.category.items if i.path != item.path]
        self._render_items()

    def _close(self) -> None:
        self.on_update()
        self.destroy()


class ConfirmCleanModal(ctk.CTkToplevel):
    """Explicit confirmation dialog listing exact items & paths before sending to Trash or deleting."""

    def __init__(
        self,
        parent,
        categories: list[CleanCategory],
        mode: Literal["trash", "permanent"],
        on_confirm: Callable[[], None],
    ):
        super().__init__(parent)
        self.categories = categories
        self.mode = mode
        self.on_confirm = on_confirm

        self.title("Confirm Cleanup — Review What Will Be Cleaned")
        self.geometry("760x540")
        self.minsize(640, 440)
        self.configure(fg_color=theme.BG_DARK)
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self) -> None:
        total_bytes = sum(c.selected_bytes for c in self.categories)
        total_items = sum(len(c.selected_items) for c in self.categories)

        banner_color = "#064e3b" if self.mode == "trash" else "#7f1d1d"
        banner_text = (
            f"Destination: Windows Recycle Bin (Recoverable) — {format_bytes(total_bytes)} across {total_items} items"
            if self.mode == "trash"
            else f"WARNING: Permanent Delete (Bypassing Recycle Bin) — {format_bytes(total_bytes)} across {total_items} items"
        )

        banner = ctk.CTkFrame(self, fg_color=banner_color, corner_radius=10)
        banner.pack(fill="x", padx=16, pady=(16, 10))
        ctk.CTkLabel(
            banner,
            text=banner_text,
            font=(theme.FONT_FAMILY, 13, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(padx=14, pady=12)

        ctk.CTkLabel(
            self,
            text="The following categories and specific items are queued for cleanup:",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 6))

        scroll = ctk.CTkScrollableFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=10)
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        for cat in self.categories:
            sel = cat.selected_items
            if not sel:
                continue
            card = ctk.CTkFrame(scroll, fg_color=theme.BG_CARD, corner_radius=8)
            card.pack(fill="x", padx=6, pady=4)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(8, 2))
            ctk.CTkLabel(
                top,
                text=cat.name,
                font=(theme.FONT_FAMILY, 13, "bold"),
                text_color=theme.TEXT_PRIMARY,
            ).pack(side="left")
            ctk.CTkLabel(
                top,
                text=f"{format_bytes(cat.selected_bytes)} ({len(sel)} items)",
                font=(theme.FONT_FAMILY, 12, "bold"),
                text_color=theme.ACCENT_GREEN,
            ).pack(side="right")

            ctk.CTkLabel(
                card,
                text=f"What it has: {cat.what_it_has}",
                font=(theme.FONT_FAMILY, 11),
                text_color=theme.TEXT_SECONDARY,
                anchor="w",
                wraplength=680,
                justify="left",
            ).pack(fill="x", padx=12, pady=(0, 4))

            preview_lines = [
                f"  • {it.name} ({format_bytes(it.size_bytes)}) — {it.path}"
                for it in sel[:6]
            ]
            if len(sel) > 6:
                preview_lines.append(f"  ... and {len(sel) - 6} more items")
            ctk.CTkLabel(
                card,
                text="\n".join(preview_lines),
                font=(theme.FONT_MONO, 10),
                text_color=theme.TEXT_MUTED,
                anchor="w",
                justify="left",
            ).pack(fill="x", padx=12, pady=(0, 8))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 16))

        ctk.CTkButton(
            btns,
            text="Cancel",
            width=120,
            height=38,
            fg_color=theme.BG_ELEVATED,
            hover_color=theme.BORDER_SUBTLE,
            command=self.destroy,
        ).pack(side="left")

        action_txt = (
            f"Move {format_bytes(total_bytes)} to Recycle Bin"
            if self.mode == "trash"
            else f"Permanently Delete {format_bytes(total_bytes)}"
        )
        action_col = theme.ACCENT_GREEN if self.mode == "trash" else theme.ACCENT_RED
        action_hov = theme.ACCENT_GREEN_HOVER if self.mode == "trash" else theme.ACCENT_RED_HOVER

        ctk.CTkButton(
            btns,
            text=action_txt,
            height=38,
            fg_color=action_col,
            hover_color=action_hov,
            font=(theme.FONT_FAMILY, 13, "bold"),
            command=self._proceed,
        ).pack(side="right")

    def _proceed(self) -> None:
        self.destroy()
        self.on_confirm()


class ReportModal(ctk.CTkToplevel):
    """Audit report modal for Dry Run Previews and Post-Cleanup Results."""

    def __init__(
        self,
        parent,
        result: CleanResult,
        recycle_bin_bytes: int = 0,
        on_empty_recycle_bin: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self.result = result
        self.recycle_bin_bytes = recycle_bin_bytes
        self.on_empty_recycle_bin = on_empty_recycle_bin

        title = "Dry Run Preview (No Files Touched)" if result.dry_run else "Cleanup Complete — Audit Report"
        self.title(title)
        self.geometry("760x540")
        self.minsize(640, 420)
        self.configure(fg_color=theme.BG_DARK)
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self) -> None:
        res = self.result
        hdr_bg = "#1e3a8a" if res.dry_run else "#064e3b"
        hdr = ctk.CTkFrame(self, fg_color=hdr_bg, corner_radius=10)
        hdr.pack(fill="x", padx=16, pady=(16, 10))

        if res.dry_run:
            headline = f"Dry Run Preview: {format_bytes(res.freed_bytes)} ({res.items_deleted} items) would be moved to {'Recycle Bin' if res.mode == 'trash' else 'Permanent Deletion'}"
        else:
            dest = "Windows Recycle Bin" if res.mode == "trash" else "permanently deleted"
            headline = f"Cleaned {format_bytes(res.freed_bytes)} ({res.items_deleted} items moved to {dest})"

        ctk.CTkLabel(
            hdr,
            text=headline,
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            wraplength=700,
        ).pack(padx=14, pady=(12, 6))

        if not res.dry_run and res.mode == "trash" and self.recycle_bin_bytes > 0:
            note = (
                f"Note: Your Windows Recycle Bin now holds {format_bytes(self.recycle_bin_bytes)} on C:. "
                "Your files are safely recoverable there. Empty the Recycle Bin once you are satisfied to reclaim that space on C:."
            )
            ctk.CTkLabel(
                hdr,
                text=note,
                font=(theme.FONT_FAMILY, 12),
                text_color="#a7f3d0",
                wraplength=700,
                justify="left",
            ).pack(padx=14, pady=(0, 10))

        log_box = ctk.CTkTextbox(
            self,
            fg_color=theme.BG_SIDEBAR,
            text_color=theme.TEXT_SECONDARY,
            font=(theme.FONT_MONO, 11),
            corner_radius=10,
        )
        log_box.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        lines: list[str] = []
        if res.skipped_paths:
            lines.append(f"=== Skipped Items ({len(res.skipped_paths)}) — Locked by open apps or requiring Admin ===")
            for path, reason in res.skipped_paths[:100]:
                lines.append(f"  * {path}\n      Reason: {reason}")
            if len(res.skipped_paths) > 100:
                lines.append(f"  ... plus {len(res.skipped_paths) - 100} more skipped items.")
            lines.append("")

        label_verb = "Items Queued" if res.dry_run else "Items Processed"
        lines.append(f"=== {label_verb} ({len(res.deleted_paths)}) ===")
        sorted_paths = sorted(res.deleted_paths, key=lambda x: x[1], reverse=True)
        for path, sz in sorted_paths[:200]:
            lines.append(f"  * [{format_bytes(sz):>10}]  {path}")
        if len(sorted_paths) > 200:
            lines.append(f"  ... plus {len(sorted_paths) - 200} additional smaller items.")

        log_box.insert("1.0", "\n".join(lines))
        log_box.configure(state="disabled")

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=16, pady=(0, 14))

        if not res.dry_run and res.mode == "trash" and self.recycle_bin_bytes > 0 and self.on_empty_recycle_bin:
            ctk.CTkButton(
                bottom,
                text=f"Empty Recycle Bin ({format_bytes(self.recycle_bin_bytes)})",
                height=36,
                fg_color=theme.ACCENT_AMBER,
                hover_color="#d97706",
                text_color="#111827",
                font=(theme.FONT_FAMILY, 12, "bold"),
                command=self._empty_bin,
            ).pack(side="left")

        ctk.CTkButton(
            bottom,
            text="Close",
            width=120,
            height=36,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            command=self.destroy,
        ).pack(side="right")

    def _empty_bin(self) -> None:
        if self.on_empty_recycle_bin:
            self.destroy()
            self.on_empty_recycle_bin()
