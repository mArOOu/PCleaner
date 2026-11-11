"""Data models for PCleaner categories, scanned items, diagnostics, and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TierType = Literal["safe", "browser_app", "dev", "system"]
SafetyLevel = Literal["100% Safe", "Safe", "Dev Safe", "Review First", "Admin Required"]


@dataclass
class CleanItem:
    """Represents a concrete file or subfolder discovered inside a cleanup category."""

    path: str
    name: str
    size_bytes: int
    is_dir: bool
    file_count: int
    mtime: float
    description: str = ""
    selected: bool = True


@dataclass
class CleanCategory:
    """Definition + scan state of a cleanable category."""

    id: str
    name: str
    tier: TierType
    safety: SafetyLevel
    what_it_has: str
    delete_impact: str
    requires_admin: bool = False
    default_checked: bool = True
    supports_trash: bool = True
    paths: list[str] = field(default_factory=list)
    glob_patterns: list[str] = field(default_factory=list)  # e.g. thumbcache_*.db inside path
    clean_contents_only: bool = True  # True: clean children of path, False: delete path itself

    # Populated during scan:
    items: list[CleanItem] = field(default_factory=list)
    total_bytes: int = 0
    total_files: int = 0
    scanned: bool = False
    error: str = ""

    @property
    def selected_items(self) -> list[CleanItem]:
        return [item for item in self.items if item.selected]

    @property
    def selected_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items if item.selected)


@dataclass
class CulpritSpotlight:
    """A plain-English diagnostic card explaining a major disk consumer on C:."""

    title: str
    path: str
    size_bytes: int
    category_label: str
    explanation: str
    recommendation: str
    severity: Literal["high", "medium", "info"] = "medium"


@dataclass
class LargeFileEntry:
    """A large individual file found during Space Detective scan."""

    path: str
    name: str
    size_bytes: int
    mtime: float
    ext: str
    explanation: str


@dataclass
class FolderNode:
    """Represents a folder's disk usage for interactive drill-down."""

    path: str
    name: str
    size_bytes: int
    file_count: int
    mtime: float
    explanation: str = ""
    children: list["FolderNode"] = field(default_factory=list)


@dataclass
class GrowthEntry:
    """Represents growth of a folder compared against a prior snapshot."""

    path: str
    name: str
    previous_bytes: int
    current_bytes: int
    delta_bytes: int


@dataclass
class SpaceReport:
    """Full Space Detective diagnostic report."""

    scanned_at: float
    drive_total: int
    drive_used: int
    drive_free: int
    spotlights: list[CulpritSpotlight] = field(default_factory=list)
    top_folders: list[FolderNode] = field(default_factory=list)
    large_files: list[LargeFileEntry] = field(default_factory=list)
    growth_entries: list[GrowthEntry] = field(default_factory=list)
    previous_snapshot_time: float | None = None


@dataclass
class CleanResult:
    """Result summary after executing (or previewing) a cleanup."""

    dry_run: bool
    mode: Literal["trash", "permanent"]
    freed_bytes: int
    items_deleted: int
    items_skipped: int
    deleted_paths: list[tuple[str, int]] = field(default_factory=list)
    skipped_paths: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)
    errors: list[str] = field(default_factory=list)
