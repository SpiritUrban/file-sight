"""Per-file processing pipeline: open image -> caption -> suggested name.

The captioner is injected, so tests can run the whole pipeline with a
mock captioner and never load the real model.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional

from filesight.captioner import ImageCaptioner, load_image_for_captioning
from filesight.models import FileEntry, FileError
from filesight.naming import NameAllocator

ProgressCallback = Callable[[int, int, FileEntry], None]


def process_file(
    path: Path, captioner: ImageCaptioner, allocator: NameAllocator
) -> FileEntry:
    """Process one image. Never raises; failures are recorded in the entry."""
    start = time.perf_counter()
    caption: Optional[str] = None
    suggested: Optional[str] = None
    error: Optional[FileError] = None
    status = "success"
    try:
        image = load_image_for_captioning(str(path))
        caption = captioner.caption(image)
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
        caption=caption,
        suggested_name=suggested,
        processing_time_ms=elapsed_ms,
        error=error,
    )


def process_files(
    files: list[Path],
    captioner: ImageCaptioner,
    on_progress: Optional[ProgressCallback] = None,
) -> list[FileEntry]:
    """Process all files in order; suggested-name numbering is stable."""
    allocator = NameAllocator()
    entries: list[FileEntry] = []
    total = len(files)
    for index, path in enumerate(files, start=1):
        entry = process_file(path, captioner, allocator)
        entries.append(entry)
        if on_progress is not None:
            on_progress(index, total, entry)
    return entries
