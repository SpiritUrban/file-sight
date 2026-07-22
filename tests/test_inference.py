"""Inference backend registry, selection, fallback and diagnostics.

DirectML-specific assertions are skipped when the provider is unavailable,
so these run on any machine; a skipped DirectML test is never counted as a
passed GPU check.
"""

from __future__ import annotations

import pytest

from filesight.inference import (
    BACKEND_AUTO,
    BACKEND_ONNX_CPU,
    BACKEND_ONNX_CUDA,
    BACKEND_ONNX_DIRECTML,
    BACKEND_PRIORITY,
    BACKEND_PYTORCH_CPU,
    available_backends,
    benchmark_backend,
    resolve_backend,
    select_auto_backend,
)
# Aliased so pytest does not collect the `test_backend` helper as a test.
from filesight.inference import test_backend as run_backend_test
from filesight.inference.base import (
    BackendError,
    detect_gpu_name,
    detect_gpu_names,
)
from filesight.inference.onnx_backends import (
    OnnxCpuBackend,
    OnnxCudaBackend,
    OnnxDirectMlBackend,
    reset_session_cache,
)
from filesight.inference.registry import make_backend


def _onnx_installed() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _directml_available() -> bool:
    if not _onnx_installed():
        return False
    return OnnxDirectMlBackend().is_available()


onnx = pytest.mark.skipif(not _onnx_installed(), reason="onnxruntime not installed")
dml = pytest.mark.skipif(
    not _directml_available(), reason="DirectML provider not available"
)


@pytest.fixture(autouse=True)
def _clean_sessions():
    reset_session_cache()
    yield
    reset_session_cache()


# --- registry / construction ---------------------------------------------


def test_make_backend_for_each_id() -> None:
    assert make_backend(BACKEND_PYTORCH_CPU).backend_id == BACKEND_PYTORCH_CPU
    assert make_backend(BACKEND_ONNX_CPU).backend_id == BACKEND_ONNX_CPU
    assert make_backend(BACKEND_ONNX_DIRECTML).backend_id == BACKEND_ONNX_DIRECTML
    assert make_backend(BACKEND_ONNX_CUDA).backend_id == BACKEND_ONNX_CUDA


def test_unknown_backend_raises() -> None:
    with pytest.raises(BackendError):
        make_backend("gpu")  # deliberately vague id is not accepted


def test_available_backends_lists_all_four() -> None:
    ids = {b["backend_id"] for b in available_backends()}
    assert ids == {
        BACKEND_ONNX_CUDA, BACKEND_ONNX_DIRECTML,
        BACKEND_ONNX_CPU, BACKEND_PYTORCH_CPU,
    }


def test_available_backends_separate_runtime_from_captioning() -> None:
    rows = {b["backend_id"]: b for b in available_backends()}
    # A present runtime must never be reported as caption-capable while no
    # ONNX caption model exists.
    for backend_id in (BACKEND_ONNX_CUDA, BACKEND_ONNX_DIRECTML, BACKEND_ONNX_CPU):
        assert rows[backend_id]["can_caption"] is False
    assert rows[BACKEND_PYTORCH_CPU]["can_caption"] is True
    assert all(b["label"] for b in rows.values())


# --- priority order --------------------------------------------------------


def test_priority_prefers_gpu_then_cpu() -> None:
    assert BACKEND_PRIORITY == (
        BACKEND_ONNX_CUDA, BACKEND_ONNX_DIRECTML,
        BACKEND_ONNX_CPU, BACKEND_PYTORCH_CPU,
    )


def test_auto_picks_only_caption_capable_backend() -> None:
    choice, considered = select_auto_backend()
    assert choice == BACKEND_PYTORCH_CPU
    ordered = [c["backend_id"] for c in considered]
    assert ordered == list(BACKEND_PRIORITY)
    chosen = [c for c in considered if c["reason"] == "selected"]
    assert len(chosen) == 1 and chosen[0]["backend_id"] == choice


def test_auto_records_a_reason_for_every_candidate() -> None:
    _, considered = select_auto_backend()
    assert all(c["reason"] for c in considered)
    # An available-but-unusable runtime is explained, not silently dropped.
    for c in considered:
        if c["available"] and not c["can_caption"]:
            assert "caption model" in c["reason"]


