"""Safe cleanup execution engine supporting Recycle Bin (send2trash) and dry-run previews."""

from __future__ import annotations

import os
import shutil
import stat
import time
from typing import Callable, Literal

from send2trash import send2trash

from core.models import CleanCategory, CleanItem, CleanResult
from core.scanner import measure_dir
from utils.config import append_history, is_whitelisted, load_config, save_config
from utils.formatting import is_reparse_point
from utils.logger import get_logger


def _remove_readonly_and_delete(path: str, is_dir: bool) -> None:
    """Permanently delete a file or folder (only used when mode == 'permanent')."""
    def _on_rm_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            raise

    if is_dir:
        shutil.rmtree(path, onerror=_on_rm_error)
    else:
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)


def _friendly_error(exc: Exception) -> str:
    msg = str(exc).lower()
    winerr = getattr(exc, "winerror", None)
    if winerr in (32, 33) or "being used by another process" in msg or "sharing violation" in msg:
        return "Skipped (currently in use by a running program)"
    if isinstance(exc, PermissionError) or winerr == 5 or "access is denied" in msg:
        return "Permission denied (may require closing app or running as Admin)"
    if "cannot find the path" in msg or winerr in (2, 3):
        return "Already removed"
    return f"Skipped ({str(exc)[:100]})"


def _delete_single_path(
    path: str,
    size_hint: int,
    is_dir: bool,
    mode: Literal["trash", "permanent"],
) -> tuple[int, int, list[tuple[str, int]], list[tuple[str, str]]]:
    """Delete or trash one path, falling back to per-child cleanup if a folder has locked files.

    Returns (freed_bytes, deleted_count, deleted_paths, skipped_paths).
    """
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path) or is_reparse_point(abs_path):
        return 0, 0, [], []

    try:
        if mode == "trash":
            send2trash(abs_path)
        else:
            _remove_readonly_and_delete(abs_path, is_dir)
        return size_hint, 1, [(abs_path, size_hint)], []
    except Exception as top_exc:
        # If it's a directory, try cleaning unlocked children individually so one locked log
        # doesn't block cleaning 3 GB of sibling files.
        if is_dir and os.path.isdir(abs_path):
            freed = 0
            deleted_cnt = 0
            deleted_list: list[tuple[str, int]] = []
            skipped_list: list[tuple[str, str]] = []
            try:
                with os.scandir(abs_path) as it:
                    children = list(it)
            except Exception as scan_exc:
                return 0, 0, [], [(abs_path, _friendly_error(scan_exc))]

            for child in children:
                if is_reparse_point(child):
                    continue
                c_is_dir = child.is_dir(follow_symlinks=False)
                if c_is_dir:
                    c_size, _, _ = measure_dir(child.path)
                else:
                    try:
                        c_size = child.stat(follow_symlinks=False).st_size
                    except OSError:
                        c_size = 0
                f_b, d_c, d_l, s_l = _delete_single_path(child.path, c_size, c_is_dir, mode)
                freed += f_b
                deleted_cnt += d_c
                deleted_list.extend(d_l)
                skipped_list.extend(s_l)

            # Try removing the now-empty parent folder if nothing was skipped inside
            if not skipped_list:
                try:
                    if mode == "trash":
                        send2trash(abs_path)
                    else:
                        os.rmdir(abs_path)
                except Exception:
                    pass
            return freed, deleted_cnt, deleted_list, skipped_list

        return 0, 0, [], [(abs_path, _friendly_error(top_exc))]


def execute_cleanup(
    categories: list[CleanCategory],
    mode: Literal["trash", "permanent"] = "trash",
    dry_run: bool = False,
    whitelist: list[str] | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
    cancel_flag: Callable[[], bool] | None = None,
) -> CleanResult:
    """Clean all selected CleanItems across the given categories (or run a dry-run preview)."""
    whitelist = whitelist or []
    logger = get_logger()

    items_to_clean: list[tuple[CleanCategory, CleanItem]] = []
    for cat in categories:
        for item in cat.selected_items:
            if not is_whitelisted(item.path, whitelist):
                items_to_clean.append((cat, item))

    total = len(items_to_clean)
    if dry_run:
        deleted_paths = [(item.path, item.size_bytes) for _, item in items_to_clean]
        total_bytes = sum(item.size_bytes for _, item in items_to_clean)
        return CleanResult(
            dry_run=True,
            mode=mode,
            freed_bytes=total_bytes,
            items_deleted=total,
            items_skipped=0,
            deleted_paths=deleted_paths,
        )

    freed_bytes = 0
    deleted_count = 0
    deleted_paths: list[tuple[str, int]] = []
    skipped_paths: list[tuple[str, str]] = []
    errors: list[str] = []

    logger.info(f"Starting cleanup (mode={mode}, items={total})")

    for idx, (cat, item) in enumerate(items_to_clean, start=1):
        if cancel_flag and cancel_flag():
            logger.info("Cleanup cancelled by user.")
            break
        if on_progress:
            on_progress(f"{cat.name}: {item.name}", idx, total)

        f_b, d_c, d_l, s_l = _delete_single_path(
            item.path,
            item.size_bytes,
            item.is_dir,
            mode,
        )
        freed_bytes += f_b
        deleted_count += d_c
        deleted_paths.extend(d_l)
        skipped_paths.extend(s_l)

    logger.info(
        f"Cleanup finished: freed={freed_bytes} bytes, deleted={deleted_count}, skipped={len(skipped_paths)}"
    )

    if freed_bytes > 0:
        cfg = load_config()
        cfg["total_freed_bytes"] = int(cfg.get("total_freed_bytes", 0)) + freed_bytes
        save_config(cfg)

    append_history(
        {
            "timestamp": time.time(),
            "mode": mode,
            "freed_bytes": freed_bytes,
            "items_deleted": deleted_count,
            "items_skipped": len(skipped_paths),
            "categories": list({cat.name for cat, _ in items_to_clean}),
        }
    )

    return CleanResult(
        dry_run=False,
        mode=mode,
        freed_bytes=freed_bytes,
        items_deleted=deleted_count,
        items_skipped=len(skipped_paths),
        deleted_paths=deleted_paths,
        skipped_paths=skipped_paths,
        errors=errors,
    )


def trash_custom_paths(
    paths_with_sizes: list[tuple[str, int, bool]],
    mode: Literal["trash", "permanent"] = "trash",
) -> CleanResult:
    """Trash or delete specific paths selected from Space Detective."""
    freed_bytes = 0
    deleted_count = 0
    deleted_paths: list[tuple[str, int]] = []
    skipped_paths: list[tuple[str, str]] = []

    for path, sz, is_dir in paths_with_sizes:
        f_b, d_c, d_l, s_l = _delete_single_path(path, sz, is_dir, mode)
        freed_bytes += f_b
        deleted_count += d_c
        deleted_paths.extend(d_l)
        skipped_paths.extend(s_l)

    if freed_bytes > 0:
        cfg = load_config()
        cfg["total_freed_bytes"] = int(cfg.get("total_freed_bytes", 0)) + freed_bytes
        save_config(cfg)

    append_history(
        {
            "timestamp": time.time(),
            "mode": f"detective_{mode}",
            "freed_bytes": freed_bytes,
            "items_deleted": deleted_count,
            "items_skipped": len(skipped_paths),
            "categories": ["Space Detective"],
        }
    )

    return CleanResult(
        dry_run=False,
        mode=mode,
        freed_bytes=freed_bytes,
        items_deleted=deleted_count,
        items_skipped=len(skipped_paths),
        deleted_paths=deleted_paths,
        skipped_paths=skipped_paths,
    )
