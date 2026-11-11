"""Main CustomTkinter application window for PCleaner."""

from __future__ import annotations

import os
import threading
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from core.categories import build_categories
from core.cleaner import execute_cleanup
from core.models import CleanCategory
from core.scanner import (
    get_drive_stats,
    scan_all_categories,
    scan_dev_artifacts,
)
from core.system_tools import (
    empty_recycle_bin,
    find_wsl_vhdx_files,
    get_hibernation_status,
    get_recycle_bin_info,
    run_dism_cleanup,
    set_hibernation,
)
from gui import theme
from gui.detective_view import SpaceDetectiveView
from gui.modals import ConfirmCleanModal, InspectorModal, ReportModal, open_in_explorer
from utils.config import load_config, load_history, save_config
from utils.elevation import is_admin, restart_as_admin
from utils.formatting import format_bytes, format_timestamp


class PCleanerApp(ctk.CTk):
    """Main desktop GUI window for PCleaner."""

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("PCleaner — C: Drive Space Detective & Safe Cleaner")
        self.geometry("1160x760")
        self.minsize(980, 650)
        self.configure(fg_color=theme.BG_DARK)

        self.cfg: dict[str, Any] = load_config()
        self.admin_mode = is_admin()
        self.categories: list[CleanCategory] = build_categories()
        self.dev_categories: list[CleanCategory] = []

        self.cat_vars: dict[str, ctk.BooleanVar] = {}
        self.cat_widgets: dict[str, dict[str, Any]] = {}
        self.dev_cat_vars: dict[str, ctk.BooleanVar] = {}

        self._busy = False
        self._closing = False
        self._cancel_requested = False
        self._active_page = "clean"

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_layout()
        self.refresh_drive_and_bin()
        # Automatically kick off a quick category scan on startup so user sees numbers right away
        self.after(250, self.start_category_scan)

    def _safe_after(self, fn) -> None:
        """Schedule callback on Tk main loop only if window is still open."""
        if self._closing:
            return
        try:
            if self.winfo_exists():
                self.after(0, lambda: None if self._closing else fn())
        except Exception:
            pass

    def _on_close(self) -> None:
        self._closing = True
        self._cancel_requested = True
        self.destroy()

    def _build_layout(self) -> None:
        # Top Header Banner
        header = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=0, height=92)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        # Left Brand & Admin Pill
        brand_col = ctk.CTkFrame(header, fg_color="transparent")
        brand_col.pack(side="left", padx=20, pady=12)

        brand_row = ctk.CTkFrame(brand_col, fg_color="transparent")
        brand_row.pack(anchor="w")
        ctk.CTkLabel(
            brand_row,
            text="PCleaner",
            font=(theme.FONT_FAMILY, 22, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")

        if self.admin_mode:
            ctk.CTkLabel(
                brand_row,
                text="ADMIN",
                font=(theme.FONT_FAMILY, 10, "bold"),
                fg_color="#064e3b",
                text_color="#34d399",
                corner_radius=6,
                padx=8,
                pady=2,
            ).pack(side="left", padx=(10, 0))
        else:
            ctk.CTkButton(
                brand_row,
                text="Restart as Admin",
                height=24,
                width=120,
                font=(theme.FONT_FAMILY, 11, "bold"),
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_AMBER,
                command=self._elevate_app,
            ).pack(side="left", padx=(10, 0))

        self.lifetime_lbl = ctk.CTkLabel(
            brand_col,
            text="",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.TEXT_MUTED,
        )
        self.lifetime_lbl.pack(anchor="w", pady=(2, 0))

        # Center Drive C: Gauge
        gauge_col = ctk.CTkFrame(header, fg_color=theme.BG_CARD, corner_radius=10)
        gauge_col.pack(side="left", fill="x", expand=True, padx=20, pady=12)

        gauge_top = ctk.CTkFrame(gauge_col, fg_color="transparent")
        gauge_top.pack(fill="x", padx=14, pady=(8, 4))
        self.drive_title_lbl = ctk.CTkLabel(
            gauge_top,
            text="Local Disk (C:)",
            font=(theme.FONT_FAMILY, 13, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        self.drive_title_lbl.pack(side="left")

        self.drive_free_lbl = ctk.CTkLabel(
            gauge_top,
            text="",
            font=(theme.FONT_FAMILY, 13, "bold"),
            text_color=theme.ACCENT_GREEN,
        )
        self.drive_free_lbl.pack(side="right")

        self.drive_bar = ctk.CTkProgressBar(gauge_col, height=10)
        self.drive_bar.pack(fill="x", padx=14, pady=(0, 10))

        # Right Recycle Bin Status + Quick Empty
        bin_col = ctk.CTkFrame(header, fg_color=theme.BG_CARD, corner_radius=10)
        bin_col.pack(side="right", padx=(0, 20), pady=12)

        bin_inner = ctk.CTkFrame(bin_col, fg_color="transparent")
        bin_inner.pack(padx=12, pady=8)

        self.bin_lbl = ctk.CTkLabel(
            bin_inner,
            text="Recycle Bin: ...",
            font=(theme.FONT_FAMILY, 12, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        self.bin_lbl.pack(side="left", padx=(0, 10))

        self.empty_bin_btn = ctk.CTkButton(
            bin_inner,
            text="Empty Trash",
            width=95,
            height=28,
            fg_color=theme.BG_ELEVATED,
            hover_color=theme.ACCENT_AMBER,
            font=(theme.FONT_FAMILY, 11, "bold"),
            command=self._handle_empty_recycle_bin,
        )
        self.empty_bin_btn.pack(side="left")

        # Main Body: Left Sidebar + Right Page Container
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)

        sidebar = ctk.CTkFrame(body, fg_color=theme.BG_SIDEBAR, width=215, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("clean", "Quick & Safe Clean"),
            ("detective", "Space Detective"),
            ("dev", "Python & WebDev"),
            ("system", "System Tools"),
            ("settings", "Settings & History"),
        ]

        ctk.CTkLabel(
            sidebar,
            text="NAVIGATION",
            font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=18, pady=(18, 6))

        for key, label in nav_items:
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                height=40,
                anchor="w",
                corner_radius=8,
                font=(theme.FONT_FAMILY, 13, "bold"),
                fg_color="transparent",
                hover_color=theme.BG_CARD,
                text_color=theme.TEXT_SECONDARY,
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = btn

        # Delete Mode Indicator inside sidebar bottom
        mode_box = ctk.CTkFrame(sidebar, fg_color=theme.BG_CARD, corner_radius=8)
        mode_box.pack(side="bottom", fill="x", padx=12, pady=14)
        ctk.CTkLabel(
            mode_box,
            text="Deletion Safety",
            font=(theme.FONT_FAMILY, 11, "bold"),
            text_color=theme.TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))
        self.mode_pill_lbl = ctk.CTkLabel(
            mode_box,
            text="",
            font=(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.mode_pill_lbl.pack(fill="x", padx=10, pady=(0, 8))

        # Main Page Container + Bottom Status Bar
        right_wrap = ctk.CTkFrame(body, fg_color="transparent")
        right_wrap.pack(side="right", fill="both", expand=True)

        self.page_container = ctk.CTkFrame(right_wrap, fg_color="transparent")
        self.page_container.pack(fill="both", expand=True, padx=16, pady=(14, 6))

        # Status Bar
        status_bar = ctk.CTkFrame(right_wrap, fg_color=theme.BG_SIDEBAR, height=34, corner_radius=0)
        status_bar.pack(fill="x", side="bottom")
        status_bar.pack_propagate(False)

        self.status_lbl = ctk.CTkLabel(
            status_bar,
            text="Ready",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.TEXT_SECONDARY,
        )
        self.status_lbl.pack(side="left", padx=14)

        self.progress_bar = ctk.CTkProgressBar(status_bar, width=180, height=8)
        self.progress_bar.set(0)

        # Build all pages
        self.pages: dict[str, ctk.CTkFrame] = {}
        self.pages["clean"] = self._build_clean_page(self.page_container)
        self.pages["detective"] = SpaceDetectiveView(
            self.page_container,
            on_refresh_drive=self.refresh_drive_and_bin,
            get_delete_mode=lambda: self.cfg.get("delete_mode", "trash"),
            on_status=self.set_status,
        )
        self.pages["dev"] = self._build_dev_page(self.page_container)
        self.pages["system"] = self._build_system_page(self.page_container)
        self.pages["settings"] = self._build_settings_page(self.page_container)

        self._update_mode_indicator()
        self._show_page("clean")

    def _show_page(self, key: str) -> None:
        self._active_page = key
        for k, frame in self.pages.items():
            if k == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        for k, btn in self.nav_buttons.items():
            if k == key:
                btn.configure(fg_color=theme.ACCENT_BLUE, text_color=theme.TEXT_PRIMARY)
            else:
                btn.configure(fg_color="transparent", text_color=theme.TEXT_SECONDARY)

        if key == "settings":
            self._refresh_settings_lists()
        elif key == "system":
            self._refresh_system_tools()

    def set_status(self, text: str) -> None:
        self.status_lbl.configure(text=text)

    def _update_mode_indicator(self) -> None:
        mode = self.cfg.get("delete_mode", "trash")
        if mode == "trash":
            self.mode_pill_lbl.configure(
                text="Move to Recycle Bin",
                text_color=theme.ACCENT_GREEN,
            )
        else:
            self.mode_pill_lbl.configure(
                text="Permanent Delete",
                text_color=theme.ACCENT_RED,
            )

    def refresh_drive_and_bin(self) -> None:
        total, used, free, pct = get_drive_stats("C:\\")
        free_gb = free / (1024**3)
        self.drive_title_lbl.configure(
            text=f"Local Disk (C:)  —  {format_bytes(used)} / {format_bytes(total)} ({pct:.1f}% used)"
        )
        self.drive_free_lbl.configure(
            text=f"{format_bytes(free)} Free",
            text_color=(
                theme.ACCENT_RED
                if free_gb < 15
                else (theme.ACCENT_AMBER if free_gb < 30 else theme.ACCENT_GREEN)
            ),
        )
        self.drive_bar.configure(
            progress_color=(
                theme.ACCENT_RED
                if free_gb < 15
                else (theme.ACCENT_AMBER if free_gb < 30 else theme.ACCENT_BLUE)
            )
        )
        self.drive_bar.set(min(1.0, max(0.0, pct / 100.0)))

        rb = get_recycle_bin_info("C:\\")
        self.bin_lbl.configure(text=f"Recycle Bin: {format_bytes(rb.size_bytes)} ({rb.item_count} items)")
        self.empty_bin_btn.configure(state="normal" if rb.item_count > 0 or rb.size_bytes > 0 else "disabled")

        lifetime = int(self.cfg.get("total_freed_bytes", 0))
        self.lifetime_lbl.configure(text=f"Lifetime cleaned: {format_bytes(lifetime)}")

    def _elevate_app(self) -> None:
        if restart_as_admin():
            self.destroy()
        else:
            messagebox.showwarning("UAC Declined", "Administrator elevation was cancelled or failed.")

    def _handle_empty_recycle_bin(self) -> None:
        rb = get_recycle_bin_info("C:\\")
        if rb.size_bytes == 0 and rb.item_count == 0:
            messagebox.showinfo("Recycle Bin", "Your Recycle Bin is already empty.")
            return
        ok = messagebox.askyesno(
            "Empty Windows Recycle Bin",
            f"Permanently empty {format_bytes(rb.size_bytes)} ({rb.item_count} items) from the Recycle Bin?\n\n"
            "This cannot be undone, and will immediately release this space back to C:.",
        )
        if not ok:
            return
        success, msg = empty_recycle_bin("C:\\")
        self.refresh_drive_and_bin()
        if success:
            self.set_status(msg)
            messagebox.showinfo("Recycle Bin Emptied", msg)
        else:
            messagebox.showerror("Error", msg)

    # =========================================================================
    # PAGE 1: QUICK & SAFE CLEAN
    # =========================================================================
    def _build_clean_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color="transparent")

        top = ctk.CTkFrame(page, fg_color=theme.BG_CARD, corner_radius=10)
        top.pack(fill="x", pady=(0, 10))

        txt = ctk.CTkFrame(top, fg_color="transparent")
        txt.pack(side="left", padx=14, pady=12)
        ctk.CTkLabel(
            txt,
            text="Quick & Safe Cleaner",
            font=(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            txt,
            text="Every category explains what lives inside. Click 'Inspect Files' to browse individual items before trashing.",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(anchor="w")

        self.rescan_cats_btn = ctk.CTkButton(
            top,
            text="Rescan Categories",
            width=155,
            height=36,
            fg_color=theme.BG_ELEVATED,
            hover_color=theme.ACCENT_BLUE,
            font=(theme.FONT_FAMILY, 12, "bold"),
            command=self.start_category_scan,
        )
        self.rescan_cats_btn.pack(side="right", padx=14, pady=12)

        self.cat_scroll = ctk.CTkScrollableFrame(page, fg_color=theme.BG_SIDEBAR, corner_radius=10)
        self.cat_scroll.pack(fill="both", expand=True, pady=(0, 10))

        self._render_category_cards()

        # Bottom action bar
        action_bar = ctk.CTkFrame(page, fg_color=theme.BG_CARD, corner_radius=10)
        action_bar.pack(fill="x")

        self.selected_total_lbl = ctk.CTkLabel(
            action_bar,
            text="Selected to clean: 0 B",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        self.selected_total_lbl.pack(side="left", padx=16, pady=12)

        self.clean_now_btn = ctk.CTkButton(
            action_bar,
            text="Move Selected to Recycle Bin",
            height=38,
            width=230,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=(theme.FONT_FAMILY, 13, "bold"),
            command=lambda: self._run_clean_workflow(dry_run=False),
        )
        self.clean_now_btn.pack(side="right", padx=(8, 14), pady=10)

        self.dry_run_btn = ctk.CTkButton(
            action_bar,
            text="Dry Run Preview",
            height=38,
            width=145,
            fg_color=theme.BG_ELEVATED,
            hover_color=theme.ACCENT_BLUE,
            font=(theme.FONT_FAMILY, 12, "bold"),
            command=lambda: self._run_clean_workflow(dry_run=True),
        )
        self.dry_run_btn.pack(side="right", pady=10)

        return page

    def _render_category_cards(self) -> None:
        for w in self.cat_scroll.winfo_children():
            w.destroy()
        self.cat_widgets.clear()

        tiers = [
            ("safe", "Tier 1 — Safe Windows & System Temp"),
            ("browser_app", "Tier 2 — Browsers & Desktop App Caches"),
            ("dev", "Tier 3 — Python & WebDev Caches"),
        ]

        for tier_key, tier_title in tiers:
            tier_cats = [c for c in self.categories if c.tier == tier_key]
            if not tier_cats:
                continue

            ctk.CTkLabel(
                self.cat_scroll,
                text=tier_title,
                font=(theme.FONT_FAMILY, 13, "bold"),
                text_color=theme.ACCENT_BLUE,
                anchor="w",
            ).pack(fill="x", padx=10, pady=(12, 4))

            for cat in tier_cats:
                card = ctk.CTkFrame(self.cat_scroll, fg_color=theme.BG_CARD, corner_radius=10)
                card.pack(fill="x", padx=8, pady=4)

                var = self.cat_vars.get(cat.id) or ctk.BooleanVar(value=cat.default_checked)
                self.cat_vars[cat.id] = var

                cb = ctk.CTkCheckBox(
                    card,
                    text="",
                    variable=var,
                    width=24,
                    command=lambda c=cat, v=var: self._on_category_checkbox(c, v),
                )
                cb.pack(side="left", padx=(14, 6), pady=14)

                info = ctk.CTkFrame(card, fg_color="transparent")
                info.pack(side="left", fill="x", expand=True, padx=4, pady=10)

                title_row = ctk.CTkFrame(info, fg_color="transparent")
                title_row.pack(fill="x")

                ctk.CTkLabel(
                    title_row,
                    text=cat.name,
                    font=(theme.FONT_FAMILY, 13, "bold"),
                    text_color=theme.TEXT_PRIMARY,
                ).pack(side="left")

                bg_col, fg_col = theme.SAFETY_COLORS.get(cat.safety, (theme.BG_ELEVATED, theme.TEXT_PRIMARY))
                ctk.CTkLabel(
                    title_row,
                    text=cat.safety,
                    font=(theme.FONT_FAMILY, 10, "bold"),
                    fg_color=bg_col,
                    text_color=fg_col,
                    corner_radius=6,
                    padx=8,
                    pady=2,
                ).pack(side="left", padx=(10, 0))

                ctk.CTkLabel(
                    info,
                    text=f"What it has: {cat.what_it_has}",
                    font=(theme.FONT_FAMILY, 11),
                    text_color=theme.TEXT_SECONDARY,
                    anchor="w",
                    wraplength=560,
                    justify="left",
                ).pack(fill="x", pady=(3, 1))

                ctk.CTkLabel(
                    info,
                    text=f"Impact: {cat.delete_impact}",
                    font=(theme.FONT_FAMILY, 11),
                    text_color=theme.TEXT_MUTED,
                    anchor="w",
                    wraplength=560,
                    justify="left",
                ).pack(fill="x")

                right = ctk.CTkFrame(card, fg_color="transparent")
                right.pack(side="right", padx=14, pady=10)

                size_lbl = ctk.CTkLabel(
                    right,
                    text="Scanning..." if not cat.scanned else format_bytes(cat.selected_bytes),
                    font=(theme.FONT_FAMILY, 14, "bold"),
                    text_color=theme.TEXT_PRIMARY,
                    anchor="e",
                )
                size_lbl.pack(anchor="e")

                sub_lbl = ctk.CTkLabel(
                    right,
                    text="",
                    font=(theme.FONT_FAMILY, 11),
                    text_color=theme.TEXT_MUTED,
                    anchor="e",
                )
                sub_lbl.pack(anchor="e", pady=(0, 6))

                inspect_btn = ctk.CTkButton(
                    right,
                    text="Inspect Files",
                    width=105,
                    height=28,
                    fg_color=theme.BG_ELEVATED,
                    hover_color=theme.ACCENT_BLUE,
                    font=(theme.FONT_FAMILY, 11, "bold"),
                    command=lambda c=cat: self._open_inspector(c),
                )
                inspect_btn.pack(anchor="e")

                self.cat_widgets[cat.id] = {
                    "size_lbl": size_lbl,
                    "sub_lbl": sub_lbl,
                    "inspect_btn": inspect_btn,
                }

    def _on_category_checkbox(self, cat: CleanCategory, var: ctk.BooleanVar) -> None:
        checked = bool(var.get())
        for item in cat.items:
            item.selected = checked
        self._refresh_category_displays()

    def _refresh_category_displays(self) -> None:
        total_sel = 0
        for cat in self.categories:
            w = self.cat_widgets.get(cat.id)
            if not w:
                continue
            if not cat.scanned:
                w["size_lbl"].configure(text="Scanning...", text_color=theme.TEXT_MUTED)
                w["sub_lbl"].configure(text="")
                continue

            sel_bytes = cat.selected_bytes
            total_sel += sel_bytes
            has_selected = len(cat.selected_items) > 0
            if cat.id in self.cat_vars and cat.items:
                self.cat_vars[cat.id].set(has_selected)

            w["size_lbl"].configure(
                text=format_bytes(sel_bytes) if has_selected else format_bytes(cat.total_bytes),
                text_color=(
                    theme.ACCENT_GREEN
                    if sel_bytes > 50 * 1024 * 1024
                    else (theme.TEXT_PRIMARY if sel_bytes > 0 else theme.TEXT_MUTED)
                ),
            )
            if cat.error:
                w["sub_lbl"].configure(text=cat.error, text_color=theme.ACCENT_AMBER)
            elif sel_bytes != cat.total_bytes and has_selected:
                w["sub_lbl"].configure(
                    text=f"{len(cat.selected_items)}/{len(cat.items)} items ({format_bytes(cat.total_bytes)} total)",
                    text_color=theme.TEXT_MUTED,
                )
            else:
                w["sub_lbl"].configure(
                    text=f"{len(cat.items)} items • {cat.total_files:,} files",
                    text_color=theme.TEXT_MUTED,
                )

        mode = self.cfg.get("delete_mode", "trash")
        self.selected_total_lbl.configure(text=f"Selected to clean: {format_bytes(total_sel)}")
        if mode == "trash":
            self.clean_now_btn.configure(
                text=f"Move to Recycle Bin ({format_bytes(total_sel)})",
                fg_color=theme.ACCENT_GREEN,
                hover_color=theme.ACCENT_GREEN_HOVER,
            )
        else:
            self.clean_now_btn.configure(
                text=f"Delete Permanently ({format_bytes(total_sel)})",
                fg_color=theme.ACCENT_RED,
                hover_color=theme.ACCENT_RED_HOVER,
            )

    def _open_inspector(self, cat: CleanCategory) -> None:
        if not cat.scanned:
            messagebox.showinfo("Scanning", "Please wait until the scan completes.")
            return
        InspectorModal(
            self,
            cat,
            on_update=self._refresh_category_displays,
            on_whitelist=self._add_to_whitelist,
        )

    def _add_to_whitelist(self, path: str) -> None:
        wl: list[str] = self.cfg.get("whitelist", [])
        norm = os.path.abspath(path)
        if norm not in wl:
            wl.append(norm)
            self.cfg["whitelist"] = wl
            save_config(self.cfg)
            self.set_status(f"Added to whitelist (will never be cleaned): {norm}")

    def start_category_scan(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.rescan_cats_btn.configure(state="disabled", text="Scanning...")
        self.clean_now_btn.configure(state="disabled")
        self.progress_bar.pack(side="right", padx=14)
        self.progress_bar.set(0)
        self.set_status("Scanning cleanup categories...")

        # Rebuild categories fresh so new files/updaters are caught
        old_checks = {cid: v.get() for cid, v in self.cat_vars.items()}
        self.categories = build_categories()
        for c in self.categories:
            if c.id in old_checks:
                c.default_checked = old_checks[c.id]
        self._render_category_cards()

        whitelist = self.cfg.get("whitelist", [])

        def _worker():
            def _prog(name: str, done: int, total: int):
                self._safe_after(lambda n=name, d=done, t=total: self._on_scan_progress(n, d, t))

            scan_all_categories(
                self.categories,
                whitelist=whitelist,
                on_progress=_prog,
                cancel_flag=lambda: self._closing or self._cancel_requested,
            )
            self._safe_after(self._on_categories_scanned)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_scan_progress(self, name: str, done: int, total: int) -> None:
        self.progress_bar.set(done / max(1, total))
        self.set_status(f"Scanned ({done}/{total}): {name}")

    def _on_categories_scanned(self) -> None:
        self._busy = False
        self.progress_bar.pack_forget()
        self.rescan_cats_btn.configure(state="normal", text="Rescan Categories")
        self.clean_now_btn.configure(state="normal")
        self._refresh_category_displays()
        total_avail = sum(c.total_bytes for c in self.categories)
        self.set_status(f"Scan complete. Found {format_bytes(total_avail)} of cleanable cache/temp files.")

    def _run_clean_workflow(self, dry_run: bool) -> None:
        if self._busy:
            return
        active_cats = [c for c in self.categories if c.selected_items]
        if not active_cats:
            messagebox.showinfo("Nothing Selected", "Please select at least one item or category to clean.")
            return

        mode = self.cfg.get("delete_mode", "trash")

        if dry_run:
            res = execute_cleanup(
                active_cats,
                mode=mode,  # type: ignore[arg-type]
                dry_run=True,
                whitelist=self.cfg.get("whitelist", []),
            )
            ReportModal(self, res)
            return

        # Warn if Admin-only categories are selected while not running as Admin
        needs_admin = [c.name for c in active_cats if c.requires_admin]
        if needs_admin and not self.admin_mode:
            proceed = messagebox.askyesno(
                "Administrator Rights Recommended",
                "You selected Windows system folders that normally require Administrator rights:\n"
                + "\n".join(f"• {n}" for n in needs_admin)
                + "\n\nWithout Admin rights, protected Windows files will be skipped. Continue anyway?",
            )
            if not proceed:
                return

        ConfirmCleanModal(
            self,
            active_cats,
            mode=mode,  # type: ignore[arg-type]
            on_confirm=lambda: self._execute_clean_async(active_cats, mode),
        )

    def _execute_clean_async(self, active_cats: list[CleanCategory], mode: str) -> None:
        self._busy = True
        self.clean_now_btn.configure(state="disabled")
        self.rescan_cats_btn.configure(state="disabled")
        self.progress_bar.pack(side="right", padx=14)
        self.progress_bar.set(0)
        self.set_status("Cleaning selected items...")

        whitelist = self.cfg.get("whitelist", [])

        def _worker():
            def _prog(label: str, done: int, total: int):
                self._safe_after(
                    lambda lbl=label, d=done, t=total: (
                        self.progress_bar.set(d / max(1, t)),
                        self.set_status(f"Cleaning ({d}/{t}): {lbl}"),
                    )
                )

            res = execute_cleanup(
                active_cats,
                mode=mode,  # type: ignore[arg-type]
                dry_run=False,
                whitelist=whitelist,
                on_progress=_prog,
                cancel_flag=lambda: self._closing or self._cancel_requested,
            )
            self._safe_after(lambda r=res: self._on_clean_finished(r))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_clean_finished(self, res) -> None:
        self._busy = False
        self.progress_bar.pack_forget()
        self.clean_now_btn.configure(state="normal")
        self.rescan_cats_btn.configure(state="normal")
        self.refresh_drive_and_bin()
        rb = get_recycle_bin_info("C:\\")
        self.set_status(f"Cleaned {format_bytes(res.freed_bytes)} ({res.items_deleted} items).")

        ReportModal(
            self,
            res,
            recycle_bin_bytes=rb.size_bytes,
            on_empty_recycle_bin=self._handle_empty_recycle_bin,
        )
        # Re-scan to refresh remaining sizes
        self.start_category_scan()

    # =========================================================================
    # PAGE 2: PYTHON & WEBDEV DEEP CLEANER
    # =========================================================================
    def _build_dev_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color="transparent")

        top = ctk.CTkFrame(page, fg_color=theme.BG_CARD, corner_radius=10)
        top.pack(fill="x", pady=(0, 10))

        txt = ctk.CTkFrame(top, fg_color="transparent")
        txt.pack(side="left", padx=14, pady=12)
        ctk.CTkLabel(
            txt,
            text="Python & WebDev Project Artifact Scanner",
            font=(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            txt,
            text="Finds leftover __pycache__, pytest caches, and inactive node_modules folders across your project folders.",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
        ).pack(anchor="w")

        self.dev_scan_btn = ctk.CTkButton(
            top,
            text="Scan Python & WebDev",
            width=185,
            height=38,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=(theme.FONT_FAMILY, 13, "bold"),
            command=self._start_dev_scan,
        )
        self.dev_scan_btn.pack(side="right", padx=14, pady=12)

        self.dev_scroll = ctk.CTkScrollableFrame(page, fg_color=theme.BG_SIDEBAR, corner_radius=10)
        self.dev_scroll.pack(fill="both", expand=True, pady=(0, 10))

        ctk.CTkLabel(
            self.dev_scroll,
            text="Click 'Scan Python & WebDev' to inspect your user/dev folders for:\n"
            "• Python __pycache__, .pytest_cache, .ruff_cache directories\n"
            f"• Inactive node_modules folders untouched for >{self.cfg.get('stale_days', 30)} days\n\n"
            "Note: Global pip, uv, npm, and HuggingFace/.cache folders are also available in Quick & Safe Clean.",
            font=(theme.FONT_FAMILY, 13),
            text_color=theme.TEXT_SECONDARY,
            justify="center",
        ).pack(pady=50)

        btm = ctk.CTkFrame(page, fg_color=theme.BG_CARD, corner_radius=10)
        btm.pack(fill="x")
        self.dev_total_lbl = ctk.CTkLabel(
            btm,
            text="Selected dev artifacts: 0 B",
            font=(theme.FONT_FAMILY, 13, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        self.dev_total_lbl.pack(side="left", padx=16, pady=12)

        self.dev_clean_btn = ctk.CTkButton(
            btm,
            text="Move Dev Artifacts to Recycle Bin",
            height=36,
            width=240,
            fg_color=theme.ACCENT_GREEN,
            hover_color=theme.ACCENT_GREEN_HOVER,
            font=(theme.FONT_FAMILY, 13, "bold"),
            state="disabled",
            command=self._clean_dev_artifacts,
        )
        self.dev_clean_btn.pack(side="right", padx=14, pady=10)

        return page

    def _start_dev_scan(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.dev_scan_btn.configure(state="disabled", text="Scanning...")
        self.set_status("Scanning project folders for Python & Node artifacts...")
        roots = self.cfg.get("dev_scan_roots", [os.path.expanduser("~")])
        stale_days = int(self.cfg.get("stale_days", 30))
        wl = self.cfg.get("whitelist", [])

        def _worker():
            node_cat, py_cat = scan_dev_artifacts(
                roots,
                stale_days=stale_days,
                whitelist=wl,
                cancel_flag=lambda: self._closing or self._cancel_requested,
            )
            self._safe_after(lambda pc=py_cat, nc=node_cat: self._on_dev_scanned([pc, nc]))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_dev_scanned(self, cats: list[CleanCategory]) -> None:
        self._busy = False
        self.dev_categories = cats
        self.dev_scan_btn.configure(state="normal", text="Rescan Python & WebDev")
        self._render_dev_results()
        self.set_status("Python & WebDev scan finished.")

    def _render_dev_results(self) -> None:
        for w in self.dev_scroll.winfo_children():
            w.destroy()
        self.dev_cat_vars.clear()

        for cat in self.dev_categories:
            card = ctk.CTkFrame(self.dev_scroll, fg_color=theme.BG_CARD, corner_radius=10)
            card.pack(fill="x", padx=8, pady=6)

            hdr = ctk.CTkFrame(card, fg_color="transparent")
            hdr.pack(fill="x", padx=14, pady=(10, 4))

            ctk.CTkLabel(
                hdr,
                text=cat.name,
                font=(theme.FONT_FAMILY, 14, "bold"),
                text_color=theme.TEXT_PRIMARY,
            ).pack(side="left")

            ctk.CTkLabel(
                hdr,
                text=f"{format_bytes(cat.selected_bytes)} selected ({len(cat.items)} folders)",
                font=(theme.FONT_FAMILY, 13, "bold"),
                text_color=theme.ACCENT_GREEN if cat.selected_bytes > 0 else theme.TEXT_MUTED,
            ).pack(side="right")

            ctk.CTkLabel(
                card,
                text=f"{cat.what_it_has}  |  {cat.delete_impact}",
                font=(theme.FONT_FAMILY, 11),
                text_color=theme.TEXT_SECONDARY,
                anchor="w",
                wraplength=760,
                justify="left",
            ).pack(fill="x", padx=14, pady=(0, 8))

            if not cat.items:
                ctk.CTkLabel(
                    card,
                    text="  None found in your configured dev scan roots.",
                    font=(theme.FONT_FAMILY, 12),
                    text_color=theme.TEXT_MUTED,
                    anchor="w",
                ).pack(fill="x", padx=14, pady=(0, 10))
                continue

            for item in cat.items[:25]:
                row = ctk.CTkFrame(card, fg_color=theme.BG_ELEVATED, corner_radius=6)
                row.pack(fill="x", padx=14, pady=2)
                var = ctk.BooleanVar(value=item.selected)

                def _tgl(it=item, v=var):
                    it.selected = bool(v.get())
                    self._update_dev_total()

                ctk.CTkCheckBox(row, text="", variable=var, width=24, command=_tgl).pack(
                    side="left", padx=(8, 4), pady=6
                )
                ctk.CTkLabel(
                    row,
                    text=f"{item.name}  ({item.description})\n{item.path}",
                    font=(theme.FONT_MONO, 10),
                    text_color=theme.TEXT_PRIMARY,
                    anchor="w",
                    justify="left",
                ).pack(side="left", fill="x", expand=True, padx=4, pady=4)
                ctk.CTkLabel(
                    row,
                    text=format_bytes(item.size_bytes),
                    font=(theme.FONT_FAMILY, 12, "bold"),
                    text_color=theme.ACCENT_BLUE,
                ).pack(side="right", padx=10)

            if len(cat.items) > 25:
                ctk.CTkButton(
                    card,
                    text=f"Inspect All {len(cat.items)} Folders",
                    height=28,
                    fg_color=theme.BG_ELEVATED,
                    command=lambda c=cat: InspectorModal(
                        self, c, on_update=self._render_dev_results, on_whitelist=self._add_to_whitelist
                    ),
                ).pack(pady=8)

        self._update_dev_total()

    def _update_dev_total(self) -> None:
        total_sel = sum(c.selected_bytes for c in self.dev_categories)
        self.dev_total_lbl.configure(text=f"Selected dev artifacts: {format_bytes(total_sel)}")
        self.dev_clean_btn.configure(state="normal" if total_sel > 0 else "disabled")

    def _clean_dev_artifacts(self) -> None:
        active = [c for c in self.dev_categories if c.selected_items]
        if not active:
            return
        mode = self.cfg.get("delete_mode", "trash")
        ConfirmCleanModal(
            self,
            active,
            mode=mode,  # type: ignore[arg-type]
            on_confirm=lambda: self._execute_dev_clean(active, mode),
        )

    def _execute_dev_clean(self, active: list[CleanCategory], mode: str) -> None:
        res = execute_cleanup(
            active,
            mode=mode,  # type: ignore[arg-type]
            dry_run=False,
            whitelist=self.cfg.get("whitelist", []),
        )
        self.refresh_drive_and_bin()
        rb = get_recycle_bin_info("C:\\")
        ReportModal(
            self,
            res,
            recycle_bin_bytes=rb.size_bytes,
            on_empty_recycle_bin=self._handle_empty_recycle_bin,
        )
        self._start_dev_scan()

    # =========================================================================
    # PAGE 3: SYSTEM TOOLS
    # =========================================================================
    def _build_system_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color="transparent")
        self.sys_scroll = ctk.CTkScrollableFrame(page, fg_color=theme.BG_SIDEBAR, corner_radius=10)
        self.sys_scroll.pack(fill="both", expand=True)
        return page

    def _refresh_system_tools(self) -> None:
        for w in self.sys_scroll.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self.sys_scroll,
            text="Windows Deep System Space Tools",
            font=(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(12, 8))

        # 1. Recycle Bin Card
        rb = get_recycle_bin_info("C:\\")
        rb_card = ctk.CTkFrame(self.sys_scroll, fg_color=theme.BG_CARD, corner_radius=10)
        rb_card.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            rb_card,
            text=f"Windows Recycle Bin on C: — {format_bytes(rb.size_bytes)} ({rb.item_count} items)",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            rb_card,
            text="Items sent to Trash by PCleaner stay safely in the Recycle Bin until emptied. Empty it when you are confident you don't need them back.",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
            wraplength=760,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkButton(
            rb_card,
            text=f"Empty Recycle Bin ({format_bytes(rb.size_bytes)})",
            height=34,
            fg_color=theme.ACCENT_AMBER,
            hover_color="#d97706",
            text_color="#111827",
            font=(theme.FONT_FAMILY, 12, "bold"),
            state="normal" if rb.size_bytes > 0 or rb.item_count > 0 else "disabled",
            command=lambda: (self._handle_empty_recycle_bin(), self._refresh_system_tools()),
        ).pack(anchor="w", padx=14, pady=(0, 12))

        # 2. WSL2 / Docker VHDX Inspector
        vhdxs = find_wsl_vhdx_files()
        wsl_card = ctk.CTkFrame(self.sys_scroll, fg_color=theme.BG_CARD, corner_radius=10)
        wsl_card.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            wsl_card,
            text="WSL2 / Docker Virtual Disks (.vhdx)",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            wsl_card,
            text="WSL2 virtual disk files expand automatically when you install packages inside Linux, and NEVER release free space back to Windows automatically.",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
            wraplength=760,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 6))

        if vhdxs:
            for v in vhdxs:
                ctk.CTkLabel(
                    wsl_card,
                    text=f"  • {v.label}: {format_bytes(v.size_bytes)} — {v.path}",
                    font=(theme.FONT_MONO, 11),
                    text_color=theme.ACCENT_BLUE,
                    anchor="w",
                ).pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(
                wsl_card,
                text="To shrink a VHDX safely: Run `wsl --shutdown` in PowerShell, then `Optimize-VHD -Path \"<path>\" -Mode Full` (or compact via diskpart).",
                font=(theme.FONT_FAMILY, 11),
                text_color=theme.TEXT_MUTED,
                anchor="w",
                wraplength=760,
            ).pack(fill="x", padx=14, pady=(4, 12))
        else:
            ctk.CTkLabel(
                wsl_card,
                text="  No large WSL2/Docker .vhdx files detected in AppData\\Local.",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.TEXT_MUTED,
                anchor="w",
            ).pack(fill="x", padx=14, pady=(0, 12))

        # 3. Windows Component Store (DISM)
        dism_card = ctk.CTkFrame(self.sys_scroll, fg_color=theme.BG_CARD, corner_radius=10)
        dism_card.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            dism_card,
            text="Windows Component Store Cleanup (WinSxS / DISM)",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            dism_card,
            text="Safely removes superseded Windows Update backup files inside C:\\Windows\\WinSxS. Can reclaim 1–6 GB safely (Requires Administrator).",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
            wraplength=760,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 8))

        self.dism_log_lbl = ctk.CTkLabel(
            dism_card,
            text="",
            font=(theme.FONT_MONO, 10),
            text_color=theme.TEXT_MUTED,
            anchor="w",
        )
        self.dism_log_lbl.pack(fill="x", padx=14, pady=(0, 6))

        self.dism_btn = ctk.CTkButton(
            dism_card,
            text="Run DISM Cleanup" if self.admin_mode else "Requires Admin Mode (Click Header)",
            height=34,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            state="normal" if self.admin_mode else "disabled",
            command=self._start_dism,
        )
        self.dism_btn.pack(anchor="w", padx=14, pady=(0, 12))

        # 4. Hibernation File
        h_exists, h_size = get_hibernation_status()
        hib_card = ctk.CTkFrame(self.sys_scroll, fg_color=theme.BG_CARD, corner_radius=10)
        hib_card.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            hib_card,
            text=f"Windows Hibernation (hiberfil.sys) — {'Enabled (' + format_bytes(h_size) + ')' if h_exists else 'Disabled (0 B used)'}",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            hib_card,
            text="Hibernation saves RAM contents to C:\\hiberfil.sys. Disabling it if you only use Sleep or Shut Down saves several GB immediately.",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
            wraplength=760,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 10))

        if self.admin_mode:
            ctk.CTkButton(
                hib_card,
                text="Disable Hibernation" if h_exists else "Enable Hibernation",
                height=32,
                fg_color=theme.BG_ELEVATED,
                hover_color=theme.ACCENT_BLUE,
                command=lambda: self._toggle_hibernation(not h_exists),
            ).pack(anchor="w", padx=14, pady=(0, 12))

    def _start_dism(self) -> None:
        self.dism_btn.configure(state="disabled", text="Running DISM...")
        self.set_status("Running Windows DISM Component Store cleanup...")

        def _worker():
            ok, msg = run_dism_cleanup(
                on_line=lambda line: self._safe_after(lambda l=line: self.dism_log_lbl.configure(text=l))
            )
            self._safe_after(lambda o=ok, m=msg: self._on_dism_done(o, m))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_dism_done(self, ok: bool, msg: str) -> None:
        self.dism_btn.configure(state="normal", text="Run DISM Cleanup")
        self.refresh_drive_and_bin()
        self.set_status(msg)
        if ok:
            messagebox.showinfo("DISM Cleanup", msg)
        else:
            messagebox.showerror("DISM Failed", msg)

    def _toggle_hibernation(self, enable: bool) -> None:
        ok, msg = set_hibernation(enable)
        self.refresh_drive_and_bin()
        self._refresh_system_tools()
        if ok:
            messagebox.showinfo("Hibernation", msg)
        else:
            messagebox.showerror("Error", msg)

    # =========================================================================
    # PAGE 4: SETTINGS & HISTORY
    # =========================================================================
    def _build_settings_page(self, parent) -> ctk.CTkFrame:
        page = ctk.CTkFrame(parent, fg_color="transparent")
        self.settings_scroll = ctk.CTkScrollableFrame(page, fg_color=theme.BG_SIDEBAR, corner_radius=10)
        self.settings_scroll.pack(fill="both", expand=True)
        return page

    def _refresh_settings_lists(self) -> None:
        for w in self.settings_scroll.winfo_children():
            w.destroy()

        # Delete Mode Setting
        mode_card = ctk.CTkFrame(self.settings_scroll, fg_color=theme.BG_CARD, corner_radius=10)
        mode_card.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(
            mode_card,
            text="Deletion Safety Mode",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 4))

        mode_var = ctk.StringVar(value=self.cfg.get("delete_mode", "trash"))

        def _set_mode():
            self.cfg["delete_mode"] = mode_var.get()
            save_config(self.cfg)
            self._update_mode_indicator()
            self._refresh_category_displays()

        ctk.CTkRadioButton(
            mode_card,
            text="Move to Windows Recycle Bin (Recommended — safe & recoverable)",
            variable=mode_var,
            value="trash",
            command=_set_mode,
        ).pack(anchor="w", padx=14, pady=4)
        ctk.CTkRadioButton(
            mode_card,
            text="Permanent Delete (Use only if files are too large for Recycle Bin)",
            variable=mode_var,
            value="permanent",
            command=_set_mode,
        ).pack(anchor="w", padx=14, pady=(2, 12))

        # Dev Scan Roots
        roots_card = ctk.CTkFrame(self.settings_scroll, fg_color=theme.BG_CARD, corner_radius=10)
        roots_card.pack(fill="x", padx=10, pady=6)
        r_top = ctk.CTkFrame(roots_card, fg_color="transparent")
        r_top.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(
            r_top,
            text="Python & WebDev Scan Folders",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkButton(
            r_top,
            text="+ Add Folder",
            width=105,
            height=28,
            fg_color=theme.ACCENT_BLUE,
            command=self._add_dev_root,
        ).pack(side="right")

        for root_path in self.cfg.get("dev_scan_roots", []):
            row = ctk.CTkFrame(roots_card, fg_color=theme.BG_ELEVATED, corner_radius=6)
            row.pack(fill="x", padx=14, pady=3)
            ctk.CTkLabel(row, text=root_path, font=(theme.FONT_MONO, 11)).pack(side="left", padx=10, pady=6)
            ctk.CTkButton(
                row,
                text="Remove",
                width=70,
                height=24,
                fg_color="#7f1d1d",
                hover_color=theme.ACCENT_RED,
                command=lambda p=root_path: self._remove_dev_root(p),
            ).pack(side="right", padx=8, pady=4)
        ctk.CTkFrame(roots_card, fg_color="transparent", height=8).pack()

        # Whitelist Card
        wl_card = ctk.CTkFrame(self.settings_scroll, fg_color=theme.BG_CARD, corner_radius=10)
        wl_card.pack(fill="x", padx=10, pady=6)
        w_top = ctk.CTkFrame(wl_card, fg_color="transparent")
        w_top.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(
            w_top,
            text="Whitelist (Paths Never Cleaned)",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkButton(
            w_top,
            text="+ Exclude Folder",
            width=120,
            height=28,
            fg_color=theme.BG_ELEVATED,
            hover_color=theme.ACCENT_GREEN,
            command=self._add_whitelist_folder,
        ).pack(side="right")

        wl = self.cfg.get("whitelist", [])
        if not wl:
            ctk.CTkLabel(
                wl_card,
                text="No excluded paths yet. Click 'Keep Forever' in any File Inspector to add items here.",
                font=(theme.FONT_FAMILY, 11),
                text_color=theme.TEXT_MUTED,
                anchor="w",
            ).pack(fill="x", padx=14, pady=(0, 12))
        else:
            for item_p in wl:
                row = ctk.CTkFrame(wl_card, fg_color=theme.BG_ELEVATED, corner_radius=6)
                row.pack(fill="x", padx=14, pady=3)
                ctk.CTkLabel(row, text=item_p, font=(theme.FONT_MONO, 11)).pack(side="left", padx=10, pady=6)
                ctk.CTkButton(
                    row,
                    text="Remove",
                    width=70,
                    height=24,
                    fg_color="#7f1d1d",
                    command=lambda p=item_p: self._remove_whitelist(p),
                ).pack(side="right", padx=8, pady=4)
            ctk.CTkFrame(wl_card, fg_color="transparent", height=8).pack()

        # Cleanup History
        hist_card = ctk.CTkFrame(self.settings_scroll, fg_color=theme.BG_CARD, corner_radius=10)
        hist_card.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(
            hist_card,
            text="Recent Cleanup Audit History",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 6))

        history = load_history()
        if not history:
            ctk.CTkLabel(
                hist_card,
                text="No cleanup sessions recorded yet.",
                font=(theme.FONT_FAMILY, 11),
                text_color=theme.TEXT_MUTED,
                anchor="w",
            ).pack(fill="x", padx=14, pady=(0, 12))
        else:
            for h in history[:15]:
                ts = format_timestamp(h.get("timestamp", 0))
                freed = format_bytes(h.get("freed_bytes", 0))
                cnt = h.get("items_deleted", 0)
                mode_lbl = h.get("mode", "trash")
                cats_str = ", ".join(h.get("categories", [])[:3])
                ctk.CTkLabel(
                    hist_card,
                    text=f"  [{ts}]  {freed} ({cnt} items, mode={mode_lbl}) — {cats_str}",
                    font=(theme.FONT_MONO, 10),
                    text_color=theme.TEXT_SECONDARY,
                    anchor="w",
                ).pack(fill="x", padx=14, pady=2)
            ctk.CTkFrame(hist_card, fg_color="transparent", height=10).pack()

    def _add_dev_root(self) -> None:
        folder = filedialog.askdirectory(title="Select Folder Containing Python / WebDev Projects")
        if folder:
            roots = self.cfg.get("dev_scan_roots", [])
            norm = os.path.abspath(folder)
            if norm not in roots:
                roots.append(norm)
                self.cfg["dev_scan_roots"] = roots
                save_config(self.cfg)
                self._refresh_settings_lists()

    def _remove_dev_root(self, path: str) -> None:
        self.cfg["dev_scan_roots"] = [p for p in self.cfg.get("dev_scan_roots", []) if p != path]
        save_config(self.cfg)
        self._refresh_settings_lists()

    def _add_whitelist_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select Folder to Never Clean")
        if folder:
            self._add_to_whitelist(folder)
            self._refresh_settings_lists()

    def _remove_whitelist(self, path: str) -> None:
        self.cfg["whitelist"] = [p for p in self.cfg.get("whitelist", []) if p != path]
        save_config(self.cfg)
        self._refresh_settings_lists()
