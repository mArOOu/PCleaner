"""Cleanup category definitions tailored for Windows, Python, and WebDev."""

from __future__ import annotations

import glob
import os
from pathlib import Path

from core.models import CleanCategory


def _env(var: str, fallback: str = "") -> str:
    return os.environ.get(var, fallback)


def _chromium_cache_paths(user_data_dir: str, include_site_storage: bool = False) -> list[str]:
    """Discover cache directories across all profiles in a Chromium-based browser."""
    results: list[str] = []
    if not os.path.isdir(user_data_dir):
        return results

    # Top-level shader caches
    for sub in ("ShaderCache", "GrShaderCache", "GraphiteDawnCache", "DawnCache"):
        p = os.path.join(user_data_dir, sub)
        if os.path.exists(p):
            results.append(p)

    # Profile directories: Default, Profile 1, Profile 2, Guest Profile, etc.
    try:
        entries = os.listdir(user_data_dir)
    except OSError:
        return results

    profile_dirs = [
        os.path.join(user_data_dir, e)
        for e in entries
        if (e == "Default" or e.startswith("Profile ") or e == "Guest Profile")
        and os.path.isdir(os.path.join(user_data_dir, e))
    ]

    cache_subs = (
        ("Service Worker\\CacheStorage", "File System")
        if include_site_storage
        else (
            "Cache",
            "Code Cache",
            "GPUCache",
            "DawnGraphiteCache",
            "DawnWebGPUCache",
            "GrShaderCache",
            "ShaderCache",
        )
    )

    for prof in profile_dirs:
        for sub in cache_subs:
            p = os.path.join(prof, sub)
            if os.path.exists(p):
                results.append(p)
    return results


def _firefox_cache_paths(local_appdata: str) -> list[str]:
    results: list[str] = []
    profiles_root = os.path.join(local_appdata, "Mozilla", "Firefox", "Profiles")
    if not os.path.isdir(profiles_root):
        return results
    for entry in os.listdir(profiles_root):
        c2 = os.path.join(profiles_root, entry, "cache2")
        if os.path.isdir(c2):
            results.append(c2)
    return results


def _electron_updater_paths(local_appdata: str) -> list[str]:
    """Find bloated *-updater folders (e.g., notion-updater, discord-updater) in AppData\\Local."""
    results: list[str] = []
    if not os.path.isdir(local_appdata):
        return results
    try:
        for entry in os.listdir(local_appdata):
            if entry.lower().endswith("-updater") or entry.lower().endswith("_updater"):
                full = os.path.join(local_appdata, entry)
                if os.path.isdir(full):
                    results.append(full)
    except OSError:
        pass
    return results


