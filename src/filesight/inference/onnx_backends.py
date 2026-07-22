"""ONNX Runtime backends: CPU and DirectML.

State of play (documented in docs/iteration-06.md): the caption model has
not yet been exported to ONNX, so these backends do not *generate captions*
— ``caption_images`` raises rather than quietly delegating to PyTorch, so a
scan's reported backend can never falsely read "DirectML" while the work
actually happens on CPU. What they *do* provide is a real, verified ONNX
Runtime path: a genuine session on the requested execution provider, a
compute self-test on the device, benchmarking and honest diagnostics —
which is what the RX 580 / DirectML verification rests on.
"""

from __future__ import annotations

import base64
import time
from typing import Optional

from PIL import Image

from filesight.inference.base import (
    BACKEND_ONNX_CPU,
    BACKEND_ONNX_DIRECTML,
    RUNTIME_ONNX,
    BackendDiagnostics,
    BackendError,
    CaptionResult,
    detect_gpu_name,
)

DML_PROVIDER = "DmlExecutionProvider"
CPU_PROVIDER = "CPUExecutionProvider"

# A tiny (32x32 MatMul+Add) model, embedded so the self-test needs no
# `onnx` builder at runtime and no shipped binary. See
# scratchpad/gen_selftest_model.py for how it was produced.
_SELFTEST_MODEL_B64 = (
    "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"
)

_SELFTEST_N = 32
_SELFTEST_EXPECTED_SUM = -30.888267517089844
_SELFTEST_TOLERANCE = 0.05

_NO_CAPTION_MESSAGE = (
    "The caption model has not been exported to ONNX yet, so this backend "
    "cannot generate captions. Captioning falls back to PyTorch CPU. This "
    "backend's DirectML/ONNX path is verified via 'Test backend' and "
    "'Benchmark'. See docs/iteration-06.md."
)


# One ONNX Runtime session per execution provider for the whole process.
#
# Creating a *second* DirectML session after the first is torn down
# deadlocks the D3D12 device under the worker's piped stdio, and recreating
# sessions is wasteful anyway. Every backend instance shares the cached
# session, so it is created once (at preload) and reused by scan, backend
# test and benchmark alike.
_SESSION_CACHE: dict[str, object] = {}
_SESSION_LOCK = None  # set lazily to a threading.Lock


def _session_lock():
    global _SESSION_LOCK
    if _SESSION_LOCK is None:
        import threading

        _SESSION_LOCK = threading.Lock()
    return _SESSION_LOCK


def reset_session_cache() -> None:
    """Drop cached sessions (tests only; not used in normal operation)."""
    _SESSION_CACHE.clear()


class OnnxBackend:
    """Shared logic; subclasses pin the execution provider."""

    provider: str = CPU_PROVIDER
    backend_id: str = BACKEND_ONNX_CPU

    def __init__(self) -> None:
        self._session = None
        self._ort_version: Optional[str] = None

    # -- availability ------------------------------------------------------

    @staticmethod
    def _import_ort():
        import onnxruntime as ort

        return ort

    def is_available(self) -> bool:
        try:
            ort = self._import_ort()
        except Exception:
            return False
        return self.provider in ort.get_available_providers()

    # -- session -----------------------------------------------------------

    def _model_bytes(self) -> bytes:
        return base64.b64decode(_SELFTEST_MODEL_B64)

    def _make_session(self):
        ort = self._import_ort()
        self._ort_version = ort.__version__
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # DirectML requires sequential execution; it is also the safe
        # default for a single-stream captioning workload.
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_mem_pattern = self.provider != DML_PROVIDER
        return ort.InferenceSession(
            self._model_bytes(), options, providers=[self.provider]
        )

    def initialize(self) -> None:
        if self._session is not None:
            return
        with _session_lock():
            cached = _SESSION_CACHE.get(self.provider)
            if cached is None:
                cached = self._make_session()
                _SESSION_CACHE[self.provider] = cached
            self._session = cached

    # -- captioning (not yet on ONNX) -------------------------------------

    def caption_image(self, image: Image.Image) -> CaptionResult:
        raise BackendError("ONNX_CAPTION_UNAVAILABLE", _NO_CAPTION_MESSAGE)

    def caption_images(self, images: list[Image.Image]) -> list[CaptionResult]:
        raise BackendError("ONNX_CAPTION_UNAVAILABLE", _NO_CAPTION_MESSAGE)

    # -- self-test / diagnostics ------------------------------------------

    def self_test(self) -> BackendDiagnostics:
        import numpy as np

        diag = self.get_diagnostics()
        if not diag.available:
            diag.self_test_passed = False
            diag.error = f"{self.provider} is not available in ONNX Runtime."
            return diag
        try:
            self.initialize()
            actual = self._session.get_providers()
            diag.initialized = True
            diag.model_loaded = True
            if self.provider not in actual:
                diag.self_test_passed = False
                diag.error = (
                    f"session fell back to {actual}; {self.provider} not used"
                )
                return diag

            x = np.ones((1, _SELFTEST_N), dtype=np.float32)
            self._session.run(None, {"X": x})  # warm-up
            start = time.perf_counter()
            output = self._session.run(None, {"X": x})[0]
            diag.inference_ms = int((time.perf_counter() - start) * 1000)
            got = float(np.asarray(output).sum())
            ok = abs(got - _SELFTEST_EXPECTED_SUM) <= _SELFTEST_TOLERANCE
            diag.self_test_passed = ok
            if not ok:
                diag.error = (
                    f"self-test output {got:.4f} != expected "
                    f"{_SELFTEST_EXPECTED_SUM:.4f}"
                )
        except Exception as exc:
            diag.self_test_passed = False
            diag.error = f"{type(exc).__name__}: {exc}"
        return diag

    def get_diagnostics(self) -> BackendDiagnostics:
        available = self.is_available()
        actual_provider = None
        if self._session is not None:
            providers = self._session.get_providers()
            actual_provider = providers[0] if providers else None
        return BackendDiagnostics(
            backend_id=self.backend_id,
            available=available,
            runtime=RUNTIME_ONNX,
            initialized=self._session is not None,
            model_loaded=self._session is not None,
            execution_provider=actual_provider or self.provider,
            device_name=self._device_name(),
            runtime_version=self._ort_version or _ort_version_safe(),
            model_id="filesight-selftest",
            notes=[_NO_CAPTION_MESSAGE],
        )

    def _device_name(self) -> Optional[str]:
        return "CPU"

    def close(self) -> None:
        # Detach this instance but keep the process-wide session warm; see
        # _SESSION_CACHE. Recreating a DirectML session is what deadlocks.
        self._session = None


class OnnxCpuBackend(OnnxBackend):
    provider = CPU_PROVIDER
    backend_id = BACKEND_ONNX_CPU


class OnnxDirectMlBackend(OnnxBackend):
    provider = DML_PROVIDER
    backend_id = BACKEND_ONNX_DIRECTML

    def _device_name(self) -> Optional[str]:
        # Only claim a device when DirectML is genuinely usable.
        if not self.is_available():
            return None
        return detect_gpu_name()


def _ort_version_safe() -> Optional[str]:
    try:
        import onnxruntime as ort

        return ort.__version__
    except Exception:
        return None
