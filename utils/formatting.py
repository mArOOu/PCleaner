"""Formatting and filesystem safety helpers for Windows."""

from __future__ import annotations

import os
import stat
import time
from datetime import datetime


def format_bytes(num_bytes: int | float) -> str:
    """Format byte count into a human-readable string."""
    size = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f} {unit}" if size < 100 else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def format_age(mtime: float) -> str:
    """Format a modification timestamp into a friendly relative age."""
    if not mtime:
        return "Unknown"
    delta = time.time() - mtime
    if delta < 60:
        return "Just now"
    if delta < 3600:
        mins = int(delta // 60)
        return f"{mins}m ago"
    if delta < 86400:
        hours = int(delta // 3600)
        return f"{hours}h ago"
    days = int(delta // 86400)
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        months = days // 30
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


def format_timestamp(ts: float) -> str:
    """Format timestamp as YYYY-MM-DD HH:MM."""
    if not ts:
        return "Unknown"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def is_reparse_point(entry_or_path: os.DirEntry[str] | str) -> bool:
    """Return True if the path is a Windows symlink, junction, or reparse point."""
    try:
        if isinstance(entry_or_path, os.DirEntry):
            if entry_or_path.is_symlink():
                return True
            st = entry_or_path.stat(follow_symlinks=False)
        else:
            if os.path.islink(entry_or_path):
                return True
            st = os.lstat(entry_or_path)
        attrs = getattr(st, "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return True
