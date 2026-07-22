"""Adapt an InferenceBackend to the ImageCaptioner interface the pipeline uses."""

from __future__ import annotations

from PIL import Image

from filesight.inference.registry import BackendSelection


class BackendCaptioner:
    """Exposes ``.caption(image)`` / ``.model_name`` / ``.device`` over a backend.

    The pipeline and report code were written against the old
    ``ImageCaptioner`` shape; this keeps them unchanged while routing the
    actual work through the selected inference backend.
    """

    def __init__(self, selection: BackendSelection) -> None:
        self.selection = selection
        self._backend = selection.backend
        self.model_name = selection.model_id or "unknown"
        # The pipeline records this as ModelInfo.device; use the honest
        # execution provider so the report device matches the backend.
        self.device = selection.execution_provider or "cpu"

    def load(self) -> None:
        self._backend.initialize()

    def caption(self, image: Image.Image) -> str:
        return self._backend.caption_image(image).caption

    def close(self) -> None:
        try:
            self._backend.close()
        except Exception:
            pass
