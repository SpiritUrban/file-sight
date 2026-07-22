"""PyTorch CPU backend — the historical, quality-reference captioner.

Wraps the BLIP model that FileSight has used since iteration 1. It stays
the production captioning backend until an ONNX caption model is exported
and quality-verified; the ONNX backends currently provide the DirectML
runtime path (self-test, benchmark, diagnostics), not caption generation.
"""

from __future__ import annotations

import time
from typing import Optional

from PIL import Image

from filesight.inference.base import (
    BACKEND_PYTORCH_CPU,
    RUNTIME_PYTORCH,
    BackendDiagnostics,
    CaptionResult,
)


class PyTorchCpuBackend:
    """BLIP on CPU via transformers. Loads the model once, lazily."""

    backend_id = BACKEND_PYTORCH_CPU

    def __init__(self, model_name: Optional[str] = None) -> None:
        from filesight.captioner import DEFAULT_MODEL

        self.model_name = model_name or DEFAULT_MODEL
        self._model = None
        self._processor = None
        self._torch_version: Optional[str] = None

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
        except Exception:
            return False
        return True

    def initialize(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import BlipForConditionalGeneration, BlipProcessor

        self._torch_version = torch.__version__
        self._processor = BlipProcessor.from_pretrained(
            self.model_name, local_files_only=_offline()
        )
        self._model = BlipForConditionalGeneration.from_pretrained(
            self.model_name, local_files_only=_offline()
        )
        self._model.to("cpu")
        self._model.eval()

    def caption_image(self, image: Image.Image) -> CaptionResult:
        return self.caption_images([image])[0]

    def caption_images(self, images: list[Image.Image]) -> list[CaptionResult]:
        if self._model is None:
            self.initialize()
        import torch

        results: list[CaptionResult] = []
        # BLIP's processor batches, but memory is bounded on CPU; caption
        # one at a time to match the historical behaviour exactly.
        for image in images:
            inputs = self._processor(images=image, return_tensors="pt")
            with torch.no_grad():
                output_ids = self._model.generate(
                    **inputs, max_new_tokens=32, num_beams=3
                )
            text = self._processor.decode(output_ids[0], skip_special_tokens=True)
            results.append(CaptionResult(caption=text.strip(), backend_id=self.backend_id))
        return results

    def self_test(self) -> BackendDiagnostics:
        diag = self.get_diagnostics()
        try:
            self.initialize()
            start = time.perf_counter()
            probe = Image.new("RGB", (64, 64), (120, 60, 30))
            result = self.caption_images([probe])[0]
            diag.inference_ms = int((time.perf_counter() - start) * 1000)
            diag.initialized = True
            diag.model_loaded = True
            diag.self_test_passed = bool(result.caption)
            if not result.caption:
                diag.error = "model returned an empty caption"
        except Exception as exc:
            diag.self_test_passed = False
            diag.error = f"{type(exc).__name__}: {exc}"
        return diag

    def get_diagnostics(self) -> BackendDiagnostics:
        return BackendDiagnostics(
            backend_id=self.backend_id,
            available=self.is_available(),
            runtime=RUNTIME_PYTORCH,
            initialized=self._model is not None,
            model_loaded=self._model is not None,
            execution_provider="CPU",
            device_name="CPU",
            runtime_version=self._torch_version,
            model_id=self.model_name,
        )

    def close(self) -> None:
        self._model = None
        self._processor = None


def _offline() -> bool:
    """Whether to forbid network access when loading the model.

    Off by default so a dev run can still download the model on first use;
    a bundled/offline build sets FILESIGHT_OFFLINE=1 to force local-only.
    """
    import os

    return os.environ.get("FILESIGHT_OFFLINE", "").lower() in ("1", "true", "yes")
