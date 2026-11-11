"""Fast Windows disk scanner, category inspector, dev artifact finder, and Space Detective."""

from __future__ import annotations

import fnmatch
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from core.models import (
    CleanCategory,
    CleanItem,
    CulpritSpotlight,
    FolderNode,
    GrowthEntry,
    LargeFileEntry,
    SpaceReport,
)
from utils.config import is_whitelisted, load_snapshots, save_snapshot
from utils.formatting import format_bytes, is_reparse_point


def get_drive_stats(drive: str = "C:\\") -> tuple[int, int, int, float]:
    """Return (total_bytes, used_bytes, free_bytes, percent_used)."""
    usage = shutil.disk_usage(drive)
    pct = (usage.used / usage.total * 100.0) if usage.total else 0.0
    return usage.total, usage.used, usage.free, pct


def measure_dir(
    path: str,
    cancel_flag: Callable[[], bool] | None = None,
    large_files_out: list[LargeFileEntry] | None = None,
    min_large_bytes: int = 100 * 1024 * 1024,
) -> tuple[int, int, float]:
    """Recursively measure directory size (bytes), file count, and newest mtime.

    Uses os.scandir and skips reparse points/junctions to prevent double counting.
    Optionally collects individual files >= min_large_bytes in the same pass.
    """
    total_size = 0
    file_count = 0
    max_mtime = 0.0
    stack = [path]

    while stack:
        if cancel_flag and cancel_flag():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if is_reparse_point(entry):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            total_size += st.st_size
                            file_count += 1
                            if st.st_mtime > max_mtime:
                                max_mtime = st.st_mtime
                            if large_files_out is not None and st.st_size >= min_large_bytes:
                                _, ext = os.path.splitext(entry.name)
                                large_files_out.append(
                                    LargeFileEntry(
                                        path=entry.path,
                                        name=entry.name,
                                        size_bytes=st.st_size,
                                        mtime=st.st_mtime,
                                        ext=ext.lower(),
                                        explanation=_explain_file_ext(ext, entry.name, entry.path),
                                    )
                                )
                    except OSError:
                        continue
        except OSError:
            continue

    return total_size, file_count, max_mtime


def _describe_item(category_id: str, name: str, path: str, is_dir: bool) -> str:
    """Provide human-friendly context for an item inside a cleanup category."""
    low = name.lower()
    p_low = path.lower()
    if category_id == "user_temp" or category_id == "win_temp":
        if "remotion" in low:
            return "Remotion video render / webpack bundle temp cache"
        if "vscode" in low:
            return "VS Code updater / installer temp folder"
        if low.endswith(".log") or low.endswith(".txt"):
            return "Application log file"
        if low.endswith(".tmp"):
            return "Temporary scratch file"
        if low.endswith(".exe") or low.endswith(".msi"):
            return "Leftover installer binary"
        if is_dir:
            return "Temporary app working folder / extracted setup files"
        return "Temporary file"
    if category_id == "browser_caches":
        if "brave" in p_low:
            return f"Brave browser {name} (web assets/JS cache)"
        if "chrome" in p_low:
            return f"Google Chrome {name} (web assets/JS cache)"
        if "edge" in p_low:
            return f"Microsoft Edge {name} (web assets/JS cache)"
        if "firefox" in p_low:
            return f"Firefox {name} (web cache)"
        return "Browser cache folder"
    if category_id == "browser_site_storage":
        return f"Offline web app storage ({name}) inside browser profile"
    if category_id == "electron_updaters":
        return "Downloaded app update installer package"
    if category_id == "spotify_cache":
        return "Spotify audio/UI cache data"
    if category_id == "ai_playwright_caches":
        if "huggingface" in p_low or "huggingface" in low:
            return "Downloaded HuggingFace AI model weights & tokenizers"
        if "whisper" in p_low:
            return "Downloaded Whisper speech-to-text model files"
        if "torch" in p_low:
            return "PyTorch cached model checkpoints"
        if "playwright" in p_low or "puppeteer" in p_low:
            return "Headless Chromium/Firefox/WebKit browser binaries for automation"
    if category_id == "python_caches":
        return "Cached Python wheels (.whl) & source packages"
    if category_id == "node_caches":
        return "Cached npm/yarn/pnpm JavaScript packages"
    return "Cached data"