def test_auto_would_pick_gpu_once_it_can_caption(monkeypatch) -> None:
    """The single switch: when a GPU backend gains a caption model, auto
    must choose it over the CPU without any other change."""
    import filesight.inference.registry as reg

    real_probe = reg._probe

    def fake_probe(backend_id: str):
        if backend_id == BACKEND_ONNX_DIRECTML:
            return True, True, None  # pretend the ONNX export landed
        return real_probe(backend_id)

    monkeypatch.setattr(reg, "_probe", fake_probe)
    choice, _ = reg.select_auto_backend()
    assert choice == BACKEND_ONNX_DIRECTML
    assert reg.resolve_backend(BACKEND_AUTO).actual_backend == BACKEND_ONNX_DIRECTML


def test_cuda_wins_over_directml_when_both_caption(monkeypatch) -> None:
    import filesight.inference.registry as reg

    monkeypatch.setattr(reg, "_probe", lambda b: (True, True, None))
    choice, _ = reg.select_auto_backend()
    assert choice == BACKEND_ONNX_CUDA


# --- auto selection & fallback policy -------------------------------------


def test_auto_selects_pytorch_for_captioning() -> None:
    # Captioning is PyTorch CPU until the ONNX caption model exists.
    selection = resolve_backend(BACKEND_AUTO)
    assert selection.actual_backend == BACKEND_PYTORCH_CPU
    assert selection.runtime == "pytorch"


def test_auto_records_directml_availability() -> None:
    selection = resolve_backend(BACKEND_AUTO)
    assert selection.directml_available == _directml_available()


def test_requesting_onnx_falls_back_when_allowed() -> None:
    selection = resolve_backend(BACKEND_ONNX_DIRECTML, allow_fallback=True)
    assert selection.actual_backend == BACKEND_PYTORCH_CPU
    assert selection.fallback_occurred is True
    assert selection.fallback_reason


def test_requesting_onnx_without_fallback_raises() -> None:
    with pytest.raises(BackendError) as exc:
        resolve_backend(BACKEND_ONNX_CPU, allow_fallback=False)
    assert exc.value.code == "BACKEND_CANNOT_CAPTION"


def test_pytorch_request_has_no_spurious_fallback() -> None:
    selection = resolve_backend(BACKEND_PYTORCH_CPU)
    assert selection.actual_backend == BACKEND_PYTORCH_CPU
    assert selection.fallback_occurred is False


def test_unknown_requested_backend_raises() -> None:
    with pytest.raises(BackendError):
        resolve_backend("fast")


def test_selection_report_dict_is_honest() -> None:
    data = resolve_backend(BACKEND_AUTO).report_dict()
    assert data["actual_backend"] == BACKEND_PYTORCH_CPU
    assert data["requested_backend"] == BACKEND_AUTO
    assert set(data) >= {
        "requested_backend", "actual_backend", "runtime",
        "execution_provider", "device_name", "fallback_occurred",
        "fallback_reason", "directml_available",
    }


# --- ONNX backends never silently caption ---------------------------------


@onnx
def test_onnx_backend_refuses_to_caption() -> None:
    from PIL import Image

    backend = OnnxCpuBackend()
    with pytest.raises(BackendError) as exc:
        backend.caption_image(Image.new("RGB", (8, 8)))
    assert exc.value.code == "ONNX_CAPTION_UNAVAILABLE"


# --- self-test ------------------------------------------------------------


@onnx
def test_onnx_cpu_self_test_passes() -> None:
    diag = run_backend_test(BACKEND_ONNX_CPU)
    assert diag.available is True
    assert diag.self_test_passed is True
    assert diag.execution_provider == "CPUExecutionProvider"
    assert diag.runtime == "onnxruntime"


@dml
def test_directml_self_test_passes_on_this_gpu() -> None:
    diag = run_backend_test(BACKEND_ONNX_DIRECTML)
    assert diag.available is True
    assert diag.self_test_passed is True, diag.error
    assert diag.execution_provider == "DmlExecutionProvider"
    # honest device name, never invented
    assert diag.device_name
    assert diag.device_name == detect_gpu_name()


