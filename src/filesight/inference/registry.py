"""Backend construction, auto-selection and the fallback policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from filesight.inference.base import (
    BACKEND_AUTO,
    BACKEND_ONNX_CPU,
    BACKEND_ONNX_CUDA,
    BACKEND_ONNX_DIRECTML,
    BACKEND_PRIORITY,
    BACKEND_PYTORCH_CPU,
    KNOWN_BACKENDS,
    BackendDiagnostics,
    BackendError,
    InferenceBackend,
)


def make_backend(backend_id: str) -> InferenceBackend:
    """Construct a concrete backend by id. Does not initialize it."""
    if backend_id == BACKEND_PYTORCH_CPU:
        from filesight.inference.pytorch_cpu import PyTorchCpuBackend

        return PyTorchCpuBackend()
    if backend_id == BACKEND_ONNX_CPU:
        from filesight.inference.onnx_backends import OnnxCpuBackend

        return OnnxCpuBackend()
    if backend_id == BACKEND_ONNX_DIRECTML:
        from filesight.inference.onnx_backends import OnnxDirectMlBackend

        return OnnxDirectMlBackend()
    if backend_id == BACKEND_ONNX_CUDA:
        from filesight.inference.onnx_backends import OnnxCudaBackend

        return OnnxCudaBackend()
    raise BackendError("UNKNOWN_BACKEND", f"Unknown backend: {backend_id!r}")


def test_backend(backend_id: str) -> BackendDiagnostics:
    """Run a backend's self-test and return diagnostics. Never raises."""
    try:
        backend = make_backend(backend_id)
    except BackendError as exc:
        return BackendDiagnostics(
            backend_id=backend_id, available=False, runtime="unknown",
            self_test_passed=False, error=str(exc),
        )
    try:
        return backend.self_test()
    finally:
        try:
            backend.close()
        except Exception:
            pass


@dataclass
class BackendSelection:
    """The backend that will actually caption, plus honest provenance."""

    backend: InferenceBackend
    requested_backend: str
    actual_backend: str
    runtime: str
    runtime_version: Optional[str] = None
    execution_provider: Optional[str] = None
    device_name: Optional[str] = None
    model_id: Optional[str] = None
    fallback_occurred: bool = False
    fallback_reason: Optional[str] = None
    directml_available: bool = False
    cuda_available: bool = False
    considered: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def report_dict(self) -> dict:
        return {
            "requested_backend": self.requested_backend,
            "actual_backend": self.actual_backend,
            "runtime": self.runtime,
            "runtime_version": self.runtime_version,
            "execution_provider": self.execution_provider,
            "device_name": self.device_name,
            "model_id": self.model_id,
            "fallback_occurred": self.fallback_occurred,
            "fallback_reason": self.fallback_reason,
            "directml_available": self.directml_available,
            "cuda_available": self.cuda_available,
            # Why auto landed where it did — every candidate, in order,
            # with the honest reason it was or was not chosen.
            "considered": self.considered,
        }


# Reason recorded when a runtime is present but has no caption model.
_NO_CAPTION_MODEL = (
    "the ONNX caption model pack is not installed for this runtime, so it "
    "cannot run a scan (install the model pack or set "
    "FILESIGHT_ONNX_MODEL_DIR; see docs/onnx-export.md)"
)
_RUNTIME_MISSING = "runtime/provider not available on this machine"
_CHOSEN = "selected"


def _probe(backend_id: str) -> tuple[bool, bool, Optional[str]]:
    """(available, can_caption, error) for one backend. Never raises."""
    try:
        backend = make_backend(backend_id)
        available = backend.is_available()
        captions = bool(available and backend.can_caption())
        return available, captions, None
    except Exception as exc:
        return False, False, f"{type(exc).__name__}: {exc}"


def _provider_available(backend_id: str) -> bool:
    available, _, _ = _probe(backend_id)
    return available


def _directml_available() -> bool:
    return _provider_available(BACKEND_ONNX_DIRECTML)


def _cuda_available() -> bool:
    return _provider_available(BACKEND_ONNX_CUDA)