def scan_category(
    cat: CleanCategory,
    whitelist: list[str] | None = None,
    cancel_flag: Callable[[], bool] | None = None,
) -> CleanCategory:
    """Scan all target paths in a CleanCategory and populate CleanItem entries."""
    whitelist = whitelist or []
    items: list[CleanItem] = []
    seen_paths: set[str] = set()
    cat.error = ""

    for target_path in cat.paths:
        if cancel_flag and cancel_flag():
            break
        if not os.path.exists(target_path) or is_reparse_point(target_path):
            continue
        if is_whitelisted(target_path, whitelist):
            continue

        try:
            with os.scandir(target_path) as it:
                for entry in it:
                    if cancel_flag and cancel_flag():
                        break
                    if is_reparse_point(entry):
                        continue
                    if is_whitelisted(entry.path, whitelist):
                        continue

                    # Apply optional glob filter (e.g. thumbcache_*.db)
                    if cat.glob_patterns:
                        if not any(fnmatch.fnmatch(entry.name.lower(), pat.lower()) for pat in cat.glob_patterns):
                            continue

                    norm_p = os.path.normcase(entry.path)
                    if norm_p in seen_paths:
                        continue
                    seen_paths.add(norm_p)

                    try:
                        if entry.is_dir(follow_symlinks=False):
                            sz, cnt, mtime = measure_dir(entry.path, cancel_flag)
                            if sz == 0 and cnt == 0:
                                # Still record empty folders inside Temp/updaters cleanly
                                st = entry.stat(follow_symlinks=False)
                                mtime = st.st_mtime
                            items.append(
                                CleanItem(
                                    path=entry.path,
                                    name=entry.name,
                                    size_bytes=sz,
                                    is_dir=True,
                                    file_count=cnt,
                                    mtime=mtime,
                                    description=_describe_item(cat.id, entry.name, entry.path, True),
                                    selected=cat.default_checked,
                                )
                            )
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            items.append(
                                CleanItem(
                                    path=entry.path,
                                    name=entry.name,
                                    size_bytes=st.st_size,
                                    is_dir=False,
                                    file_count=1,
                                    mtime=st.st_mtime,
                                    description=_describe_item(cat.id, entry.name, entry.path, False),
                                    selected=cat.default_checked,
                                )
                            )
                    except OSError:
                        continue
        except PermissionError:
            cat.error = "Some folders require Administrator rights to inspect."
        except OSError as exc:
            cat.error = str(exc)

    items.sort(key=lambda i: i.size_bytes, reverse=True)
    cat.items = items
    cat.total_bytes = sum(i.size_bytes for i in items)
    cat.total_files = sum(i.file_count for i in items)
    cat.scanned = True
    return cat


def scan_all_categories(
    categories: list[CleanCategory],
    whitelist: list[str] | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
    cancel_flag: Callable[[], bool] | None = None,
) -> list[CleanCategory]:
    """Scan all cleanup categories concurrently."""
    total = len(categories)
    done = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {
            pool.submit(scan_category, cat, whitelist, cancel_flag): cat for cat in categories
        }
        for fut in as_completed(future_map):
            cat = future_map[fut]
            try:
                fut.result()
            except Exception as exc:
                cat.error = str(exc)
            done += 1
            if on_progress:
                on_progress(cat.name, done, total)
    return categories


