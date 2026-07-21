"""Timestamp selection and FFmpeg frame extraction.

Timestamp math is pure and unit-testable; extraction shells out to
FFmpeg (argument list, never a shell string) with a per-frame timeout
and guaranteed child-process termination.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from filesight.constants import (
    FRAME_EXTRACTION_TIMEOUT_SECONDS,
    LONG_VIDEO_END_FRACTION,
    LONG_VIDEO_START_FRACTION,
    SHORT_VIDEO_THRESHOLD_SECONDS,
)

# For short clips we bias sampling toward the middle and stay away from
# the very start (intro/black) and very end (fade-out/black).
_SHORT_START_FRACTION = 0.15
_SHORT_END_FRACTION = 0.90


@dataclass
class ExtractedFrame:
    index: int
    timestamp_seconds: float
    path: Optional[str]  # None if extraction failed
    error: Optional[str] = None


def compute_timestamps(duration_seconds: float, num_frames: int) -> list[float]:
    """Evenly spread ``num_frames`` sample times across the video.

    Never returns exactly 0.0 or the exact end. Deterministic: the same
    inputs always yield the same timestamps.
    """
    if num_frames < 1:
        return []
    if duration_seconds <= SHORT_VIDEO_THRESHOLD_SECONDS:
        lo, hi = _SHORT_START_FRACTION, _SHORT_END_FRACTION
    else:
        lo, hi = LONG_VIDEO_START_FRACTION, LONG_VIDEO_END_FRACTION

    if num_frames == 1:
        fractions = [(lo + hi) / 2]
    else:
        step = (hi - lo) / (num_frames - 1)
        fractions = [lo + step * i for i in range(num_frames)]

    return [round(f * duration_seconds, 3) for f in fractions]


def extract_frames(
    ffmpeg: str,
    video_path: str,
    timestamps: list[float],
    out_dir: Path,
) -> list[ExtractedFrame]:
    """Extract one JPEG per timestamp. Per-frame failures are recorded."""
    results: list[ExtractedFrame] = []
    for index, timestamp in enumerate(timestamps, start=1):
        out_path = out_dir / f"frame-{index:03d}.jpg"
        error = _extract_one(ffmpeg, video_path, timestamp, out_path)
        if error is None and out_path.is_file() and out_path.stat().st_size > 0:
            results.append(
                ExtractedFrame(index, timestamp, str(out_path), None)
            )
        else:
            results.append(
                ExtractedFrame(
                    index, timestamp, None, error or "FFmpeg produced no frame"
                )
            )
    return results


def _extract_one(
    ffmpeg: str, video_path: str, timestamp: float, out_path: Path
) -> Optional[str]:
    """Run FFmpeg for a single frame; return an error string or None.

    ``-ss`` before ``-i`` performs a fast seek so the whole video is not
    decoded. ``-nostdin`` keeps FFmpeg from swallowing our stdin, which
    matters for clean Ctrl+C handling.
    """
    command = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-y",
        str(out_path),
    ]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL
    )
    try:
        _, stderr = process.communicate(timeout=FRAME_EXTRACTION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _kill(process)
        return f"frame extraction timed out after {FRAME_EXTRACTION_TIMEOUT_SECONDS}s"
    except BaseException:
        # KeyboardInterrupt or anything else: never leave FFmpeg running.
        _kill(process)
        raise
    if process.returncode != 0:
        message = stderr.decode("utf-8", "replace").strip() or "unknown FFmpeg error"
        return f"FFmpeg exit {process.returncode}: {message}"
    return None


def _kill(process: "subprocess.Popen") -> None:
    try:
        process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass
