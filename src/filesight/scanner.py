"""Discovery of supported image files."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def find_images(directory: Path, recursive: bool = False) -> list[Path]:
    """Return supported image files in ``directory``, sorted for stable output.

    Extensions are matched case-insensitively. Only regular files are returned.
    """
    iterator = directory.rglob("*") if recursive else directory.glob("*")
    images = [
        path
        for path in iterator
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return sorted(images, key=lambda p: str(p).lower())
