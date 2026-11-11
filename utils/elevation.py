"""Windows Administrator privilege detection and elevation helpers."""

from __future__ import annotations

import ctypes
import os
import sys


def is_admin() -> bool:
    """Return True if the current process has Windows Administrator privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def restart_as_admin(extra_args: list[str] | None = None) -> bool:
    """Relaunch the current application with UAC elevation.

    Returns True if the elevation prompt was triggered successfully.
    """
    try:
        executable = sys.executable
        script = os.path.abspath(sys.argv[0])
        args = [f'"{script}"']
        for arg in (extra_args if extra_args is not None else sys.argv[1:]):
            args.append(f'"{arg}"')
        params = " ".join(args)

        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            os.getcwd(),
            1,
        )
        return int(result) > 32
    except Exception:
        return False
