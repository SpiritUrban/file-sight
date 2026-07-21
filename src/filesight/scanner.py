"""Discovery of supported image and video files."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

# Backward-compatible alias (iteration 1/2 imported this name).
SUPPORTED_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS


def _iter_files(directory: Path, recursive: bool):
    return directory.rglob("*") if recursive else directory.glob("*")


def _find(directory: Path, extensions: set[str], recursive: bool) -> list[Path]:
    files = [
        path
        for path in _iter_files(directory, recursive)
        if path.is_file() and path.suffix.lower() in extensions
    ]
    return sorted(files, key=lambda p: str(p).lower())


def find_images(directory: Path, recursive: bool = False) -> list[Path]:
    """Return supported image files, sorted, case-insensitive on extension."""
    return _find(directory, SUPPORTED_IMAGE_EXTENSIONS, recursive)


def find_videos(directory: Path, recursive: bool = False) -> list[Path]:
    """Return supported video files, sorted, case-insensitive on extension."""
    return _find(directory, SUPPORTED_VIDEO_EXTENSIONS, recursive)


def find_media(
    directory: Path,
    recursive: bool = False,
    include_images: bool = True,
    include_videos: bool = False,
) -> list[Path]:
    """Return the selected media, sorted together in one stable order."""
    extensions: set[str] = set()
    if include_images:
        extensions |= SUPPORTED_IMAGE_EXTENSIONS
    if include_videos:
        extensions |= SUPPORTED_VIDEO_EXTENSIONS
    return _find(directory, extensions, recursive)


def is_video(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
