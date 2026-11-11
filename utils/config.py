"""Persistent user configuration, whitelist, snapshots, and cleanup history."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "data"
CONFIG_PATH = DATA_DIR / "config.json"
SNAPSHOT_PATH = DATA_DIR / "snapshots.json"
HISTORY_PATH = DATA_DIR / "history.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "delete_mode": "trash",  # "trash" (Recycle Bin) or "permanent"
    "low_space_threshold_gb": 20.0,
    "stale_days": 30,
    "whitelist": [],
    "dev_scan_roots": [
        os.path.expanduser("~"),
    ],
    "total_freed_bytes": 0,
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_data_dir()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    ensure_data_dir()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def is_whitelisted(path: str, whitelist: list[str]) -> bool:
    """Return True if path matches or lies inside any whitelisted path."""
    if not whitelist:
        return False
    norm_target = os.path.normcase(os.path.abspath(path))
    for w in whitelist:
        norm_w = os.path.normcase(os.path.abspath(w))
        if norm_target == norm_w or norm_target.startswith(norm_w + os.sep):
            return True
    return False


def load_snapshots() -> list[dict[str, Any]]:
    ensure_data_dir()
    if SNAPSHOT_PATH.exists():
        try:
            with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_snapshot(snapshot: dict[str, Any], max_keep: int = 10) -> None:
    ensure_data_dir()
    snapshots = load_snapshots()
    snapshots.append(snapshot)
    snapshots = snapshots[-max_keep:]
    try:
        with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            json.dump(snapshots, f, indent=2)
    except Exception:
        pass


def load_history() -> list[dict[str, Any]]:
    ensure_data_dir()
    if HISTORY_PATH.exists():
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def append_history(entry: dict[str, Any], max_keep: int = 50) -> None:
    ensure_data_dir()
    history = load_history()
    history.insert(0, entry)
    history = history[:max_keep]
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass
