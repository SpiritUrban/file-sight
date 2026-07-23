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
        """Make the backend ready to caption.

        For PyTorch, ``initialize`` already loads BLIP weights. For ONNX,
        ``initialize`` only builds the tiny self-test session; the caption
        graphs are built on the first ``_captioner()`` call. Touching that
        path here keeps the scan's "Loading model" phase honest and avoids
        paying the 900 MB cold start on the first real file.
        """
        self._backend.initialize()
        ensure = getattr(self._backend, "_captioner", None)
        if callable(ensure):
            ensure()

    def caption(self, image: Image.Image) -> str:
        return self._backend.caption_image(image).caption

    def close(self) -> None:
        try:
            self._backend.close()
        except Exception:
            pass
