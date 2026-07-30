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


def _torch_installed() -> bool:
    try:
        import torch  # noqa: F401
    except Exception:
        return False
    return True


def _model_pack() -> bool:
    """Is an exported ONNX caption model installed on this machine?"""
    from filesight.inference.onnx_caption import model_is_available

    return model_is_available()


onnx = pytest.mark.skipif(not _onnx_installed(), reason="onnxruntime not installed")
# PyTorch is a ~200 MB install and loading BLIP pulls ~1 GB from Hugging Face.
# The tests that genuinely need it say so, so a lean environment reports
# "skipped: torch not installed" instead of failing for the wrong reason.
torch_required = pytest.mark.skipif(
    not _torch_installed(), reason="torch not installed"
)
dml = pytest.mark.skipif(
    not _directml_available(), reason="DirectML provider not available"
)
needs_model = pytest.mark.skipif(
    not _model_pack(), reason="ONNX caption model pack not installed"
)
no_model = pytest.mark.skipif(
    _model_pack(), reason="ONNX caption model pack is installed here"
)


def _best_caption_backend() -> str:
    """What auto should choose here, derived independently of the code
    under test: the first priority entry that can really caption."""
    from filesight.inference.registry import _probe

    for backend_id in BACKEND_PRIORITY:
        available, captions, _ = _probe(backend_id)
        if available and captions:
            return backend_id
    raise AssertionError("no caption-capable backend on this machine")


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


@torch_required
def test_available_backends_separate_runtime_from_captioning() -> None:
    rows = {b["backend_id"]: b for b in available_backends()}
    # An ONNX backend may only claim captioning when BOTH its runtime and
    # the exported model pack are present — never on the runtime alone.
    for backend_id in (BACKEND_ONNX_CUDA, BACKEND_ONNX_DIRECTML, BACKEND_ONNX_CPU):
        row = rows[backend_id]
        assert row["can_caption"] == (row["available"] and _model_pack())
    assert rows[BACKEND_PYTORCH_CPU]["can_caption"] is True
    assert all(b["label"] for b in rows.values())


@no_model
def test_onnx_cannot_caption_without_the_model_pack() -> None:
    rows = {b["backend_id"]: b for b in available_backends()}
    for backend_id in (BACKEND_ONNX_DIRECTML, BACKEND_ONNX_CPU):
        assert rows[backend_id]["can_caption"] is False


# --- priority order --------------------------------------------------------


def test_priority_prefers_gpu_then_cpu() -> None:
    assert BACKEND_PRIORITY == (
        BACKEND_ONNX_CUDA, BACKEND_ONNX_DIRECTML,
        BACKEND_ONNX_CPU, BACKEND_PYTORCH_CPU,
    )


def test_auto_picks_only_caption_capable_backend() -> None:
    choice, considered = select_auto_backend()
    assert choice == _best_caption_backend()
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


def test_auto_selects_the_best_caption_capable_backend() -> None:
    selection = resolve_backend(BACKEND_AUTO)
    assert selection.actual_backend == _best_caption_backend()


@needs_model
def test_auto_prefers_the_gpu_when_it_can_really_caption() -> None:
    """With the model pack installed, auto must stop settling for the CPU."""
    if not _directml_available():
        pytest.skip("no DirectML on this machine")
    selection = resolve_backend(BACKEND_AUTO)
    assert selection.actual_backend == BACKEND_ONNX_DIRECTML
    assert selection.runtime == "onnxruntime"
    assert selection.device_name == detect_gpu_name()
    assert selection.fallback_occurred is False


@no_model
def test_auto_falls_back_to_pytorch_without_a_model_pack() -> None:
    selection = resolve_backend(BACKEND_AUTO)
    assert selection.actual_backend == BACKEND_PYTORCH_CPU
    assert selection.runtime == "pytorch"


def test_auto_records_directml_availability() -> None:
    selection = resolve_backend(BACKEND_AUTO)
    assert selection.directml_available == _directml_available()


