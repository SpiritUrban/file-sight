"""The inference backend contract shared by every implementation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from PIL import Image

# Stable internal backend identifiers. Never use vague labels like "gpu",
# "fast" or "best" — the UI must be able to state exactly what ran.
BACKEND_AUTO = "auto"
BACKEND_ONNX_DIRECTML = "onnx-directml"
BACKEND_ONNX_CPU = "onnx-cpu"
BACKEND_PYTORCH_CPU = "pytorch-cpu"

# Concrete backends (excludes "auto", which selects one of these).
KNOWN_BACKENDS = (
    BACKEND_ONNX_DIRECTML,
    BACKEND_ONNX_CPU,
    BACKEND_PYTORCH_CPU,
)

# Runtime family names reported to the UI.
RUNTIME_PYTORCH = "pytorch"
RUNTIME_ONNX = "onnxruntime"


@dataclass
class CaptionResult:
    """One caption plus the backend that produced it."""

    caption: str
    backend_id: str


@dataclass
class BackendDiagnostics:
    """Everything the UI needs to describe a backend honestly.

    ``self_test_passed`` is None until a self-test has actually run, so the
    UI can distinguish "not tested" from "tested and failed".
    """

    backend_id: str
    available: bool
    runtime: str  # "pytorch" | "onnxruntime"
    initialized: bool = False
    model_loaded: bool = False
    execution_provider: Optional[str] = None
    device_name: Optional[str] = None
    runtime_version: Optional[str] = None
    model_id: Optional[str] = None
    self_test_passed: Optional[bool] = None
    inference_ms: Optional[int] = None
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class InferenceBackend(Protocol):
    """Anything that can caption images, whatever library backs it."""

    backend_id: str

    def is_available(self) -> bool:
        """Cheap check: could this backend run here at all? No model load."""
        ...

    def initialize(self) -> None:
        """Create sessions and load the model. May be slow; may raise."""
        ...

    def caption_image(self, image: Image.Image) -> CaptionResult:
        ...

    def caption_images(self, images: list[Image.Image]) -> list[CaptionResult]:
        ...

    def self_test(self) -> BackendDiagnostics:
        """Prove the backend really runs, end to end. Never raises."""
        ...

    def get_diagnostics(self) -> BackendDiagnostics:
        ...

    def close(self) -> None:
        ...


class BackendError(Exception):
    """A backend could not do what was asked. Carries a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def detect_gpu_name() -> Optional[str]:
    """Best-effort adapter name via Win32, so we never invent a device.

    Returns the primary display adapter's name (e.g. "Radeon RX 580
    Series") or None when it cannot be read.
    """
    import ctypes

    try:
        user32 = ctypes.windll.user32
    except (AttributeError, OSError):
        return None

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("DeviceName", ctypes.c_wchar * 32),
            ("DeviceString", ctypes.c_wchar * 128),
            ("StateFlags", ctypes.c_ulong),
            ("DeviceID", ctypes.c_wchar * 128),
            ("DeviceKey", ctypes.c_wchar * 128),
        ]

    best: Optional[str] = None
    index = 0
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            break
        index += 1
        name = device.DeviceString.strip()
        if not name:
            continue
        # Prefer the adapter attached to the desktop (StateFlags bit 0).
        if device.StateFlags & 0x1:
            return name
        best = best or name
    return best