def scan_dev_artifacts(
    roots: list[str],
    stale_days: int = 30,
    whitelist: list[str] | None = None,
    cancel_flag: Callable[[], bool] | None = None,
) -> tuple[CleanCategory, CleanCategory]:
    """Find stale node_modules and Python __pycache__ / .pytest_cache folders."""
    whitelist = whitelist or []
    now = time.time()
    stale_cutoff = now - (stale_days * 86400)

    node_items: list[CleanItem] = []
    py_cache_items: list[CleanItem] = []

    skip_dir_names = {
        "appdata",
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "$recycle.bin",
        "system volume information",
        ".git",
        ".hg",
        ".svn",
        "onedrive",
    }

    for root in roots:
        if not os.path.isdir(root):
            continue
        stack = [root]
        while stack:
            if cancel_flag and cancel_flag():
                break
            cur = stack.pop()
            if is_whitelisted(cur, whitelist) or is_reparse_point(cur):
                continue
            try:
                with os.scandir(cur) as it:
                    entries = list(it)
            except OSError:
                continue

            entry_names = {e.name.lower() for e in entries}
            for entry in entries:
                if cancel_flag and cancel_flag():
                    break
                if is_reparse_point(entry) or not entry.is_dir(follow_symlinks=False):
                    continue
                low = entry.name.lower()
                if low in skip_dir_names:
                    continue
                if is_whitelisted(entry.path, whitelist):
                    continue

                if low == "node_modules":
                    # Only flag if sibling package.json exists so user can reinstall cleanly
                    has_pkg = "package.json" in entry_names
                    sz, cnt, mtime = measure_dir(entry.path, cancel_flag)
                    # Also check parent dir mtime
                    try:
                        parent_mtime = os.stat(cur).st_mtime
                    except OSError:
                        parent_mtime = mtime
                    last_active = max(mtime, parent_mtime)
                    is_stale = last_active < stale_cutoff
                    if sz > 1024 * 1024 and (is_stale or not has_pkg):
                        note = (
                            f"Unused for {int((now - last_active) // 86400)}d; "
                            + ("has package.json (run `npm install` to restore)" if has_pkg else "no sibling package.json")
                        )
                        node_items.append(
                            CleanItem(
                                path=entry.path,
                                name=f"{os.path.basename(cur)}\\node_modules",
                                size_bytes=sz,
                                is_dir=True,
                                file_count=cnt,
                                mtime=last_active,
                                description=note,
                                selected=has_pkg and is_stale,
                            )
                        )
                    continue  # Never descend inside node_modules

                if low in ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"):
                    sz, cnt, mtime = measure_dir(entry.path, cancel_flag)
                    if sz > 0:
                        py_cache_items.append(
                            CleanItem(
                                path=entry.path,
                                name=f"{os.path.basename(cur)}\\{entry.name}",
                                size_bytes=sz,
                                is_dir=True,
                                file_count=cnt,
                                mtime=mtime,
                                description="Python bytecode / test runner cache",
                                selected=True,
                            )
                        )
                    continue

                if low in (".venv", "venv", "env"):
                    # Do NOT descend into virtual environments when looking for __pycache__
                    continue

                stack.append(entry.path)

    node_items.sort(key=lambda x: x.size_bytes, reverse=True)
    py_cache_items.sort(key=lambda x: x.size_bytes, reverse=True)

    stale_node_cat = CleanCategory(
        id="stale_node_modules",
        name=f"Inactive Project node_modules (>{stale_days}d untouched)",
        tier="dev",
        safety="Review First",
        what_it_has=(
            "Installed npm dependency folders inside old/inactive JavaScript projects."
        ),
        delete_impact=(
            "Safe when package.json exists: just run `npm install` in that project folder if you work on it again."
        ),
        default_checked=False,
        items=node_items,
        total_bytes=sum(i.size_bytes for i in node_items),
        total_files=sum(i.file_count for i in node_items),
        scanned=True,
    )

    pycache_cat = CleanCategory(
        id="python_pycache",
        name="Python Bytecode & Tool Caches (__pycache__ / pytest)",
        tier="dev",
        safety="Dev Safe",
        what_it_has=(
            "Compiled .pyc bytecode and test caches scattered across your Python script folders."
        ),
        delete_impact=(
            "100% safe to trash. Python automatically regenerates __pycache__ on next script run."
        ),
        default_checked=True,
        items=py_cache_items,
        total_bytes=sum(i.size_bytes for i in py_cache_items),
        total_files=sum(i.file_count for i in py_cache_items),
        scanned=True,
    )

    return stale_node_cat, pycache_cat


# --- SPACE DETECTIVE ENGINE ---

