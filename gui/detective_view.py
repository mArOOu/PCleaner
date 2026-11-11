"""Space Detective GUI view: Culprit Spotlights, Recent Growth, Folder Explorer, and Large Files."""

from __future__ import annotations

import os
import threading
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from core.cleaner import trash_custom_paths
from core.models import FolderNode, SpaceReport
from core.scanner import scan_folder_children, scan_space_detective
from gui import theme
from gui.modals import ReportModal, open_in_explorer
from utils.formatting import format_age, format_bytes, format_timestamp

# Paths that must NEVER be directly trashed from the Folder Explorer UI
_PROTECTED_PREFIXES = (
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\programdata",
    r"c:\system volume information",
    r"c:\$recycle.bin",
)


def _is_protected_path(path: str) -> bool:
    norm = os.path.normcase(os.path.abspath(path)).rstrip("\\")
    user_root = os.path.normcase(os.path.abspath(os.path.expanduser("~"))).rstrip("\\")
    if norm in ("c:", "c:\\users", user_root):
        return True
    if norm.endswith("\\appdata") or norm.endswith("\\appdata\\local") or norm.endswith("\\appdata\\roaming"):
        return True
    for pref in _PROTECTED_PREFIXES:
        if norm == pref or norm.startswith(pref + "\\"):
            return True
    return False