def build_categories() -> list[CleanCategory]:
    """Build the full list of cleanable categories dynamically for the current Windows user."""
    user_profile = os.path.expanduser("~")
    local_appdata = _env("LOCALAPPDATA", os.path.join(user_profile, "AppData", "Local"))
    roaming_appdata = _env("APPDATA", os.path.join(user_profile, "AppData", "Roaming"))
    user_temp = _env("TEMP", os.path.join(local_appdata, "Temp"))
    win_dir = _env("WINDIR", r"C:\Windows")

    # 1. Browser core caches
    browser_cache_paths: list[str] = []
    browser_site_storage_paths: list[str] = []
    for base in (
        os.path.join(local_appdata, "Google", "Chrome", "User Data"),
        os.path.join(local_appdata, "Microsoft", "Edge", "User Data"),
        os.path.join(local_appdata, "BraveSoftware", "Brave-Browser", "User Data"),
        os.path.join(local_appdata, "Vivaldi", "User Data"),
        os.path.join(roaming_appdata, "Opera Software", "Opera Stable"),
    ):
        browser_cache_paths.extend(_chromium_cache_paths(base, include_site_storage=False))
        browser_site_storage_paths.extend(_chromium_cache_paths(base, include_site_storage=True))
    browser_cache_paths.extend(_firefox_cache_paths(local_appdata))

    # 2. VS Code caches
    vscode_paths = [
        p
        for p in (
            os.path.join(roaming_appdata, "Code", "Cache"),
            os.path.join(roaming_appdata, "Code", "CachedData"),
            os.path.join(roaming_appdata, "Code", "CachedExtensionVSIXs"),
            os.path.join(roaming_appdata, "Code", "logs"),
            os.path.join(roaming_appdata, "Code", "Service Worker", "CacheStorage"),
        )
        if os.path.exists(p)
    ]

    # 3. Discord, Figma & Notion desktop caches
    app_cache_paths = [
        p
        for p in (
            os.path.join(roaming_appdata, "discord", "Cache"),
            os.path.join(roaming_appdata, "discord", "Code Cache"),
            os.path.join(roaming_appdata, "discord", "GPUCache"),
            os.path.join(roaming_appdata, "Figma", "Cache"),
            os.path.join(roaming_appdata, "Figma", "Code Cache"),
            os.path.join(roaming_appdata, "Figma", "GPUCache"),
            os.path.join(roaming_appdata, "Notion", "Cache"),
            os.path.join(roaming_appdata, "Notion", "Code Cache"),
            os.path.join(roaming_appdata, "Notion", "GPUCache"),
            os.path.join(roaming_appdata, "Notion", "logs"),
            os.path.join(roaming_appdata, "Adobe", "Common", "Media Cache Files"),
            os.path.join(roaming_appdata, "Adobe", "Common", "Media Cache"),
            os.path.join(local_appdata, "Discord", "packages"),
        )
        if os.path.exists(p)
    ]

    # 4. Spotify cache
    spotify_paths = [
        p
        for p in (
            os.path.join(local_appdata, "Spotify", "Data"),
            os.path.join(local_appdata, "Spotify", "Storage"),
            os.path.join(local_appdata, "Spotify", "Browser", "Cache"),
            os.path.join(local_appdata, "Spotify", "Default", "Cache"),
            os.path.join(local_appdata, "Spotify", "Default", "Code Cache"),
        )
        if os.path.exists(p)
    ]

    # 5. Electron updater installers
    updater_paths = _electron_updater_paths(local_appdata)

    # 6. GPU Shader caches
    shader_paths = [
        p
        for p in (
            os.path.join(local_appdata, "D3DSCache"),
            os.path.join(local_appdata, "NVIDIA", "DXCache"),
            os.path.join(local_appdata, "NVIDIA", "GLCache"),
            os.path.join(local_appdata, "NVIDIA Corporation", "NV_Cache"),
            os.path.join(local_appdata, "AMD", "DxCache"),
            os.path.join(local_appdata, "AMD", "GLCache"),
        )
        if os.path.exists(p)
    ]

    # 7. Python & WebDev Caches
    pip_cache_paths = [
        p
        for p in (
            os.path.join(local_appdata, "pip", "cache"),
            os.path.join(local_appdata, "uv", "cache"),
        )
        if os.path.exists(p)
    ]

    npm_cache_paths = [
        p
        for p in (
            os.path.join(local_appdata, "npm-cache"),
            os.path.join(roaming_appdata, "npm-cache"),
            os.path.join(local_appdata, "Yarn", "Cache"),
            os.path.join(local_appdata, "pnpm-store"),
            os.path.join(local_appdata, "pnpm", "store"),
        )
        if os.path.exists(p)
    ]

    ai_browser_dev_cache = [
        p
        for p in (
            os.path.join(user_profile, ".cache", "huggingface"),
            os.path.join(user_profile, ".cache", "whisper"),
            os.path.join(user_profile, ".cache", "torch"),
            os.path.join(local_appdata, "ms-playwright"),
            os.path.join(user_profile, ".cache", "puppeteer"),
        )
        if os.path.exists(p)
    ]

    categories: list[CleanCategory] = [
        # --- TIER 1: 100% SAFE SYSTEM & TEMP ---
        CleanCategory(
            id="user_temp",
            name="User Temporary Files (%TEMP%)",
            tier="safe",
            safety="100% Safe",
            what_it_has=(
                "Temporary scratch files, installer extractions, and app session leftovers "
                f"stored in {user_temp}."
            ),
            delete_impact=(
                "100% safe to trash. Files currently locked by open programs are skipped automatically."
            ),
            default_checked=True,
            paths=[user_temp],
        ),
        CleanCategory(
            id="crash_dumps",
            name="Crash Dumps & Error Reports",
            tier="safe",
            safety="100% Safe",
            what_it_has=(
                "Memory dump files (.dmp) and Windows Error Reporting logs created after app crashes."
            ),
            delete_impact=(
                "100% safe to trash unless you are actively debugging a crash with a developer."
            ),
            default_checked=True,
            paths=[
                p
                for p in (
                    os.path.join(local_appdata, "CrashDumps"),
                    os.path.join(local_appdata, "Microsoft", "Windows", "WER"),
                    os.path.join(win_dir, "Minidump"),
                    r"C:\ProgramData\Microsoft\Windows\WER",
                )
                if os.path.exists(p)
            ],
        ),
        CleanCategory(
            id="thumb_cache",
            name="Windows Thumbnail & Icon Cache",
            tier="safe",
            safety="100% Safe",
            what_it_has=(
                "Pre-rendered preview images (thumbcache_*.db, iconcache_*.db) used by File Explorer."
            ),
            delete_impact=(
                "100% safe to trash. Windows automatically regenerates thumbnails as you browse folders."
            ),
            default_checked=True,
            paths=[os.path.join(local_appdata, "Microsoft", "Windows", "Explorer")],
            glob_patterns=["thumbcache_*.db", "iconcache_*.db"],
            clean_contents_only=True,
        ),
        CleanCategory(
            id="gpu_shaders",
            name="DirectX & GPU Shader Caches",
            tier="safe",
            safety="100% Safe",
            what_it_has=(
                "Compiled graphics shaders cached by Windows DirectX, NVIDIA, or AMD drivers."
            ),
            delete_impact=(
                "Safe to trash. Shaders regenerate cleanly the next time you launch games or GPU apps."
            ),
            default_checked=False,
            paths=shader_paths,
        ),
        CleanCategory(
            id="win_temp",
            name="Windows System Temp",
            tier="safe",
            safety="Admin Required",
            what_it_has=(
                r"System-wide temporary files generated by Windows services and installers (C:\Windows\Temp)."
            ),
            delete_impact=(
                "Safe to clean. Requires Administrator rights to remove protected service temp files."
            ),
            requires_admin=True,
            default_checked=True,
            paths=[os.path.join(win_dir, "Temp")],
        ),
        CleanCategory(
            id="win_update_cache",
            name="Windows Update Download Cache",
            tier="safe",
            safety="Admin Required",
            what_it_has=(
                r"Already-installed Windows Update installer packages cached in SoftwareDistribution\Download."
            ),
            delete_impact=(
                "Safe to remove after updates finish installing. Requires Administrator privileges."
            ),
            requires_admin=True,
            default_checked=True,
            paths=[os.path.join(win_dir, "SoftwareDistribution", "Download")],
        ),
        # --- TIER 2: BROWSERS & APP CACHES ---
        CleanCategory(
            id="browser_caches",
            name="Browser Web & Code Caches (Brave / Chrome / Edge / Firefox)",
            tier="browser_app",
            safety="Safe",
            what_it_has=(
                "Cached web images, compiled JavaScript (Code Cache), and GPU caches across browser profiles."
            ),
            delete_impact=(
                "Safe: Bookmarks, history, saved passwords, extensions, and open logins are NOT touched. "
                "Pages just reload assets once on next visit."
            ),
            default_checked=True,
            paths=browser_cache_paths,
        ),
        CleanCategory(
            id="browser_site_storage",
            name="Browser Offline Site Storage & Service Workers",
            tier="browser_app",
            safety="Review First",
            what_it_has=(
                "Heavy offline caches ('File System' & 'Service Worker\\CacheStorage') stored by web apps "
                "(e.g., Figma web, Mega, Canva, Notion web)."
            ),
            delete_impact=(
                "Usually safe: Passwords and bookmarks stay intact, though offline web apps or "
                "unsaved browser-tab downloads (e.g. Mega cache) will re-fetch."
            ),
            default_checked=False,
            paths=browser_site_storage_paths,
        ),
        CleanCategory(
            id="electron_updaters",
            name="App Auto-Updater Installers (e.g. notion-updater)",
            tier="browser_app",
            safety="Safe",
            what_it_has=(
                "Old downloaded installer bundles left behind by desktop apps (AppData\\Local\\*-updater)."
            ),
            delete_impact=(
                "Safe to trash. Installed apps keep working normally; if an update is pending it will re-download."
            ),
            default_checked=True,
            paths=updater_paths,
        ),
        CleanCategory(
            id="spotify_cache",
            name="Spotify Audio & Embedded Browser Cache",
            tier="browser_app",
            safety="Safe",
            what_it_has=(
                "Streamed music buffer files (Spotify\\Data / Storage) and UI browser cache."
            ),
            delete_impact=(
                "Safe: Your Spotify account and playlists remain intact. Any downloaded offline playlists "
                "will need to re-download if toggled."
            ),
            default_checked=False,
            paths=spotify_paths,
        ),
        CleanCategory(
            id="app_caches",
            name="Discord, Figma, Notion & Adobe Media Caches",
            tier="browser_app",
            safety="Safe",
            what_it_has=(
                "Cached images, media peak caches, logs, and UI assets stored by Discord, Figma, Notion, and Adobe."
            ),
            delete_impact=(
                "Safe: Account login and settings stay intact. Close Discord/Figma first for best cleanup."
            ),
            default_checked=True,
            paths=app_cache_paths,
        ),
        CleanCategory(
            id="vscode_caches",
            name="VS Code Editor Caches & Old Logs",
            tier="browser_app",
            safety="Safe",
            what_it_has=(
                "VS Code editor logs, cached extension VSIX installers, and UI code cache."
            ),
            delete_impact=(
                "Safe: Extensions, settings, keybindings, and workspaces are NOT modified."
            ),
            default_checked=True,
            paths=vscode_paths,
        ),
        # --- TIER 3: PYTHON & WEBDEV ---
        CleanCategory(
            id="python_caches",
            name="Python Package Caches (pip & uv)",
            tier="dev",
            safety="Dev Safe",
            what_it_has=(
                "Downloaded .whl wheels and source tarballs cached by pip and uv during package installs."
            ),
            delete_impact=(
                "Safe: Existing Python environments & scripts keep working. Future `pip`/`uv` installs "
                "will just download packages fresh."
            ),
            default_checked=True,
            paths=pip_cache_paths,
        ),
        CleanCategory(
            id="node_caches",
            name="WebDev Package Caches (npm / yarn / pnpm)",
            tier="dev",
            safety="Dev Safe",
            what_it_has=(
                "Global tarball caches stored by npm, yarn, and pnpm across JavaScript/TypeScript projects."
            ),
            delete_impact=(
                "Safe: Existing projects and `node_modules` keep working. Running `npm install` later "
                "will simply fetch packages from registry."
            ),
            default_checked=True,
            paths=npm_cache_paths,
        ),
        CleanCategory(
            id="ai_playwright_caches",
            name="AI Models & Headless Browser Caches (.cache / Playwright)",
            tier="dev",
            safety="Review First",
            what_it_has=(
                "Local HuggingFace/Whisper/PyTorch model weights and Playwright/Puppeteer browser binaries."
            ),
            delete_impact=(
                "Check before deleting! Scripts using Whisper/HuggingFace or Playwright will re-download "
                "deleted models/browsers (often 1–3 GB) the next time you run them."
            ),
            default_checked=False,
            paths=ai_browser_dev_cache,
        ),
    ]

    # Filter out categories that don't have any existing path on this machine,
    # except keep essential ones visible even if 0 bytes.
    return categories
