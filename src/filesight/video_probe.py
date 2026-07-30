"""ffprobe wrapper: read video metadata as JSON, never via a shell string."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from filesight.constants import FFPROBE_TIMEOUT_SECONDS
from filesight.models import VideoMetadata


class FFmpegNotFound(Exception):
    """ffmpeg or ffprobe could not be located."""


class ProbeError(Exception):
    """ffprobe could not read the file or returned unusable data."""

    def __init__(self, message: str, error_type: str = "ProbeError") -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass
class FFmpegTools:
    """Resolved, verified paths to the ffmpeg and ffprobe executables."""

    ffmpeg: str
    ffprobe: str


def resolve_tools(
    ffmpeg_path: Optional[str] = None, ffprobe_path: Optional[str] = None
) -> FFmpegTools:
    """Locate ffmpeg and ffprobe, honoring explicit paths then PATH.

    Raises FFmpegNotFound with a clear, actionable message if missing.
    """
    ffmpeg = _resolve_one("ffmpeg", ffmpeg_path)
    ffprobe = _resolve_one("ffprobe", ffprobe_path)
    return FFmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe)


def _candidate_roots() -> list[Path]:
    """Every place a usable FFmpeg may sit, best candidate first.

    The list itself lives in ``ffmpeg_setup`` next to the one-click
    downloader, so the directory the download writes to and the directory
    the resolver reads from can never drift apart.
    """
    from filesight.ffmpeg_setup import search_roots

    return search_roots()


def find_bundled_tool(
    name: str, roots: Optional[list[Path]] = None
) -> Optional[str]:
    """Find an FFmpeg dropped into the project folder.

    Accepts ``<root>/ffmpeg.exe`` as well as an unpacked distribution such
    as ``<root>/ffmpeg-8.1.2-essentials_build/bin/ffmpeg.exe``, so simply
    extracting a release next to the project is enough.
    """
    executable = f"{name}.exe" if os.name == "nt" else name
    for root in roots if roots is not None else _candidate_roots():
        direct = root / executable
        if direct.is_file():
            return str(direct)
        for folder in sorted(root.glob("ffmpeg*")):
            if not folder.is_dir():
                continue
            for candidate in (folder / "bin" / executable, folder / executable):
                if candidate.is_file():
                    return str(candidate)
    return None


def _resolve_one(name: str, explicit: Optional[str]) -> str:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(explicit)
        if found:
            return found
        raise FFmpegNotFound(
            f"{name} not found at the given path: {explicit}"
        )
    # A copy shipped with the project wins over PATH: it was put there
    # deliberately, and it keeps the app working without any setup.
    bundled = find_bundled_tool(name)
    if bundled:
        return bundled
    found = shutil.which(name)
    if found:
        return found
    # The example path is built for the running OS: telling a Linux user to
    # pass `C:\path\to\ffmpeg.exe` is advice they cannot act on.
    example = (
        f"C:\\path\\to\\{name}.exe" if os.name == "nt" else f"/usr/local/bin/{name}"
    )
    raise FFmpegNotFound(
        f"{name} was not found. In the desktop app use "
        f"Settings -> \"Download FFmpeg automatically\". From the command line: "
        f"install FFmpeg and add it to PATH, unpack an FFmpeg build into the "
        f"FileSight folder, or pass --{name}-path {example}. "
        "See the README section 'Video support' for install steps."
    )


def probe_video(path: str, ffprobe: str) -> VideoMetadata:
    """Run ffprobe on ``path`` and return normalized metadata.

    Raises ProbeError (with a specific error_type) on any failure so the
    caller can record it and move on to the next file.
    """
    data = _run_ffprobe(path, ffprobe)
    return parse_probe_output(data)


def _run_ffprobe(path: str, ffprobe: str) -> dict:
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(
            f"ffprobe timed out after {FFPROBE_TIMEOUT_SECONDS}s", "ProbeTimeout"
        ) from exc
    except OSError as exc:
        raise ProbeError(f"Could not run ffprobe: {exc}", "ProbeError") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        raise ProbeError(
            f"ffprobe failed (exit {completed.returncode}): {stderr}",
            "ProbeFailed",
        )
    try:
        return json.loads(completed.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON: {exc}", "ProbeError") from exc


def parse_probe_output(data: dict) -> VideoMetadata:
    """Turn raw ffprobe JSON into VideoMetadata. Pure; unit-testable."""
    streams = data.get("streams") or []
    video_stream = next(
        (s for s in streams if s.get("codec_type") == "video"), None
    )
    if video_stream is None:
        raise ProbeError("File has no video stream.", "NoVideoStream")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    fmt = data.get("format") or {}
    duration = _parse_duration(video_stream, fmt)
    if duration is None:
        raise ProbeError("Video duration is unknown.", "UnknownDuration")
    if duration <= 0:
        raise ProbeError("Video duration is zero.", "ZeroDuration")

    return VideoMetadata(
        duration_seconds=round(duration, 2),
        width=_as_int(video_stream.get("width")),
        height=_as_int(video_stream.get("height")),
        frame_rate=_parse_frame_rate(video_stream.get("avg_frame_rate"))
        or _parse_frame_rate(video_stream.get("r_frame_rate")),
        video_codec=video_stream.get("codec_name"),
        container=fmt.get("format_name"),
        has_audio=has_audio,
        rotation_degrees=_parse_rotation(video_stream),
        creation_time=_creation_time(video_stream, fmt),
    )


def _creation_time(video_stream: dict, fmt: dict) -> Optional[str]:
    """Container/stream creation_time tag, used later for {date}."""
    for tags in (fmt.get("tags") or {}, video_stream.get("tags") or {}):
        value = tags.get("creation_time")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _as_int(value: object) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _parse_duration(video_stream: dict, fmt: dict) -> Optional[float]:
    for source in (video_stream.get("duration"), fmt.get("duration")):
        try:
            return float(source)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return None


def _parse_frame_rate(value: object) -> Optional[float]:
    """Parse ffprobe frame-rate strings like '30/1' or '30000/1001'."""
    if not isinstance(value, str) or "/" not in value:
        try:
            return float(value) if value else None  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    num, _, den = value.partition("/")
    try:
        numerator = float(num)
        denominator = float(den)
    except ValueError:
        return None
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def _parse_rotation(video_stream: dict) -> int:
    """Read rotation from tags or side_data; normalize to 0/90/180/270."""
    raw: object = None
    tags = video_stream.get("tags") or {}
    if "rotate" in tags:
        raw = tags.get("rotate")
    for side in video_stream.get("side_data_list") or []:
        if "rotation" in side:
            raw = side.get("rotation")
            break
    try:
        degrees = int(round(float(raw)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return degrees % 360