_KNOWN_FOLDER_EXPLANATIONS: dict[str, tuple[str, str, str]] = {
    "bravesoftware": (
        "Browser Profile & Caches",
        "Contains Brave Browser profiles, extensions, Service Worker caches, and offline Site File System data.",
        "Use the Quick Clean tab to purge Brave web cache and optionally clear Service Worker / File System storage.",
    ),
    "google": (
        "Browser Profile & Caches",
        "Contains Google Chrome profiles, extensions, and cached web resources.",
        "Use Quick Clean -> Browser Caches to safely clear Chrome's cache without touching passwords or bookmarks.",
    ),
    "spotify": (
        "Media App Cache",
        "Spotify caches streamed music tracks inside Spotify\\Data and embedded browser assets.",
        "Safe to clean via Quick Clean -> Spotify Cache (keeps your login & playlists intact).",
    ),
    "crossdevice": (
        "Windows Phone Link / Cross-Device Sync",
        "Windows Phone Link caches synced mobile photos, clipboard history, and device transfer buffers here.",
        "Open Phone Link settings or inspect this folder to move/clear old cached phone media.",
    ),
    "onedrive": (
        "Cloud Sync Folder",
        "Files synced locally with Microsoft OneDrive.",
        "Right-click large folders in OneDrive -> 'Free up space' to keep them cloud-only instead of deleting!",
    ),
    "temp": (
        "Temporary Files",
        "Temporary files and installers left behind by Windows and apps.",
        "100% safe to clean via Quick Clean -> User Temporary Files.",
    ),
    "npm-cache": (
        "WebDev Package Cache",
        "Global package cache saved by npm whenever you install JS libraries.",
        "Safe to purge via Quick Clean -> WebDev Package Caches.",
    ),
    "uv": (
        "Python Package Cache (uv)",
        "High-speed Python package & wheel cache maintained by `uv`.",
        "Safe to purge via Quick Clean -> Python Package Caches.",
    ),
    "wsl": (
        "Windows Subsystem for Linux (WSL2)",
        "Virtual disk image (ext4.vhdx) for Ubuntu/Linux or Docker. VHDX files grow automatically but never auto-shrink.",
        "Use System Tools -> WSL2 Compaction or run `wsl --shutdown` + compact VHDX to reclaim empty virtual space.",
    ),
    ".cache": (
        "Developer & AI Model Caches",
        "Commonly holds HuggingFace/Whisper AI models, PyTorch weights, or Playwright/Puppeteer browsers.",
        "Inspect inside! Old AI models you no longer test can easily eat 2–10 GB.",
    ),
    "winsxs": (
        "Windows Component Store",
        "Stores Windows feature components and older update backup versions.",
        "NEVER delete manually! Use System Tools -> DISM Component Cleanup (Admin) to shrink it safely.",
    ),
    "installer": (
        "Windows Installer Cache",
        "Stores .msi/.msp files needed to repair or uninstall installed programs.",
        "Do NOT delete manually — removing these can break uninstallers.",
    ),
    "softwaredistribution": (
        "Windows Update Staging",
        "Stores downloaded Windows Update installer packages.",
        "Safe to clean the Download subfolder via Quick Clean (requires Admin).",
    ),
    "notion": (
        "Notion Desktop App Data",
        "Holds offline workspace databases, local caches, and logs for Notion.",
        "Safe to clear Notion Cache/Code Cache/logs via Quick Clean -> Desktop App Caches (keeps your Notion workspaces intact).",
    ),
    "adobe": (
        "Adobe App & Media Caches",
        "Stores Adobe Premiere/After Effects/Photoshop media peak files and conformed audio/video caches.",
        "Media Cache Files are safe to clean via Quick Clean (Adobe regenerates them if you reopen old projects).",
    ),
    ".minecraft": (
        "Minecraft Worlds, Mods & Assets",
        "Contains Minecraft saved worlds, resource packs, modpacks, logs, and crash reports.",
        "Do NOT delete the whole folder if you want your saves! Explore inside to check old modpacks or logs.",
    ),
}


def explain_folder_name(name: str, full_path: str) -> str:
    low = name.lower()
    if low in _KNOWN_FOLDER_EXPLANATIONS:
        return _KNOWN_FOLDER_EXPLANATIONS[low][1]
    if low.endswith("-updater") or low.endswith("_updater"):
        return "App auto-updater staging directory (often leaves behind 100MB–1.5GB old installers)."
    if "docker" in low:
        return "Docker container images, volumes, and virtual disk data."
    if "discord" in low:
        return "Discord desktop app cache and packages."
    if "nvidia" in low or "amd" in low:
        return "Graphics driver shader caches and installer backups."
    if low == "downloads":
        return "Your Downloads folder — installers (.exe/.msi), archives (.zip), and media often pile up here."
    if low == "appdata":
        return "Hidden Windows folder holding app settings, browser profiles, caches, and temp files."
    if low == "programdata":
        return "Shared application data, game caches, and Windows Error Reporting logs."
    return ""


