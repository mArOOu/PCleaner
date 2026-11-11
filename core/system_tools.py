"""Windows-specific system maintenance helpers (Recycle Bin, DISM, WSL VHDX, Hibernation)."""

from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import dataclass
from typing import Callable


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


@dataclass
class RecycleBinInfo:
    size_bytes: int
    item_count: int


def get_recycle_bin_info(root_path: str = "C:\\") -> RecycleBinInfo:
    """Query exact size and item count currently inside the Windows Recycle Bin."""
    try:
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
        res = ctypes.windll.shell32.SHQueryRecycleBinW(root_path, ctypes.byref(info))
        if res == 0:
            return RecycleBinInfo(
                size_bytes=max(0, int(info.i64Size)),
                item_count=max(0, int(info.i64NumItems)),
            )
    except Exception:
        pass
    return RecycleBinInfo(size_bytes=0, item_count=0)


def empty_recycle_bin(root_path: str | None = None, no_sound: bool = True) -> tuple[bool, str]:
    """Empty the Windows Recycle Bin permanently (without confirmation popup since app confirms)."""
    # Flags: SHERB_NOCONFIRMATION = 0x1, SHERB_NOPROGRESSUI = 0x2, SHERB_NOSOUND = 0x4
    flags = 0x1 | 0x2 | (0x4 if no_sound else 0)
    try:
        res = ctypes.windll.shell32.SHEmptyRecycleBinW(None, root_path, flags)
        # S_OK = 0; E_UNEXPECTED (0x8000FFFF) happens if already empty
        if res == 0:
            return True, "Recycle Bin emptied successfully."
        if res & 0xFFFFFFFF == 0x8000FFFF:
            return True, "Recycle Bin is already empty."
        return False, f"Windows returned status code 0x{res & 0xFFFFFFFF:08X}."
    except Exception as exc:
        return False, str(exc)


def get_hibernation_status() -> tuple[bool, int]:
    """Return (hiberfil_exists, size_bytes)."""
    hiber_path = r"C:\hiberfil.sys"
    try:
        if os.path.exists(hiber_path):
            return True, os.path.getsize(hiber_path)
    except OSError:
        pass
    return False, 0


def set_hibernation(enabled: bool) -> tuple[bool, str]:
    """Enable or disable Windows Hibernation (requires Admin)."""
    flag = "on" if enabled else "off"
    try:
        proc = subprocess.run(
            ["powercfg", "-h", flag],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if proc.returncode == 0:
            return True, f"Hibernation turned {flag}."
        msg = (proc.stderr or proc.stdout or "").strip() or f"Exit code {proc.returncode}"
        return False, msg
    except Exception as exc:
        return False, str(exc)


@dataclass
class VhdxInfo:
    path: str
    size_bytes: int
    label: str


def find_wsl_vhdx_files() -> list[VhdxInfo]:
    """Locate WSL2 / Docker virtual disk (.vhdx) files under AppData\\Local."""
    local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local"))
    candidates = [
        os.path.join(local_appdata, "wsl"),
        os.path.join(local_appdata, "Docker"),
        os.path.join(local_appdata, "Packages"),
    ]
    results: list[VhdxInfo] = []
    seen: set[str] = set()
    for root in candidates:
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if fn.lower().endswith(".vhdx"):
                    full = os.path.join(dirpath, fn)
                    norm = os.path.normcase(full)
                    if norm in seen:
                        continue
                    seen.add(norm)
                    try:
                        sz = os.path.getsize(full)
                    except OSError:
                        sz = 0
                    label = "Docker Desktop VM Disk" if "docker" in norm else "WSL2 Linux Disk"
                    results.append(VhdxInfo(path=full, size_bytes=sz, label=label))
    results.sort(key=lambda x: x.size_bytes, reverse=True)
    return results


def run_dism_cleanup(on_line: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """Run Windows Component Store cleanup (DISM /StartComponentCleanup). Requires Admin."""
    try:
        proc = subprocess.Popen(
            ["Dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        lines: list[str] = []
        if proc.stdout:
            for line in proc.stdout:
                clean_line = line.rstrip()
                if clean_line:
                    lines.append(clean_line)
                    if on_line:
                        on_line(clean_line)
        rc = proc.wait()
        if rc == 0:
            return True, "Windows Component Store cleanup completed."
        return False, "\n".join(lines[-5:]) or f"DISM failed with code {rc}"
    except Exception as exc:
        return False, str(exc)
