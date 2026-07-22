"""The inference backend contract shared by every implementation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from PIL import Image

# Stable internal backend identifiers. Never use vague labels like "gpu",
# "fast" or "best" — the UI must be able to state exactly what ran.
BACKEND_AUTO = "auto"
BACKEND_ONNX_CUDA = "onnx-cuda"
BACKEND_ONNX_DIRECTML = "onnx-directml"
BACKEND_ONNX_CPU = "onnx-cpu"
BACKEND_PYTORCH_CPU = "pytorch-cpu"

# Concrete backends (excludes "auto", which selects one of these).
KNOWN_BACKENDS = (
    BACKEND_ONNX_CUDA,
    BACKEND_ONNX_DIRECTML,
    BACKEND_ONNX_CPU,
    BACKEND_PYTORCH_CPU,
)

# Preference order for ``auto``: fastest-in-principle first. Auto only ever
# picks a backend that is both available *and* able to caption, so this
# order expresses intent, never a claim about what actually ran.
BACKEND_PRIORITY = (
    BACKEND_ONNX_CUDA,
    BACKEND_ONNX_DIRECTML,
    BACKEND_ONNX_CPU,
    BACKEND_PYTORCH_CPU,
)

# Human labels for the UI. Vendor names appear only where the vendor's
# runtime is genuinely what executes.
BACKEND_LABELS = {
    BACKEND_AUTO: "Automatic (best available)",
    BACKEND_ONNX_CUDA: "NVIDIA GPU (CUDA)",
    BACKEND_ONNX_DIRECTML: "AMD / Intel GPU (DirectML)",
    BACKEND_ONNX_CPU: "CPU (ONNX Runtime)",
    BACKEND_PYTORCH_CPU: "CPU (PyTorch)",
}

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

    def can_caption(self) -> bool:
        """Can this backend actually produce captions right now?

        Separate from ``is_available`` on purpose: an ONNX backend's runtime
        can be perfectly available while no caption model exists for it. Auto
        selection requires both, so it can never pick a backend that would
        then have to silently hand the work to someone else.
        """
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


def detect_gpu_names() -> list[str]:
    """Every display adapter name Win32 reports, desktop-attached first.

    Best effort and read-only: we only ever report names the OS gave us, so
    a device name in the UI is never invented.
    """
    import ctypes

    try:
        user32 = ctypes.windll.user32
    except (AttributeError, OSError):
        return []

    class DISPLAY_DEVICEW(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("DeviceName", ctypes.c_wchar * 32),
            ("DeviceString", ctypes.c_wchar * 128),
            ("StateFlags", ctypes.c_ulong),
            ("DeviceID", ctypes.c_wchar * 128),
            ("DeviceKey", ctypes.c_wchar * 128),
        ]

    attached: list[str] = []
    others: list[str] = []
    seen: set[str] = set()
    index = 0
    while True:
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            break
        index += 1
        name = device.DeviceString.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        # StateFlags bit 0 = adapter attached to the desktop.
        (attached if device.StateFlags & 0x1 else others).append(name)
    return attached + others


# Substrings that identify an adapter vendor in a Win32 device string.
_VENDOR_HINTS = {
    "nvidia": ("nvidia", "geforce", "quadro", "rtx ", "gtx ", "tesla"),
    "amd": ("amd", "radeon", "firepro"),
    "intel": ("intel", "arc ", "iris", "uhd graphics", "hd graphics"),
}


def detect_gpu_name(vendor: Optional[str] = None) -> Optional[str]:
    """Adapter name, optionally restricted to a vendor.

    With ``vendor`` set, returns None rather than a different vendor's card:
    a CUDA backend must never label itself with a Radeon, and vice versa.
    """
    names = detect_gpu_names()
    if vendor is None:
        return names[0] if names else None
    hints = _VENDOR_HINTS.get(vendor.lower(), (vendor.lower(),))
    for name in names:
        lowered = name.lower()
        if any(hint in lowered for hint in hints):
            return name
    return None