def _explain_file_ext(ext: str, name: str, path: str) -> str:
    e = ext.lower()
    p_low = path.lower()
    if e == ".vhdx" or e == ".vmdk" or e == ".vdi":
        return "Virtual machine / WSL2 / Docker disk image. Grows dynamically; needs compaction to shrink."
    if e == ".dmp" or "crashdump" in p_low:
        return "Memory crash dump file created when Windows or an app crashed. Usually safe to trash."
    if e in (".iso", ".img"):
        return "OS / software disk image. Often forgotten after installing Windows or a VM."
    if e in (".zip", ".rar", ".7z", ".tar", ".gz"):
        return "Compressed archive. Check if you already extracted its contents."
    if e in (".exe", ".msi", ".msix"):
        return "Application installer or binary."
    if e in (".mp4", ".mkv", ".mov", ".avi"):
        return "Video file."
    if e in (".safetensors", ".bin", ".pt", ".pth", ".onnx", ".gguf"):
        return "AI / Machine Learning model weights file."
    if e == ".log":
        return "Oversized text log file — safe to inspect/clear if an app got stuck logging."
    if name.lower() == "hiberfil.sys":
        return "Windows Hibernation system file (controlled via powercfg -h off/on)."
    if name.lower() == "pagefile.sys":
        return "Windows Virtual Memory paging file (managed by Windows; do not delete manually)."
    return "Large file"


def scan_folder_children(
    folder_path: str,
    cancel_flag: Callable[[], bool] | None = None,
    exclude_names: set[str] | None = None,
    large_files_out: list[LargeFileEntry] | None = None,
    min_large_bytes: int = 100 * 1024 * 1024,
) -> list[FolderNode]:
    """Scan immediate subfolders (and summarize direct files) of a given folder."""
    import threading

    nodes: list[FolderNode] = []
    if not os.path.isdir(folder_path):
        return nodes

    exclude_low = {n.lower() for n in exclude_names} if exclude_names else set()
    direct_files_size = 0
    direct_files_count = 0
    direct_max_mtime = 0.0
    sub_entries: list[os.DirEntry[str]] = []

    try:
        with os.scandir(folder_path) as it:
            for entry in it:
                if is_reparse_point(entry):
                    continue
                if entry.name.lower() in exclude_low:
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        sub_entries.append(entry)
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        direct_files_size += st.st_size
                        direct_files_count += 1
                        if st.st_mtime > direct_max_mtime:
                            direct_max_mtime = st.st_mtime
                        if large_files_out is not None and st.st_size >= min_large_bytes:
                            _, ext = os.path.splitext(entry.name)
                            large_files_out.append(
                                LargeFileEntry(
                                    path=entry.path,
                                    name=entry.name,
                                    size_bytes=st.st_size,
                                    mtime=st.st_mtime,
                                    ext=ext.lower(),
                                    explanation=_explain_file_ext(ext, entry.name, entry.path),
                                )
                            )
                except OSError:
                    continue
    except OSError:
        return nodes

    lf_lock = threading.Lock()

    def _measure_sub(p: str) -> tuple[int, int, float]:
        local_lf: list[LargeFileEntry] | None = [] if large_files_out is not None else None
        res = measure_dir(p, cancel_flag, large_files_out=local_lf, min_large_bytes=min_large_bytes)
        if local_lf and large_files_out is not None:
            with lf_lock:
                large_files_out.extend(local_lf)
        return res

    with ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {
            pool.submit(_measure_sub, entry.path): entry for entry in sub_entries
        }
        for fut in as_completed(future_map):
            if cancel_flag and cancel_flag():
                break
            entry = future_map[fut]
            try:
                sz, cnt, mtime = fut.result()
            except Exception:
                sz, cnt, mtime = 0, 0, 0.0
            if sz > 0 or cnt > 0:
                nodes.append(
                    FolderNode(
                        path=entry.path,
                        name=entry.name,
                        size_bytes=sz,
                        file_count=cnt,
                        mtime=mtime,
                        explanation=explain_folder_name(entry.name, entry.path),
                    )
                )

    if direct_files_size > 0:
        nodes.append(
            FolderNode(
                path=folder_path,
                name=f"[Files directly inside {os.path.basename(folder_path) or folder_path}]",
                size_bytes=direct_files_size,
                file_count=direct_files_count,
                mtime=direct_max_mtime,
                explanation="Individual files sitting directly in this folder (not in subfolders).",
            )
        )

    nodes.sort(key=lambda n: n.size_bytes, reverse=True)
    return nodes


