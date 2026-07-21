"""Process one video file end to end into a report FileEntry.

probe -> pick timestamps -> extract frames -> filter -> caption ->
aggregate -> suggested name. Never raises for per-file problems: any
failure is recorded on the entry so the scan continues.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from filesight.captioner import ImageCaptioner
from filesight.constants import DEFAULT_MAX_VIDEO_DURATION, DEFAULT_VIDEO_FRAMES
from filesight.models import (
    MEDIA_VIDEO,
    FileEntry,
    FileError,
    SourceMetadata,
    Timings,
    VideoAnalysis,
)
from filesight.naming import NameAllocator
from filesight.temp_files import FrameWorkspace
from filesight.video_caption import analyze_frames
from filesight.video_frames import compute_timestamps, extract_frames
from filesight.video_probe import ProbeError, probe_video

VideoProgress = Callable[[str, int, int], None]

SKIP_TOO_LONG = "video_too_long"


def _source_metadata(path: Path) -> Optional[SourceMetadata]:
    try:
        stat = path.stat()
        return SourceMetadata(size_bytes=stat.st_size, modified_at_ns=stat.st_mtime_ns)
    except OSError:
        return None


def process_video(
    path: Path,
    captioner: ImageCaptioner,
    allocator: NameAllocator,
    ffmpeg: str,
    ffprobe: str,
    workspace: FrameWorkspace,
    max_duration: int = DEFAULT_MAX_VIDEO_DURATION,
    allow_long: bool = False,
    num_frames: int = DEFAULT_VIDEO_FRAMES,
    on_progress: Optional[VideoProgress] = None,
    naming_session: Optional[object] = None,
) -> FileEntry:
    """Analyze one video. Failures are captured on the returned entry."""
    start = time.perf_counter()
    metadata_fp = _source_metadata(path)

    def base_entry(status: str, **kwargs) -> FileEntry:
        return FileEntry(
            original_path=str(path),
            original_name=path.name,
            extension=path.suffix,
            status=status,
            media_type=MEDIA_VIDEO,
            caption=kwargs.get("caption"),
            suggested_name=kwargs.get("suggested_name"),
            processing_time_ms=int((time.perf_counter() - start) * 1000),
            source_metadata=metadata_fp,
            error=kwargs.get("error"),
            video_metadata=kwargs.get("video_metadata"),
            video_analysis=kwargs.get("video_analysis"),
            timings=kwargs.get("timings"),
            features=kwargs.get("features"),
            classification=kwargs.get("classification"),
            naming=kwargs.get("naming"),
            captured_at=kwargs.get("captured_at"),
            date_source=kwargs.get("date_source"),
        )

    # 1. Probe metadata
    probe_start = time.perf_counter()
    try:
        video_meta = probe_video(str(path), ffprobe)
    except ProbeError as exc:
        return base_entry(
            "failed", error=FileError(type=exc.error_type, message=str(exc))
        )
    probe_ms = int((time.perf_counter() - probe_start) * 1000)

    # 2. Duration gate
    if video_meta.duration_seconds > max_duration and not allow_long:
        return base_entry(
            "skipped",
            video_metadata=video_meta,
            error=FileError(
                type=SKIP_TOO_LONG,
                message=(
                    f"duration {video_meta.duration_seconds:.1f} s exceeds "
                    f"limit {max_duration} s"
                ),
            ),
        )

    # 3. Timestamps + extraction (temp, always cleaned up)
    timestamps = compute_timestamps(video_meta.duration_seconds, num_frames)
    video_dir = workspace.video_dir()
    extract_ms = 0
    try:
        if on_progress is not None:
            on_progress("Extracting frames", 0, len(timestamps))
        extract_start = time.perf_counter()
        extracted = extract_frames(ffmpeg, str(path), timestamps, video_dir)
        extract_ms = int((time.perf_counter() - extract_start) * 1000)
        extracted_count = sum(1 for f in extracted if f.path is not None)

        # 4-6. Filter + caption + aggregate
        analysis = analyze_frames(extracted, captioner, on_progress)
    finally:
        workspace.cleanup_video(video_dir)

    timings = Timings(
        probe_ms=probe_ms,
        frame_extraction_ms=extract_ms,
        captioning_ms=analysis.captioning_ms,
        aggregation_ms=analysis.aggregation_ms,
        total_ms=int((time.perf_counter() - start) * 1000),
    )
    video_analysis = VideoAnalysis(
        requested_frames=num_frames,
        extracted_frames=extracted_count,
        usable_frames=analysis.usable_frames,
        analyzed_frames=analysis.analyzed_frames,
        frames=analysis.frame_results,
        warnings=list(analysis.warnings),
    )

    # 7. No usable frame -> failed
    if analysis.aggregated_caption is None:
        return base_entry(
            "failed",
            video_metadata=video_meta,
            video_analysis=video_analysis,
            timings=timings,
            error=FileError(
                type="NoUsableVideoFrames",
                message="No usable frame could be analyzed for this video.",
            ),
        )

    # 8. Suggested name via the shared naming layer
    caption = analysis.aggregated_caption
    if naming_session is not None:
        from filesight.media_dates import resolve_media_date

        date_result = resolve_media_date(
            path,
            media_type=MEDIA_VIDEO,
            video_tags={"creation_time": video_meta.creation_time},
        )
        outcome = naming_session.name_for(
            str(path), path.name, caption,
            media_type=MEDIA_VIDEO, captured_at=date_result.captured_at,
            extra={
                "width": video_meta.width or "",
                "height": video_meta.height or "",
                "duration": int(video_meta.duration_seconds),
            },
        )
        return base_entry(
            "success",
            caption=caption,
            suggested_name=outcome.naming.suggested_name,
            video_metadata=video_meta,
            video_analysis=video_analysis,
            timings=timings,
            features=outcome.features,
            classification=outcome.classification,
            naming=outcome.naming,
            captured_at=date_result.captured_at,
            date_source=date_result.date_source,
        )

    suggested = allocator.allocate(caption, path.suffix)
    return base_entry(
        "success",
        caption=caption,
        suggested_name=suggested,
        video_metadata=video_meta,
        video_analysis=video_analysis,
        timings=timings,
    )