@no_model
def test_requesting_onnx_falls_back_when_allowed() -> None:
    selection = resolve_backend(BACKEND_ONNX_DIRECTML, allow_fallback=True)
    assert selection.actual_backend == BACKEND_PYTORCH_CPU
    assert selection.fallback_occurred is True
    assert selection.fallback_reason


@no_model
def test_requesting_onnx_without_fallback_raises() -> None:
    with pytest.raises(BackendError) as exc:
        resolve_backend(BACKEND_ONNX_CPU, allow_fallback=False)
    assert exc.value.code == "BACKEND_CANNOT_CAPTION"


@needs_model
def test_requesting_onnx_is_honoured_when_it_can_caption() -> None:
    """The user's explicit GPU choice must actually be used, not silently
    downgraded, once the model pack makes it possible."""
    if not _directml_available():
        pytest.skip("no DirectML on this machine")
    selection = resolve_backend(BACKEND_ONNX_DIRECTML, allow_fallback=False)
    assert selection.actual_backend == BACKEND_ONNX_DIRECTML
    assert selection.fallback_occurred is False


@torch_required
def test_pytorch_request_has_no_spurious_fallback() -> None:
    selection = resolve_backend(BACKEND_PYTORCH_CPU)
    assert selection.actual_backend == BACKEND_PYTORCH_CPU
    assert selection.fallback_occurred is False


def test_unknown_requested_backend_raises() -> None:
    with pytest.raises(BackendError):
        resolve_backend("fast")


def test_selection_report_dict_is_honest() -> None:
    data = resolve_backend(BACKEND_AUTO).report_dict()
    assert data["actual_backend"] == _best_caption_backend()
    assert data["requested_backend"] == BACKEND_AUTO
    assert set(data) >= {
        "requested_backend", "actual_backend", "runtime",
        "execution_provider", "device_name", "fallback_occurred",
        "fallback_reason", "directml_available",
    }


# --- ONNX backends never silently caption ---------------------------------


@onnx
def test_onnx_backend_refuses_to_caption_without_a_model(monkeypatch) -> None:
    """Missing model must be a clear error, never a silent hand-off to
    PyTorch dressed up as an ONNX result."""
    from PIL import Image

    import filesight.inference.onnx_caption as oc

    monkeypatch.setattr(oc, "find_model_dir", lambda: None)
    backend = OnnxCpuBackend()
    with pytest.raises(BackendError) as exc:
        backend.caption_image(Image.new("RGB", (8, 8)))
    assert exc.value.code == "ONNX_MODEL_MISSING"


@onnx
@needs_model
@torch_required
def test_onnx_cpu_really_captions() -> None:
    from PIL import Image

    result = OnnxCpuBackend().caption_image(Image.new("RGB", (64, 64), (30, 90, 160)))
    assert result.caption
    assert result.backend_id == BACKEND_ONNX_CPU


@dml
@needs_model
def test_directml_really_captions_on_this_gpu() -> None:
    from PIL import Image

    result = OnnxDirectMlBackend().caption_image(
        Image.new("RGB", (64, 64), (200, 120, 40))
    )
    assert result.caption
    assert result.backend_id == BACKEND_ONNX_DIRECTML


@dml
@needs_model
def test_directml_diagnostics_name_both_placements() -> None:
    """The decoder runs on CPU, so the report must not read as though the
    whole model ran on the GPU."""
    diag = OnnxDirectMlBackend().get_diagnostics()
    assert "DmlExecutionProvider" in diag.execution_provider
    assert "CPUExecutionProvider" in diag.execution_provider
    assert "vision" in diag.execution_provider
    assert "decoder" in diag.execution_provider
    assert any("decoder runs on CPU" in note for note in diag.notes)


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
    assert "DmlExecutionProvider" in diag.execution_provider
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
@torch_required
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
    assert "DmlExecutionProvider" in result["execution_provider"]
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