def scan_space_detective(
    on_status: Callable[[str], None] | None = None,
    cancel_flag: Callable[[], bool] | None = None,
    min_large_file_mb: int = 100,
) -> SpaceReport:
    """Perform a fast, single-pass Space Detective diagnostic scan of C: drive."""
    total, used, free, _ = get_drive_stats("C:\\")
    user_profile = os.path.expanduser("~")
    local_appdata = os.environ.get("LOCALAPPDATA", os.path.join(user_profile, "AppData", "Local"))
    roaming_appdata = os.environ.get("APPDATA", os.path.join(user_profile, "AppData", "Roaming"))

    min_bytes = min_large_file_mb * 1024 * 1024
    large_files: list[LargeFileEntry] = []

    if on_status:
        on_status("Scanning AppData\\Local & AppData\\Roaming...")
    local_lf: list[LargeFileEntry] = []
    roaming_lf: list[LargeFileEntry] = []
    user_lf: list[LargeFileEntry] = []
    root_lf: list[LargeFileEntry] = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_local = pool.submit(scan_folder_children, local_appdata, cancel_flag, None, local_lf, min_bytes)
        f_roaming = pool.submit(scan_folder_children, roaming_appdata, cancel_flag, None, roaming_lf, min_bytes)
        f_user = pool.submit(scan_folder_children, user_profile, cancel_flag, {"appdata"}, user_lf, min_bytes)
        f_root = pool.submit(scan_folder_children, "C:\\", cancel_flag, {"users", "windows"}, root_lf, min_bytes)

        local_nodes = f_local.result()
        roaming_nodes = f_roaming.result()
        user_nodes = f_user.result()
        c_nodes = f_root.result()

    if on_status:
        on_status("Analyzing top space culprits and large files...")

    large_files.extend(local_lf)
    large_files.extend(roaming_lf)
    large_files.extend(user_lf)
    large_files.extend(root_lf)

    # Synthesize AppData node for user_nodes and Users/Windows nodes for C:\ Explorer view
    appdata_size = sum(n.size_bytes for n in local_nodes) + sum(n.size_bytes for n in roaming_nodes)
    appdata_files = sum(n.file_count for n in local_nodes) + sum(n.file_count for n in roaming_nodes)
    user_nodes.append(
        FolderNode(
            path=os.path.join(user_profile, "AppData"),
            name="AppData",
            size_bytes=appdata_size,
            file_count=appdata_files,
            mtime=time.time(),
            explanation=explain_folder_name("AppData", os.path.join(user_profile, "AppData")),
        )
    )
    user_nodes.sort(key=lambda n: n.size_bytes, reverse=True)

    users_size = sum(n.size_bytes for n in user_nodes)
    users_files = sum(n.file_count for n in user_nodes)
    c_nodes.append(
        FolderNode(
            path=r"C:\Users",
            name="Users",
            size_bytes=users_size,
            file_count=users_files,
            mtime=time.time(),
            explanation="User profiles, Desktop, Downloads, Documents, and hidden AppData.",
        )
    )

    measured_c = sum(n.size_bytes for n in c_nodes)
    est_windows = max(0, used - measured_c)
    c_nodes.append(
        FolderNode(
            path=r"C:\Windows",
            name="Windows",
            size_bytes=est_windows,
            file_count=0,
            mtime=time.time(),
            explanation="Windows OS, WinSxS Component Store & Update cache (~estimated; click Explore to scan exact subfolders).",
        )
    )
    c_nodes.sort(key=lambda n: n.size_bytes, reverse=True)

    # Combine key inspectable folders for spotlighting and snapshot tracking
    snapshot_map: dict[str, int] = {}
    for node in c_nodes + user_nodes + local_nodes + roaming_nodes:
        if not node.name.startswith("[Files directly"):
            snapshot_map[os.path.normcase(node.path)] = node.size_bytes

    # Build Culprit Spotlights (>= 300 MB)
    spotlights: list[CulpritSpotlight] = []
    threshold = 300 * 1024 * 1024
    seen_spotlight_paths: set[str] = set()

    candidate_nodes = local_nodes + roaming_nodes + user_nodes
    for node in candidate_nodes:
        if node.size_bytes < threshold or node.name.startswith("[Files directly"):
            continue
        norm = os.path.normcase(node.path)
        if norm in seen_spotlight_paths:
            continue
        low = node.name.lower()
        if low in ("appdata", "microsoft", "packages", "programs"):
            if node.size_bytes < 2.5 * 1024**3:
                continue
        seen_spotlight_paths.add(norm)

        if low in _KNOWN_FOLDER_EXPLANATIONS:
            cat_label, expl, rec = _KNOWN_FOLDER_EXPLANATIONS[low]
            sev = "high" if node.size_bytes >= 2 * 1024**3 else "medium"
        elif low.endswith("-updater") or low.endswith("_updater"):
            cat_label = "App Auto-Updater Leftovers"
            expl = f"{node.name} holds {format_bytes(node.size_bytes)} of downloaded app installer bundles."
            rec = "Safe to clean via Quick Clean -> App Auto-Updater Installers."
            sev = "high" if node.size_bytes >= 1 * 1024**3 else "medium"
        else:
            cat_label = "Large User / App Folder"
            expl = node.explanation or f"This folder uses {format_bytes(node.size_bytes)} across {node.file_count:,} files."
            rec = "Click 'Explore' below to inspect what's inside before deciding whether to keep or trash."
            sev = "high" if node.size_bytes >= 3 * 1024**3 else "info"

        spotlights.append(
            CulpritSpotlight(
                title=f"{node.name} ({format_bytes(node.size_bytes)})",
                path=node.path,
                size_bytes=node.size_bytes,
                category_label=cat_label,
                explanation=expl,
                recommendation=rec,
                severity=sev,
            )
        )

    spotlights.sort(key=lambda s: s.size_bytes, reverse=True)
    spotlights = spotlights[:18]

    # Deduplicate and filter out Windows OS binaries from large_files if any slipped in
    seen_lf: set[str] = set()
    unique_lf: list[LargeFileEntry] = []
    for lf in large_files:
        np = os.path.normcase(lf.path)
        if np not in seen_lf:
            seen_lf.add(np)
            unique_lf.append(lf)
    unique_lf.sort(key=lambda f: f.size_bytes, reverse=True)
    large_files = unique_lf[:50]

    # Compare against previous snapshot for "What grew recently?"
    prev_snapshots = load_snapshots()
    growth_entries: list[GrowthEntry] = []
    prev_time: float | None = None
    if prev_snapshots:
        last_snap = prev_snapshots[-1]
        prev_time = last_snap.get("timestamp")
        prev_sizes: dict[str, int] = last_snap.get("folders", {})
        for norm_path, cur_sz in snapshot_map.items():
            prev_sz = prev_sizes.get(norm_path, 0)
            delta = cur_sz - prev_sz
            if delta >= 50 * 1024 * 1024:  # Grew by >= 50 MB
                growth_entries.append(
                    GrowthEntry(
                        path=norm_path,
                        name=os.path.basename(norm_path) or norm_path,
                        previous_bytes=prev_sz,
                        current_bytes=cur_sz,
                        delta_bytes=delta,
                    )
                )
        growth_entries.sort(key=lambda g: g.delta_bytes, reverse=True)
        growth_entries = growth_entries[:15]

    # Save fresh snapshot
    save_snapshot({"timestamp": time.time(), "folders": snapshot_map})

    return SpaceReport(
        scanned_at=time.time(),
        drive_total=total,
        drive_used=used,
        drive_free=free,
        spotlights=spotlights,
        top_folders=c_nodes,
        large_files=large_files,
        growth_entries=growth_entries,
        previous_snapshot_time=prev_time,
    )
