"""Controlled temporary directories for extracted video frames.

One run gets one operation directory under the system temp folder; each
video gets its own subdirectory. Everything is removed on cleanup, on
error and on Ctrl+C. FileSight only ever deletes directories it created.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from types import TracebackType
from typing import Optional


class FrameWorkspace:
    """Owns one temp directory tree for a single scan run.

    Use as a context manager so the whole tree is deleted even if the
    caller raises (including KeyboardInterrupt).
    """

    def __init__(self, base: Optional[Path] = None) -> None:
        root = base if base is not None else Path(tempfile.gettempdir()) / "filesight"
        self._operation_dir = root / f"operation-{uuid.uuid4().hex}"
        self._created = False

    @property
    def operation_dir(self) -> Path:
        return self._operation_dir

    def _ensure_root(self) -> None:
        if not self._created:
            self._operation_dir.mkdir(parents=True, exist_ok=True)
            self._created = True

    def video_dir(self) -> Path:
        """Create and return a fresh per-video subdirectory."""
        self._ensure_root()
        directory = self._operation_dir / f"video-{uuid.uuid4().hex}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def cleanup_video(self, directory: Path) -> None:
        """Remove one per-video directory; never raises."""
        try:
            if directory.is_relative_to(self._operation_dir):
                shutil.rmtree(directory, ignore_errors=True)
        except (OSError, ValueError):
            pass

    def cleanup(self) -> None:
        """Remove the whole operation tree; never raises."""
        if self._created:
            shutil.rmtree(self._operation_dir, ignore_errors=True)
            self._created = False

    def __enter__(self) -> "FrameWorkspace":
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.cleanup()