def _build_selection(
    backend_id: str,
    requested: str,
    *,
    fallback: bool,
    reason: Optional[str],
    considered: list[dict],
    dml_available: bool,
    cuda_available: bool,
) -> BackendSelection:
    backend = make_backend(backend_id)
    diag = backend.get_diagnostics()
    return BackendSelection(
        backend=backend,
        requested_backend=requested,
        actual_backend=backend_id,
        runtime=diag.runtime,
        runtime_version=diag.runtime_version,
        execution_provider=diag.execution_provider,
        device_name=diag.device_name,
        model_id=diag.model_id,
        fallback_occurred=fallback,
        fallback_reason=reason,
        directml_available=dml_available,
        cuda_available=cuda_available,
        considered=considered,
        notes=[reason] if reason else [],
    )


def select_auto_backend() -> tuple[Optional[str], list[dict]]:
    """Best backend that can genuinely caption, plus why each was ranked so.

    Walks ``BACKEND_PRIORITY`` (CUDA, DirectML, ONNX CPU, PyTorch CPU) and
    takes the first candidate that is both available and caption-capable. A
    backend whose runtime works but has no caption model is passed over and
    recorded as such — auto never picks something that would then hand the
    work to a different device than the one it names.
    """
    considered: list[dict] = []
    chosen: Optional[str] = None
    for backend_id in BACKEND_PRIORITY:
        available, captions, error = _probe(backend_id)
        if chosen is None and available and captions:
            chosen = backend_id
            why = _CHOSEN
        elif error:
            why = error
        elif not available:
            why = _RUNTIME_MISSING
        elif not captions:
            why = _NO_CAPTION_MODEL
        else:
            why = "lower priority than the selected backend"
        considered.append(
            {
                "backend_id": backend_id,
                "available": available,
                "can_caption": captions,
                "reason": why,
            }
        )
    return chosen, considered


def resolve_backend(
    requested: str = BACKEND_AUTO,
    allow_fallback: bool = True,
) -> BackendSelection:
    """Pick the backend that will caption this scan, honestly.

    ``auto`` walks the priority order and takes the best backend that can
    actually caption. Today only PyTorch CPU has a caption model, so auto
    still lands on the CPU even where DirectML or CUDA is present — and it
    records exactly why in ``considered``, so the UI never has to guess and
    can never overstate the device. Requesting a GPU backend explicitly
    falls back with a stated reason, or errors when fallback is disabled.
    """
    if requested not in (BACKEND_AUTO, *KNOWN_BACKENDS):
        raise BackendError("UNKNOWN_BACKEND", f"Unknown backend: {requested!r}")

    dml_available = _directml_available()
    cuda_available = _cuda_available()
    auto_choice, considered = select_auto_backend()

    if auto_choice is None:
        raise BackendError(
            "NO_USABLE_BACKEND",
            "No inference backend on this machine can generate captions. "
            "PyTorch CPU is the baseline and appears to be missing or "
            "broken; reinstall the Python dependencies.",
        )

    def picked(backend_id: str, fallback: bool, reason: Optional[str]):
        return _build_selection(
            backend_id, requested,
            fallback=fallback, reason=reason, considered=considered,
            dml_available=dml_available, cuda_available=cuda_available,
        )

    if requested == BACKEND_AUTO:
        skipped = [
            c["backend_id"] for c in considered
            if c["available"] and not c["can_caption"]
        ]
        reason = None
        if skipped:
            reason = (
                f"{', '.join(skipped)} available but skipped: "
                f"{_NO_CAPTION_MODEL}. See docs/iteration-06.md."
            )
        return picked(auto_choice, fallback=False, reason=reason)

    # An explicit request.
    available, captions, error = _probe(requested)
    if available and captions:
        return picked(requested, fallback=False, reason=None)

    why = error or (_RUNTIME_MISSING if not available else _NO_CAPTION_MODEL)
    if not allow_fallback:
        raise BackendError(
            "BACKEND_CANNOT_CAPTION",
            f"Backend {requested!r} cannot generate captions: {why}. "
            "Automatic fallback is disabled, so nothing was run. Enable "
            "fallback or choose a different backend. See docs/iteration-06.md.",
        )
    return picked(
        auto_choice,
        fallback=True,
        reason=(
            f"requested {requested!r} but {why}; fell back to "
            f"{auto_choice!r}."
        ),
    )