# --- decoder placement ----------------------------------------------------


def test_decoder_provider_cuda_uses_gpu() -> None:
    from filesight.inference.onnx_caption import decoder_provider_for

    assert decoder_provider_for("CUDAExecutionProvider") == "CUDAExecutionProvider"


def test_decoder_provider_directml_stays_on_cpu() -> None:
    from filesight.inference.onnx_caption import decoder_provider_for

    assert decoder_provider_for("DmlExecutionProvider") == "CPUExecutionProvider"
    assert decoder_provider_for("CPUExecutionProvider") == "CPUExecutionProvider"


def test_onnx_blip_captioner_defaults_decoder_from_vision(tmp_path) -> None:
    from pathlib import Path

    from filesight.inference.onnx_caption import OnnxBlipCaptioner

    cuda = OnnxBlipCaptioner(Path(tmp_path), "CUDAExecutionProvider")
    assert cuda.decoder_provider == "CUDAExecutionProvider"

    dml = OnnxBlipCaptioner(Path(tmp_path), "DmlExecutionProvider")
    assert dml.decoder_provider == "CPUExecutionProvider"


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
    assert selection.actual_backend == _best_caption_backend()
    assert selection.actual_backend != BACKEND_ONNX_CUDA
    assert selection.fallback_occurred is True
    assert "onnx-cuda" in selection.fallback_reason
    assert selection.cuda_available is False


@cuda
def test_cuda_self_test_passes_on_this_gpu() -> None:
    diag = run_backend_test(BACKEND_ONNX_CUDA)
    assert diag.self_test_passed is True, diag.error
    assert diag.execution_provider == "CUDAExecutionProvider"
    assert diag.device_name == detect_gpu_name("nvidia")


# --- model pack discovery -------------------------------------------------


def test_model_search_survives_a_missing_localappdata(monkeypatch) -> None:
    """Regression: the desktop app's worker did not inherit %LOCALAPPDATA%,
    so the model became invisible and scans silently ran on the CPU while
    the user had explicitly chosen the GPU."""
    from filesight.inference.onnx_caption import model_dir_candidates

    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    candidates = model_dir_candidates()
    assert candidates, "no candidate paths without LOCALAPPDATA"
    # The standard per-user location must still be reachable via the home
    # directory rather than the environment alone.
    assert any(
        "appdata" in str(c).lower() and "local" in str(c).lower()
        for c in candidates
    )


def test_model_search_prefers_the_explicit_override(monkeypatch, tmp_path) -> None:
    from filesight.inference.onnx_caption import model_dir_candidates

    monkeypatch.setenv("FILESIGHT_ONNX_MODEL_DIR", str(tmp_path))
    assert model_dir_candidates()[0] == tmp_path


def test_model_search_is_reported_for_diagnosis() -> None:
    """Every candidate is accounted for, whatever the verdict happens to be.

    The earlier version asserted `"HIT" in text or "miss" in text`. Those are
    only two of four verdicts the function can emit, and which one occurs
    depends on the machine: with a model pack installed it says HIT, with a
    half-populated directory it says "missing ...", and on a machine that has
    neither -- a CI runner, or any fresh checkout, since `models/` is
    gitignored -- every candidate is "no such directory" and the assertion
    failed for a reason that had nothing to do with the code.
    """
    from filesight.inference.onnx_caption import (
        describe_model_search,
        model_dir_candidates,
    )

    text = describe_model_search()
    assert text
    # The raw inputs, so a missing variable is distinguishable from a bad one.
    assert "env FILESIGHT_ONNX_MODEL_DIR=" in text
    # Every candidate appears, each with a bracketed verdict. That is the
    # contract; the wording of the verdict is not.
    candidates = model_dir_candidates()
    assert candidates, "there must always be somewhere to look"
    for candidate in candidates:
        assert str(candidate) in text
    assert text.count("[") >= len(candidates)


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
