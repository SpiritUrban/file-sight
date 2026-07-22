"""Backend construction, auto-selection and the fallback policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from filesight.inference.base import (
    BACKEND_AUTO,
    BACKEND_ONNX_CPU,
    BACKEND_ONNX_DIRECTML,
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
        }


# Reason recorded when a real scan cannot use an ONNX backend yet.
_CAPTION_NEEDS_PYTORCH = (
    "The caption model is not exported to ONNX yet, so captioning runs on "
    "PyTorch CPU. DirectML is verified separately via backend test and "
    "benchmark. See docs/iteration-06.md."
)


def _directml_available() -> bool:
    from filesight.inference.onnx_backends import OnnxDirectMlBackend

    try:
        return OnnxDirectMlBackend().is_available()
    except Exception:
        return False


def resolve_backend(
    requested: str = BACKEND_AUTO,
    allow_fallback: bool = True,
) -> BackendSelection:
    """Pick the backend that will caption this scan, honestly.

    Captioning currently runs only on PyTorch CPU (the ONNX caption model is
    not exported yet). ``auto`` therefore resolves to ``pytorch-cpu`` for
    captioning, while still recording whether DirectML is available so the
    report and UI can be truthful. Requesting an ONNX backend with fallback
    disabled surfaces a clear error rather than silently using the CPU.
    """
    if requested not in (BACKEND_AUTO, *KNOWN_BACKENDS):
        raise BackendError("UNKNOWN_BACKEND", f"Unknown backend: {requested!r}")

    dml_available = _directml_available()

    def pytorch_selection(fallback: bool, reason: Optional[str]) -> BackendSelection:
        backend = make_backend(BACKEND_PYTORCH_CPU)
        diag = backend.get_diagnostics()
        return BackendSelection(
            backend=backend,
            requested_backend=requested,
            actual_backend=BACKEND_PYTORCH_CPU,
            runtime=diag.runtime,
            runtime_version=diag.runtime_version,
            execution_provider=diag.execution_provider,
            device_name=diag.device_name,
            model_id=diag.model_id,
            fallback_occurred=fallback,
            fallback_reason=reason,
            directml_available=dml_available,
            notes=[reason] if reason else [],
        )

    if requested in (BACKEND_AUTO, BACKEND_PYTORCH_CPU):
        # auto notes that DirectML exists but captioning still needs PyTorch
        reason = _CAPTION_NEEDS_PYTORCH if requested == BACKEND_AUTO and dml_available else None
        return pytorch_selection(fallback=False, reason=reason)

    # An ONNX backend was explicitly requested but cannot caption yet.
    if not allow_fallback:
        raise BackendError(
            "BACKEND_CANNOT_CAPTION",
            f"Backend {requested!r} cannot generate captions yet and "
            "automatic fallback is disabled. Enable fallback or choose "
            "PyTorch CPU. See docs/iteration-06.md.",
        )
    return pytorch_selection(fallback=True, reason=_CAPTION_NEEDS_PYTORCH)


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
    """List concrete backends with a cheap availability flag (no self-test)."""
    out: list[dict] = []
    for backend_id in KNOWN_BACKENDS:
        try:
            backend = make_backend(backend_id)
            available = backend.is_available()
        except Exception:
            available = False
        out.append({"backend_id": backend_id, "available": available})
    return out