class SpaceDetectiveView(ctk.CTkFrame):
    """Diagnostic panel showing what is eating space on C: and why."""

    def __init__(
        self,
        parent,
        on_refresh_drive: Callable[[], None],
        get_delete_mode: Callable[[], str],
        on_status: Callable[[str], None],
    ):
        super().__init__(parent, fg_color="transparent")
        self.on_refresh_drive = on_refresh_drive
        self.get_delete_mode = get_delete_mode
        self.on_status = on_status

        self.report: SpaceReport | None = None
        self.current_explorer_path: str = "C:\\"
        self.current_explorer_nodes: list[FolderNode] = []
        self._scanning = False
        self._active_subtab = "Culprits & Growth"

        self._build_ui()

    def _build_ui(self) -> None:
        # Top control strip
        top = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=10)
        top.pack(fill="x", pady=(0, 10))

        left = ctk.CTkFrame(top, fg_color="transparent")
        left.pack(side="left", padx=14, pady=12)

        ctk.CTkLabel(
            left,
            text="Space Detective — Find What's Filling C:",
            font=(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            left,
            text="Scans folders, spots hidden bloat, tracks growth between runs, and explains what every item is.",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(anchor="w")

        self.scan_btn = ctk.CTkButton(
            top,
            text="Run Space Detective Scan",
            width=200,
            height=38,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=(theme.FONT_FAMILY, 13, "bold"),
            command=self.start_scan,
        )
        self.scan_btn.pack(side="right", padx=14, pady=12)

        # Sub-navigation
        nav_row = ctk.CTkFrame(self, fg_color="transparent")
        nav_row.pack(fill="x", pady=(0, 8))

        self.subtab_seg = ctk.CTkSegmentedButton(
            nav_row,
            values=["Culprits & Growth", "Folder Explorer", "Large Files (>100 MB)"],
            command=self._switch_subtab,
            selected_color=theme.ACCENT_BLUE,
            selected_hover_color=theme.ACCENT_BLUE_HOVER,
            fg_color=theme.BG_CARD,
        )
        self.subtab_seg.set("Culprits & Growth")
        self.subtab_seg.pack(side="left")

        self.scan_note = ctk.CTkLabel(
            nav_row,
            text="Click 'Run Space Detective Scan' to inspect C: drive.",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_MUTED,
        )
        self.scan_note.pack(side="right")

        # Dynamic content container
        self.body = ctk.CTkScrollableFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=10)
        self.body.pack(fill="both", expand=True)

        self._render_empty_state()

    def _render_empty_state(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.body,
            text="No Space Detective scan run yet.\n\nClick 'Run Space Detective Scan' above to discover the biggest folders,\nhidden AppData caches, large files, and folder growth since last scan.",
            font=(theme.FONT_FAMILY, 13),
            text_color=theme.TEXT_SECONDARY,
            justify="center",
        ).pack(pady=60)

    def _switch_subtab(self, value: str) -> None:
        self._active_subtab = value
        self._render_active_subtab()

    def _safe_after(self, fn) -> None:
        try:
            if self.winfo_exists():
                self.after(0, fn)
        except Exception:
            pass

    def start_scan(self) -> None:
        if self._scanning:
            return
        self._scanning = True
        self.scan_btn.configure(state="disabled", text="Scanning C:...")
        self.scan_note.configure(text="Scanning folders & large files...")

        def _worker():
            report = scan_space_detective(
                on_status=lambda msg: self._safe_after(lambda m=msg: self.on_status(m)),
            )
            self._safe_after(lambda r=report: self._on_scan_complete(r))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_scan_complete(self, report: SpaceReport) -> None:
        self._scanning = False
        self.report = report
        self.current_explorer_path = "C:\\"
        self.current_explorer_nodes = report.top_folders
        self.scan_btn.configure(state="normal", text="Rescan C: Drive")
        self.scan_note.configure(
            text=f"Last scanned: {format_timestamp(report.scanned_at)} • Free: {format_bytes(report.drive_free)}"
        )
        self.on_status("Space Detective scan complete.")
        self._render_active_subtab()

    def _render_active_subtab(self) -> None:
        if not self.report:
            self._render_empty_state()
            return
        if self._active_subtab == "Culprits & Growth":
            self._render_culprits()
        elif self._active_subtab == "Folder Explorer":
            self._render_explorer()
        else:
            self._render_large_files()

    def _render_culprits(self) -> None:
        assert self.report is not None
        for w in self.body.winfo_children():
            w.destroy()

        # Recent Growth Section
        if self.report.previous_snapshot_time:
            growth_box = ctk.CTkFrame(self.body, fg_color=theme.BG_CARD, corner_radius=10)
            growth_box.pack(fill="x", padx=8, pady=(8, 10))
            ctk.CTkLabel(
                growth_box,
                text=f"What Grew Since Previous Scan ({format_timestamp(self.report.previous_snapshot_time)}):",
                font=(theme.FONT_FAMILY, 13, "bold"),
                text_color=theme.ACCENT_AMBER,
                anchor="w",
            ).pack(fill="x", padx=12, pady=(10, 4))

            if self.report.growth_entries:
                for g in self.report.growth_entries[:8]:
                    ctk.CTkLabel(
                        growth_box,
                        text=f"  +{format_bytes(g.delta_bytes)}  in  {g.path}  (now {format_bytes(g.current_bytes)})",
                        font=(theme.FONT_MONO, 11),
                        text_color=theme.TEXT_PRIMARY,
                        anchor="w",
                    ).pack(fill="x", padx=12, pady=2)
                ctk.CTkFrame(growth_box, fg_color="transparent", height=6).pack()
            else:
                ctk.CTkLabel(
                    growth_box,
                    text="  No folders grew by more than 50 MB since your last scan.",
                    font=(theme.FONT_FAMILY, 12),
                    text_color=theme.TEXT_SECONDARY,
                    anchor="w",
                ).pack(fill="x", padx=12, pady=(0, 10))

        # Culprit Spotlights
        ctk.CTkLabel(
            self.body,
            text="Top Space Culprits Inside Your Profile & AppData:",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 6))

        if not self.report.spotlights:
            ctk.CTkLabel(
                self.body,
                text="No abnormally large user/AppData culprits (>300 MB) found.",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.TEXT_MUTED,
            ).pack(pady=20)
            return

        for sp in self.report.spotlights:
            card = ctk.CTkFrame(self.body, fg_color=theme.BG_CARD, corner_radius=10)
            card.pack(fill="x", padx=8, pady=4)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 4))

            sev_color = (
                theme.ACCENT_RED if sp.severity == "high"
                else (theme.ACCENT_AMBER if sp.severity == "medium" else theme.ACCENT_BLUE)
            )
            ctk.CTkLabel(
                top,
                text=sp.title,
                font=(theme.FONT_FAMILY, 14, "bold"),
                text_color=sev_color,
            ).pack(side="left")

            badge = ctk.CTkLabel(
                top,
                text=sp.category_label,
                font=(theme.FONT_FAMILY, 11, "bold"),
                fg_color=theme.BG_ELEVATED,
                text_color=theme.TEXT_PRIMARY,
                corner_radius=6,
                padx=8,
                pady=2,
            )
            badge.pack(side="right")

            ctk.CTkLabel(
                card,
                text=f"What it has: {sp.explanation}",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.TEXT_PRIMARY,
                anchor="w",
                wraplength=780,
                justify="left",
            ).pack(fill="x", padx=12, pady=(0, 2))

            ctk.CTkLabel(
                card,
                text=f"Tip: {sp.recommendation}",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.ACCENT_GREEN,
                anchor="w",
                wraplength=780,
                justify="left",
            ).pack(fill="x", padx=12, pady=(0, 4))

            btm = ctk.CTkFrame(card, fg_color="transparent")
            btm.pack(fill="x", padx=12, pady=(0, 10))
            ctk.CTkLabel(
                btm,
                text=sp.path,
                font=(theme.FONT_MONO, 10),
                text_color=theme.TEXT_MUTED,
            ).pack(side="left")

            ctk.CTkButton(
                btm,
                text="Open Folder",
                width=95,
                height=26,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_BLUE,
                font=(theme.FONT_FAMILY, 11),
                command=lambda p=sp.path: open_in_explorer(p),
            ).pack(side="right", padx=(6, 0))

            ctk.CTkButton(
                btm,
                text="Explore Inside",
                width=105,
                height=26,
                fg_color=theme.ACCENT_BLUE,
                hover_color=theme.ACCENT_BLUE_HOVER,
                font=(theme.FONT_FAMILY, 11, "bold"),
                command=lambda p=sp.path: self._explore_folder(p),
            ).pack(side="right")

    def _explore_folder(self, folder_path: str) -> None:
        self._active_subtab = "Folder Explorer"
        self.subtab_seg.set("Folder Explorer")
        self.on_status(f"Exploring {folder_path}...")

        def _worker():
            children = scan_folder_children(folder_path)
            self._safe_after(lambda fp=folder_path, ch=children: self._set_explorer_data(fp, ch))

        threading.Thread(target=_worker, daemon=True).start()

    def _set_explorer_data(self, folder_path: str, nodes: list[FolderNode]) -> None:
        self.current_explorer_path = folder_path
        self.current_explorer_nodes = nodes
        self.on_status(f"Showing {folder_path}")
        self._render_explorer()

    def _render_explorer(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()

        # Quick jumps + current breadcrumb bar
        nav = ctk.CTkFrame(self.body, fg_color=theme.BG_CARD, corner_radius=8)
        nav.pack(fill="x", padx=8, pady=(8, 8))

        jumps = ctk.CTkFrame(nav, fg_color="transparent")
        jumps.pack(fill="x", padx=10, pady=(8, 4))

        user_home = os.path.expanduser("~")
        quick_places = [
            ("C:\\", "C:\\"),
            ("User Profile", user_home),
            ("AppData\\Local", os.path.join(user_home, "AppData", "Local")),
            ("AppData\\Roaming", os.path.join(user_home, "AppData", "Roaming")),
            ("ProgramData", r"C:\ProgramData"),
        ]
        for label, target in quick_places:
            ctk.CTkButton(
                jumps,
                text=label,
                height=26,
                width=95,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_BLUE,
                font=(theme.FONT_FAMILY, 11),
                command=lambda p=target: self._explore_folder(p),
            ).pack(side="left", padx=(0, 6))

        parent_dir = os.path.dirname(self.current_explorer_path.rstrip("\\"))
        if parent_dir and parent_dir != self.current_explorer_path:
            ctk.CTkButton(
                jumps,
                text="Up One Level",
                height=26,
                width=100,
                fg_color=theme.ACCENT_BLUE,
                font=(theme.FONT_FAMILY, 11, "bold"),
                command=lambda p=parent_dir + ("\\" if len(parent_dir) == 2 else ""): self._explore_folder(p),
            ).pack(side="right")

        ctk.CTkLabel(
            nav,
            text=f"Current folder: {self.current_explorer_path}",
            font=(theme.FONT_MONO, 11, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(2, 8))

        total_here = sum(n.size_bytes for n in self.current_explorer_nodes) or 1
        for node in self.current_explorer_nodes[:40]:
            row = ctk.CTkFrame(self.body, fg_color=theme.BG_CARD, corner_radius=8)
            row.pack(fill="x", padx=8, pady=3)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=12, pady=8)

            pct = node.size_bytes / total_here * 100.0
            ctk.CTkLabel(
                info,
                text=f"{node.name}   —   {format_bytes(node.size_bytes)} ({pct:.1f}%)",
                font=(theme.FONT_FAMILY, 13, "bold"),
                text_color=theme.TEXT_PRIMARY,
                anchor="w",
            ).pack(fill="x")

            bar = ctk.CTkProgressBar(info, height=6, progress_color=theme.ACCENT_BLUE)
            bar.set(min(1.0, max(0.01, pct / 100.0)))
            bar.pack(fill="x", pady=(4, 4))

            sub_txt = f"{node.file_count:,} files • Modified {format_age(node.mtime)}"
            if node.explanation:
                sub_txt += f"\nWhat it is: {node.explanation}"
            ctk.CTkLabel(
                info,
                text=sub_txt,
                font=(theme.FONT_FAMILY, 11),
                text_color=theme.TEXT_SECONDARY,
                anchor="w",
                justify="left",
                wraplength=560,
            ).pack(fill="x")

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=10)

            is_virtual_files_row = node.name.startswith("[Files directly")
            if not is_virtual_files_row:
                ctk.CTkButton(
                    btns,
                    text="Explore",
                    width=70,
                    height=28,
                    fg_color=theme.ACCENT_BLUE,
                    hover_color=theme.ACCENT_BLUE_HOVER,
                    font=(theme.FONT_FAMILY, 11, "bold"),
                    command=lambda p=node.path: self._explore_folder(p),
                ).pack(side="left", padx=3)

            ctk.CTkButton(
                btns,
                text="Open",
                width=55,
                height=28,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_BLUE,
                font=(theme.FONT_FAMILY, 11),
                command=lambda p=node.path: open_in_explorer(p),
            ).pack(side="left", padx=3)

            if not is_virtual_files_row and not _is_protected_path(node.path):
                ctk.CTkButton(
                    btns,
                    text="Trash",
                    width=60,
                    height=28,
                    fg_color="#7f1d1d",
                    hover_color=theme.ACCENT_RED,
                    font=(theme.FONT_FAMILY, 11, "bold"),
                    command=lambda n=node: self._confirm_trash_path(
                        n.path, n.size_bytes, True, n.explanation or f"Folder containing {n.file_count:,} files"
                    ),
                ).pack(side="left", padx=3)

    def _render_large_files(self) -> None:
        assert self.report is not None
        for w in self.body.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self.body,
            text=f"Largest Individual Files Found (>100 MB) — {len(self.report.large_files)} files:",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(10, 6))

        if not self.report.large_files:
            ctk.CTkLabel(
                self.body,
                text="No individual files over 100 MB found in user directories.",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.TEXT_MUTED,
            ).pack(pady=30)
            return

        for f in self.report.large_files[:35]:
            row = ctk.CTkFrame(self.body, fg_color=theme.BG_CARD, corner_radius=8)
            row.pack(fill="x", padx=8, pady=3)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=12, pady=8)

            ctk.CTkLabel(
                info,
                text=f"{f.name}   —   {format_bytes(f.size_bytes)}",
                font=(theme.FONT_FAMILY, 13, "bold"),
                text_color=theme.ACCENT_AMBER if f.size_bytes > 1024**3 else theme.TEXT_PRIMARY,
                anchor="w",
            ).pack(fill="x")

            ctk.CTkLabel(
                info,
                text=f"What it is: {f.explanation}  •  Modified {format_age(f.mtime)}\n{f.path}",
                font=(theme.FONT_MONO, 10),
                text_color=theme.TEXT_SECONDARY,
                anchor="w",
                justify="left",
            ).pack(fill="x")

            btns = ctk.CTkFrame(row, fg_color="transparent")
            btns.pack(side="right", padx=10)

            ctk.CTkButton(
                btns,
                text="Open",
                width=60,
                height=28,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_BLUE,
                font=(theme.FONT_FAMILY, 11),
                command=lambda p=f.path: open_in_explorer(p),
            ).pack(side="left", padx=3)

            if not _is_protected_path(f.path) and f.name.lower() not in ("pagefile.sys", "hiberfil.sys", "swapfile.sys"):
                ctk.CTkButton(
                    btns,
                    text="Trash",
                    width=60,
                    height=28,
                    fg_color="#7f1d1d",
                    hover_color=theme.ACCENT_RED,
                    font=(theme.FONT_FAMILY, 11, "bold"),
                    command=lambda entry=f: self._confirm_trash_path(
                        entry.path, entry.size_bytes, False, entry.explanation
                    ),
                ).pack(side="left", padx=3)

    def _confirm_trash_path(self, path: str, size_bytes: int, is_dir: bool, explanation: str) -> None:
        mode = self.get_delete_mode()
        dest = "Windows Recycle Bin (recoverable)" if mode == "trash" else "PERMANENT DELETION"
        ok = messagebox.askyesno(
            "Confirm Action",
            f"Are you sure you want to send this item to {dest}?\n\n"
            f"Path: {path}\n"
            f"Size: {format_bytes(size_bytes)}\n"
            f"Details: {explanation}",
        )
        if not ok:
            return

        res = trash_custom_paths([(path, size_bytes, is_dir)], mode=mode)  # type: ignore[arg-type]
        self.on_refresh_drive()
        ReportModal(self.winfo_toplevel(), res)
        if self._active_subtab == "Folder Explorer":
            self._explore_folder(self.current_explorer_path)
        else:
            self.start_scan()
