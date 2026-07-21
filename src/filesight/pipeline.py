"""Per-file processing pipeline: open media -> caption -> suggested name.

The captioner is injected, so tests can run the whole pipeline with a
mock captioner and never load the real model. Images are handled here;
videos are delegated to video_pipeline. A shared NameAllocator gives one
report stable, unique suggested names across both media types.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from filesight.captioner import ImageCaptioner, load_image_for_captioning
from filesight.models import MEDIA_IMAGE, FileEntry, FileError, SourceMetadata
from filesight.naming import NameAllocator
from filesight.scanner import is_video

ProgressCallback = Callable[[int, int, FileEntry], None]
FrameProgress = Callable[[str, int, int], None]
FileStartCallback = Callable[[int, int, Path], None]
CancelCheck = Callable[[], bool]


class ScanCancelled(Exception):
    """Raised when a caller-supplied cancel check asks the scan to stop."""


@dataclass
class VideoContext:
    """Everything the video branch needs; None means videos are disabled."""

    ffmpeg: str
    ffprobe: str
    workspace: object  # FrameWorkspace (kept loose to avoid import cost)
    max_duration: int
    allow_long: bool
    num_frames: int


def process_image(
    path: Path,
    captioner: ImageCaptioner,
    allocator: NameAllocator,
    naming_session: Optional[object] = None,
) -> FileEntry:
    """Process one image. Never raises; failures are recorded in the entry."""
    start = time.perf_counter()
    caption: Optional[str] = None
    suggested: Optional[str] = None
    error: Optional[FileError] = None
    metadata: Optional[SourceMetadata] = None
    features = classification = naming = None
    captured_at = date_source = None
    status = "success"
    try:
        image = load_image_for_captioning(str(path))
        caption = captioner.caption(image)
        stat_result = path.stat()
        metadata = SourceMetadata(
            size_bytes=stat_result.st_size,
            modified_at_ns=stat_result.st_mtime_ns,
        )
        if naming_session is not None:
            from filesight.media_dates import resolve_media_date

            date_result = resolve_media_date(path, media_type=MEDIA_IMAGE)
            captured_at = date_result.captured_at
            date_source = date_result.date_source
            outcome = naming_session.name_for(
                str(path), path.name, caption,
                media_type=MEDIA_IMAGE, captured_at=captured_at,
            )
            features = outcome.features
            classification = outcome.classification
            naming = outcome.naming
            suggested = naming.suggested_name
        else:
            suggested = allocator.allocate(caption, path.suffix)
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # one broken file must not stop the scan
        status = "failed"
        caption = None
        suggested = None
        error = FileError(type=type(exc).__name__, message=str(exc) or repr(exc))
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return FileEntry(
        original_path=str(path),
        original_name=path.name,
        extension=path.suffix,
        status=status,
        media_type=MEDIA_IMAGE,
        caption=caption,
        suggested_name=suggested,
        processing_time_ms=elapsed_ms,
        error=error,
        source_metadata=metadata,
        features=features,
        classification=classification,
        naming=naming,
        captured_at=captured_at,
        date_source=date_source,
    )


# Backward-compatible name used by iteration-1/2 tests.
process_file = process_image


def process_files(
    files: list[Path],
    captioner: ImageCaptioner,
    on_progress: Optional[ProgressCallback] = None,
) -> list[FileEntry]:
    """Process image files in order; suggested-name numbering is stable."""
    return process_media_files(files, captioner, on_file_progress=on_progress)


def process_media_files(
    files: list[Path],
    captioner: ImageCaptioner,
    video_context: Optional[VideoContext] = None,
    on_file_progress: Optional[ProgressCallback] = None,
    on_frame_progress: Optional[FrameProgress] = None,
    on_file_start: Optional[FileStartCallback] = None,
    naming_session: Optional[object] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> list[FileEntry]:
    """Process a mixed list of images and videos in stable report order.

    ``should_cancel`` is polled before each file; when it returns True the
    scan stops with ScanCancelled, carrying the entries finished so far.
    """
    allocator = NameAllocator()
    entries: list[FileEntry] = []
    total = len(files)
    for index, path in enumerate(files, start=1):
        if should_cancel is not None and should_cancel():
            raise ScanCancelled(entries)
        if on_file_start is not None:
            on_file_start(index, total, path)
        if is_video(path):
            entry = _process_video_file(
                path, captioner, allocator, video_context, on_frame_progress,
                naming_session,
            )
        else:
            entry = process_image(path, captioner, allocator, naming_session)
        entries.append(entry)
        if on_file_progress is not None:
            on_file_progress(index, total, entry)
    return entries


def _process_video_file(
    path: Path,
    captioner: ImageCaptioner,
    allocator: NameAllocator,
    video_context: Optional[VideoContext],
    on_frame_progress: Optional[FrameProgress],
    naming_session: Optional[object] = None,
) -> FileEntry:
    if video_context is None:
        # Should not happen (scanner would not return videos), but stay safe.
        return FileEntry(
            original_path=str(path),
            original_name=path.name,
            extension=path.suffix,
            status="failed",
            media_type="video",
            caption=None,
            suggested_name=None,
            processing_time_ms=0,
            error=FileError(type="VideoSupportDisabled", message="Video support is off."),
        )
    from filesight.video_pipeline import process_video

    return process_video(
        path,
        captioner,
        allocator,
        ffmpeg=video_context.ffmpeg,
        ffprobe=video_context.ffprobe,
        workspace=video_context.workspace,
        max_duration=video_context.max_duration,
        allow_long=video_context.allow_long,
        num_frames=video_context.num_frames,
        on_progress=on_frame_progress,
        naming_session=naming_session,
    )
