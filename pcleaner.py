"""PCleaner — Entry point supporting both Desktop GUI and optional CLI mode."""

from __future__ import annotations

import argparse
import sys

from core.categories import build_categories
from core.cleaner import execute_cleanup
from core.scanner import (
    get_drive_stats,
    scan_all_categories,
    scan_space_detective,
)
from utils.config import load_config
from utils.formatting import format_bytes


def run_cli(args: argparse.Namespace) -> int:
    cfg = load_config()
    whitelist = cfg.get("whitelist", [])

    total, used, free, pct = get_drive_stats("C:\\")
    print(f"Local Disk (C:): {format_bytes(used)} / {format_bytes(total)} ({pct:.1f}% used) — {format_bytes(free)} free\n")

    if args.detective:
        print("Running Space Detective scan on C:...")
        report = scan_space_detective(on_status=lambda m: print(f"  {m}"))
        print("\n=== Top Space Culprits ===")
        for sp in report.spotlights[:12]:
            print(f"  [{format_bytes(sp.size_bytes):>10}] {sp.title}")
            print(f"      What it has: {sp.explanation}")
            print(f"      Path: {sp.path}\n")
        if report.growth_entries:
            print("=== Growth Since Last Scan ===")
            for g in report.growth_entries[:8]:
                print(f"  +{format_bytes(g.delta_bytes):>10}  {g.path}")
        return 0

    cats = build_categories()
    print("Scanning cleanup categories...")
    scan_all_categories(cats, whitelist=whitelist)
    for cat in cats:
        status = "DEFAULT ON" if cat.default_checked else "OPTIONAL  "
        print(f"  [{status}] {format_bytes(cat.total_bytes):>10} | {cat.name}")
        print(f"               What it has: {cat.what_it_has}")

    if args.clean_safe:
        safe_cats = [c for c in cats if c.tier == "safe" and not c.requires_admin and c.selected_items]
        mode = cfg.get("delete_mode", "trash")
        res = execute_cleanup(
            safe_cats,
            mode=mode,  # type: ignore[arg-type]
            dry_run=not args.apply,
            whitelist=whitelist,
        )
        prefix = "DRY RUN PREVIEW" if res.dry_run else "CLEANED"
        print(f"\n[{prefix}] {format_bytes(res.freed_bytes)} ({res.items_deleted} items, mode={res.mode})")
        for path, sz in res.deleted_paths[:20]:
            print(f"  - [{format_bytes(sz):>10}] {path}")
        if len(res.deleted_paths) > 20:
            print(f"  ... and {len(res.deleted_paths) - 20} more items")
        if not res.dry_run:
            print(f"Skipped: {res.items_skipped} items.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PCleaner — Windows C: Drive Space Detective & Safe Cleaner")
    parser.add_argument("--scan", action="store_true", help="Scan cleanup categories in CLI and exit")
    parser.add_argument("--detective", action="store_true", help="Run Space Detective report in CLI and exit")
    parser.add_argument("--clean-safe", action="store_true", help="Preview safe cleanup in CLI (pass --apply to execute)")
    parser.add_argument("--apply", action="store_true", help="Actually move items to Trash with --clean-safe")

    args = parser.parse_args()
    if args.scan or args.detective or args.clean_safe:
        return run_cli(args)

    from gui.app import PCleanerApp

    app = PCleanerApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
