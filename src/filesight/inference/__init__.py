"""Inference backends for image captioning.

The rest of FileSight talks to captioning through the ``InferenceBackend``
protocol, never to a specific library. This lets the same pipeline run on
PyTorch CPU (the historical default), ONNX Runtime CPU, or ONNX Runtime
with the DirectML execution provider on an AMD GPU — chosen at runtime and
reported honestly.
"""

from filesight.inference.base import (
    BACKEND_AUTO,
    BACKEND_ONNX_CPU,
    BACKEND_ONNX_DIRECTML,
    BACKEND_PYTORCH_CPU,
    KNOWN_BACKENDS,
    BackendDiagnostics,
    CaptionResult,
    InferenceBackend,
)
from filesight.inference.registry import (
    BackendSelection,
    available_backends,
    benchmark_backend,
    resolve_backend,
    test_backend,
)

__all__ = [
    "BACKEND_AUTO",
    "BACKEND_ONNX_CPU",
    "BACKEND_ONNX_DIRECTML",
    "BACKEND_PYTORCH_CPU",
    "KNOWN_BACKENDS",
    "BackendDiagnostics",
    "BackendSelection",
    "CaptionResult",
    "InferenceBackend",
    "available_backends",
    "benchmark_backend",
    "resolve_backend",
    "test_backend",
]
