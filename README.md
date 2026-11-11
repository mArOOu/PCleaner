# PCleaner — Windows `C:` Drive Space Detective & Safe Cleaner

A modern, transparent Windows desktop app and CLI utility designed to answer **"Why is my `C:` drive filling up?"** and safely reclaim gigabytes of space by moving expendable clutter to the **Windows Recycle Bin**.

---

## Why PCleaner?

Windows SSDs often fill up silently from hidden `AppData` bloat, Electron app auto-updaters, browser offline storage, package manager caches (`npm`, `pip`, `uv`), crash dumps, and uncompacted WSL2 virtual disks. Instead of blindly deleting mysterious folders, **PCleaner** explains **what every folder/file contains** and **what happens if you remove it**, lets you inspect individual items before cleaning, and sends everything to the **Windows Recycle Bin** by default.

---

## Key Features

### 1. Quick & Safe Cleaner (Multi-Tiered)
- **Tier 1 — Safe Windows & System Temp**
  - User Temporary Files (`%TEMP%`)
  - Crash Dumps & Windows Error Reports (`CrashDumps`, `WER`, `Minidump`)
  - Thumbnail & Icon Cache (`thumbcache_*.db`, `iconcache_*.db`)
  - DirectX / NVIDIA / AMD GPU Shader Caches
  - Windows System Temp & Windows Update Download Cache *(requires Admin)*
- **Tier 2 — Browsers & Desktop App Caches**
  - Web & Code Caches across all profiles for **Brave**, **Chrome**, **Edge**, **Vivaldi**, **Opera**, and **Firefox** *(never touches bookmarks, passwords, or logins)*
  - Separate reviewable toggle for heavy Browser Offline Site Storage (`Service Worker\CacheStorage` & `File System`)
  - App Auto-Updater leftover installers (`AppData\Local\*-updater`)
  - **Spotify** (`Data`, `Storage`, `Browser`), **Discord**, **Figma**, **Notion**, **Adobe Media Cache**, and **VS Code** caches/logs
- **Tier 3 — Python & WebDev Caches**
  - `pip` & `uv` package caches
  - `npm`, `yarn`, and `pnpm` caches
  - Optional reviewable toggle for AI model & headless browser caches (`.cache\huggingface`, `whisper`, `torch`, `ms-playwright`, `puppeteer`)

### 2. Space Detective ("What's Filling My `C:` Drive?")
- **Culprit Spotlights**: Plain-English cards highlighting the biggest hidden consumers in your User profile and `AppData`.
- **Snapshot Growth Diff**: Saves lightweight local folder size snapshots so subsequent scans show **exactly which folders grew** since your last check.
- **Interactive Folder Explorer**: Drill down from `C:\` with percentage bars, folder explanations, **Open in Explorer**, and protected-OS-path safeguards.
- **Large File Finder**: Surfaces individual files over `100 MB` (e.g., `.vhdx`, `.dmp`, `.iso`, `.zip`, `.safetensors`, videos) with file-type explanations.

### 3. Python & WebDev Project Scanner
- Hunts across your project roots for leftover `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and inactive `node_modules` directories untouched for 30+ days (verifying whether a sibling `package.json` exists).

### 4. Safety & Transparency First
- **Recycle Bin by Default**: Uses `send2trash` so cleaned files go to the Windows Recycle Bin first (recoverable anytime).
- **Live Recycle Bin Meter**: Displays exact Recycle Bin size on `C:` right in the header with an **Empty Trash** button so you know when to permanently release reclaimed space.
- **File Inspector Modal**: Click **Inspect Files** on any category to browse individual files/folders, filter by name, uncheck items to keep, or click **Keep Forever** to add paths to your persistent whitelist.
- **Dry-Run Preview & Confirmation Modal**: Preview exact paths and sizes before modifying anything, and gracefully skip files locked by active programs.

### 5. System Tools
- **WSL2 / Docker `.vhdx` Inspector**: Detects virtual disk files that don't auto-shrink and guides safe compaction.
- **Windows Component Store (`WinSxS`)**: Runs `DISM /Online /Cleanup-Image /StartComponentCleanup` *(Admin required)*.
- **Hibernation Inspector**: Displays `hiberfil.sys` size and lets Admins toggle `powercfg -h`.

---

## Installation (Windows)

**Requirements:** Windows 10/11 and Python 3.10+ (with `tkinter`).

```powershell
git clone https://github.com/mArOOu/PCleaner.git
cd PCleaner

python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
```

---

## Usage

### Desktop GUI
Double-click **`run_pcleaner.bat`**, or run:
```powershell
.\.venv\Scripts\pythonw.exe pcleaner.py
```
To add a shortcut on your Windows Desktop, run **`create_desktop_shortcut.ps1`** in PowerShell.

### CLI Mode
```powershell
# Scan and summarize all cleanup categories
.\.venv\Scripts\python.exe pcleaner.py --scan

# Run Space Detective culprit & growth analysis
.\.venv\Scripts\python.exe pcleaner.py --detective

# Dry-run preview of Tier 1 safe cleanup (no files modified)
.\.venv\Scripts\python.exe pcleaner.py --clean-safe

# Execute Tier 1 safe cleanup (moves items to Windows Recycle Bin)
.\.venv\Scripts\python.exe pcleaner.py --clean-safe --apply
```

---

## Project Structure

```text
PCleaner/
├── pcleaner.py                  # Main entry point (GUI + CLI)
├── run_pcleaner.bat             # 1-click Windows GUI launcher
├── create_desktop_shortcut.ps1  # Desktop shortcut helper
├── requirements.txt             # Python dependencies (customtkinter, send2trash, psutil)
├── core/
│   ├── categories.py            # Cleanup category definitions & dynamic path discovery
│   ├── cleaner.py               # Safe Recycle Bin / permanent deletion & audit logging
│   ├── models.py                # Dataclasses for categories, items, diagnostics, reports
│   ├── scanner.py               # Fast os.scandir scanner, dev finder & Space Detective
│   └── system_tools.py          # Windows Recycle Bin, DISM, WSL VHDX, hibernation APIs
├── gui/
│   ├── app.py                   # Main CustomTkinter application window
│   ├── detective_view.py        # Space Detective dashboard & folder explorer
│   ├── modals.py                # File Inspector, Confirmation & Audit Report modals
│   └── theme.py                 # Dark mode theme palette
└── utils/
    ├── config.py                # Local JSON settings, whitelist, snapshots, history
    ├── elevation.py             # Windows UAC Administrator elevation helpers
    ├── formatting.py            # Byte/age formatting & Windows reparse-point checks
    └── logger.py                # Audit file logging
```

---

## Disclaimer
Review items inside **Review First** categories (such as browser offline `Service Worker` / `File System` storage, `.cache` AI models, or stale `node_modules`) using the built-in **Inspect Files** modal before deleting. All standard cleanups move items to the Windows Recycle Bin by default for recoverability.