def test_directml_diagnostics_when_unavailable() -> None:
    if _directml_available():
        pytest.skip("DirectML is available here")
    diag = run_backend_test(BACKEND_ONNX_DIRECTML)
    assert diag.available is False
    assert diag.self_test_passed is False


@onnx
def test_pytorch_self_test_passes() -> None:
    diag = run_backend_test(BACKEND_PYTORCH_CPU)
    assert diag.self_test_passed is True
    assert diag.runtime == "pytorch"
    assert diag.model_loaded is True


# --- benchmark ------------------------------------------------------------


@onnx
def test_benchmark_returns_real_timings() -> None:
    result = benchmark_backend(BACKEND_ONNX_CPU, runs=3)
    assert result["error"] is None
    assert len(result["per_run_ms"]) == 3
    assert result["average_ms"] is not None
    assert all(ms >= 0 for ms in result["per_run_ms"])


def test_benchmark_clamps_runs() -> None:
    result = benchmark_backend(BACKEND_ONNX_CPU, runs=9999)
    assert result["runs"] <= 50


@dml
def test_directml_benchmark_reports_the_provider() -> None:
    result = benchmark_backend(BACKEND_ONNX_DIRECTML, runs=3)
    assert result["execution_provider"] == "DmlExecutionProvider"
    assert result["device_name"] == detect_gpu_name()


# --- session reuse (the deadlock fix) -------------------------------------


@dml
def test_directml_sessions_are_reused_not_recreated() -> None:
    from filesight.inference.onnx_backends import _SESSION_CACHE

    reset_session_cache()
    a = OnnxDirectMlBackend()
    a.initialize()
    session_a = a._session
    b = OnnxDirectMlBackend()
    b.initialize()
    # Same provider -> same cached session object; a second DirectML
    # session is what deadlocks under piped stdio.
    assert a._session is b._session
    assert _SESSION_CACHE["DmlExecutionProvider"] is session_a


# --- CUDA / NVIDIA --------------------------------------------------------


def _cuda_available() -> bool:
    if not _onnx_installed():
        return False
    return OnnxCudaBackend().is_available()


cuda = pytest.mark.skipif(
    not _cuda_available(), reason="CUDA provider not available"
)


def test_cuda_backend_never_claims_another_vendors_gpu() -> None:
    """The RX 580 must never be reported as the CUDA device."""
    backend = OnnxCudaBackend()
    name = backend._device_name()
    if not backend.is_available():
        assert name is None
    if name is not None:
        assert any(
            hint in name.lower()
            for hint in ("nvidia", "geforce", "quadro", "rtx", "gtx", "tesla")
        )


def test_cuda_diagnostics_when_unavailable() -> None:
    if _cuda_available():
        pytest.skip("CUDA is available here")
    diag = run_backend_test(BACKEND_ONNX_CUDA)
    assert diag.available is False
    assert diag.self_test_passed is False
    assert diag.device_name is None


def test_requesting_cuda_without_nvidia_falls_back_honestly() -> None:
    if _cuda_available():
        pytest.skip("CUDA is available here")
    selection = resolve_backend(BACKEND_ONNX_CUDA, allow_fallback=True)
    assert selection.actual_backend == BACKEND_PYTORCH_CPU
    assert selection.fallback_occurred is True
    assert "onnx-cuda" in selection.fallback_reason
    assert selection.cuda_available is False


@cuda
def test_cuda_self_test_passes_on_this_gpu() -> None:
    diag = run_backend_test(BACKEND_ONNX_CUDA)
    assert diag.self_test_passed is True, diag.error
    assert diag.execution_provider == "CUDAExecutionProvider"
    assert diag.device_name == detect_gpu_name("nvidia")


# --- device name ----------------------------------------------------------


def test_detect_gpu_name_is_str_or_none() -> None:
    name = detect_gpu_name()
    assert name is None or isinstance(name, str)


def test_detect_gpu_names_returns_list() -> None:
    names = detect_gpu_names()
    assert isinstance(names, list)
    assert all(isinstance(n, str) and n for n in names)
    assert len(names) == len(set(names))  # de-duplicated


def test_vendor_filter_returns_none_for_absent_vendor() -> None:
    assert detect_gpu_name("definitely-not-a-gpu-vendor") is None
