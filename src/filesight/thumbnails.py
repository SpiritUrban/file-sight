"""Thumbnail generation for the desktop UI.

Thumbnails are written to a cache directory (never next to the user's
originals) and keyed by path + size + mtime, so an edited file produces a
fresh thumbnail while unchanged files are reused.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from filesight.constants import FRAME_EXTRACTION_TIMEOUT_SECONDS
from filesight.scanner import is_video

DEFAULT_SIZE = 256
CACHE_DIR_NAME = "filesight-thumbnails"


def default_cache_dir() -> Path:
    return Path(tempfile.gettempdir()) / CACHE_DIR_NAME


def cache_key(path: Path, size: int) -> str:
    """Stable key from absolute path, size and modification time."""
    try:
        stat = path.stat()
        stamp = f"{stat.st_size}-{stat.st_mtime_ns}"
    except OSError:
        stamp = "0-0"
    raw = f"{path.resolve()}|{size}|{stamp}"
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:32]


def make_thumbnail(
    path: Path,
    cache_dir: Optional[Path] = None,
    size: int = DEFAULT_SIZE,
    ffmpeg: Optional[str] = None,
) -> Optional[Path]:
    """Return a cached thumbnail path, creating it if needed.

    Returns None when no thumbnail could be produced (the caller shows a
    placeholder). Never raises for an unreadable media file.
    """
    if not path.exists():
        raise FileNotFoundError(f"File does not exist: {path}")

    directory = cache_dir or default_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{cache_key(path, size)}.jpg"
    if target.is_file() and target.stat().st_size > 0:
        return target

    if is_video(path):
        return _video_thumbnail(path, target, size, ffmpeg)
    return _image_thumbnail(path, target, size)


def _image_thumbnail(source: Path, target: Path, size: int) -> Optional[Path]:
    from PIL import Image, ImageOps

    try:
        with Image.open(source) as img:
            img = ImageOps.exif_transpose(img)  # honour camera orientation
            img = img.convert("RGB")
            img.thumbnail((size, size), Image.LANCZOS)
            img.save(target, "JPEG", quality=85)
    except Exception:
        return None
    return target


def _video_thumbnail(
    source: Path, target: Path, size: int, ffmpeg: Optional[str]
) -> Optional[Path]:
    from filesight.video_probe import FFmpegNotFound, resolve_tools

    try:
        tools = resolve_tools(ffmpeg_path=ffmpeg)
    except FFmpegNotFound:
        return None

    # One frame from ~15% in, avoiding black intro frames.
    command = [
        tools.ffmpeg, "-nostdin", "-v", "error", "-ss", "1",
        "-i", str(source), "-frames:v", "1",
        "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
        "-y", str(target),
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    try:
        process.communicate(timeout=FRAME_EXTRACTION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        return None
    except BaseException:
        process.kill()
        raise
    if process.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        # Retry from the very first frame for very short clips.
        retry = [
            tools.ffmpeg, "-nostdin", "-v", "error", "-i", str(source),
            "-frames:v", "1",
            "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
            "-y", str(target),
        ]
        try:
            subprocess.run(retry, capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
    if target.is_file() and target.stat().st_size > 0:
        return target
    return None


def clear_cache(cache_dir: Optional[Path] = None) -> int:
    """Delete cached thumbnails. Only touches files FileSight created."""
    directory = cache_dir or default_cache_dir()
    if not directory.is_dir():
        return 0
    removed = 0
    for item in directory.glob("*.jpg"):
        try:
            item.unlink()
            removed += 1
        except OSError:
            pass
    return removed