def benchmark_backend(
    backend_id: str, runs: int = 5, warmup_runs: int = 1
) -> dict:
    """Time a backend's self-test model. Honest, bounded, never renames.

    Returns cold-start, warm per-run timings and their average. Uses the
    self-test model (not the caption model), so it measures the runtime +
    execution provider, which is what backend choice affects.
    """
    import time

    runs = max(1, min(int(runs), 50))
    warmup_runs = max(0, min(int(warmup_runs), 10))

    backend = make_backend(backend_id)
    diag = backend.get_diagnostics()
    result: dict = {
        "backend": backend_id,
        "available": diag.available,
        "execution_provider": diag.execution_provider,
        "device_name": diag.device_name,
        "runtime": diag.runtime,
        "runtime_version": diag.runtime_version,
        "runs": runs,
        "warmup_runs": warmup_runs,
        "cold_start_ms": None,
        "per_run_ms": [],
        "average_ms": None,
        "error": None,
    }
    if not diag.available:
        result["error"] = f"{backend_id} is not available."
        return result

    try:
        import numpy as np

        cold = time.perf_counter()
        backend.initialize()
        result["cold_start_ms"] = int((time.perf_counter() - cold) * 1000)

        # The self-test model has a fixed 1x32 input; captioning backends
        # override _bench_once for a real caption timing.
        timings = _time_backend(backend, runs, warmup_runs)
        result["per_run_ms"] = [round(ms, 3) for ms in timings]
        result["average_ms"] = round(sum(timings) / len(timings), 3)
        # peak process RAM, best effort
        result["peak_ram_mb"] = _peak_ram_mb()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            backend.close()
        except Exception:
            pass
    return result


def _time_backend(backend, runs: int, warmup_runs: int) -> list[float]:
    """Run a backend's cheapest real operation `runs` times, in ms."""
    import time

    import numpy as np
    from PIL import Image

    onnx_session = getattr(backend, "_session", None)
    if onnx_session is not None:
        x = np.ones((1, 32), dtype=np.float32)
        for _ in range(warmup_runs):
            onnx_session.run(None, {"X": x})
        timings = []
        for _ in range(runs):
            start = time.perf_counter()
            onnx_session.run(None, {"X": x})
            timings.append((time.perf_counter() - start) * 1000)
        return timings

    # Captioning backend: time a real caption on a probe image.
    probe = Image.new("RGB", (128, 128), (90, 120, 60))
    for _ in range(warmup_runs):
        backend.caption_image(probe)
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        backend.caption_image(probe)
        timings.append((time.perf_counter() - start) * 1000)
    return timings


def _peak_ram_mb() -> Optional[int]:
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        # Modern Windows exposes this as K32GetProcessMemoryInfo in
        # kernel32; older psapi.dll has GetProcessMemoryInfo. Try both.
        fn = getattr(ctypes.windll.kernel32, "K32GetProcessMemoryInfo", None)
        if fn is None:
            fn = ctypes.windll.psapi.GetProcessMemoryInfo
        if fn(handle, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize / (1024 * 1024))
    except Exception:
        return None
    return None


def available_backends() -> list[dict]:
    """List concrete backends with cheap flags (no self-test, no model load).

    ``available`` means the runtime is present; ``can_caption`` means it can
    actually run a scan. The UI needs both so it can offer a backend while
    telling the truth about what it will do.
    """
    from filesight.inference.base import BACKEND_LABELS

    out: list[dict] = []
    for backend_id in KNOWN_BACKENDS:
        available, captions, error = _probe(backend_id)
        out.append(
            {
                "backend_id": backend_id,
                "label": BACKEND_LABELS.get(backend_id, backend_id),
                "available": available,
                "can_caption": captions,
                "error": error,
            }
        )
    return out
