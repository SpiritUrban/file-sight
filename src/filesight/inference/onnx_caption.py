"""BLIP captioning on ONNX Runtime.

The model ships as two graphs (see docs/onnx-export.md):

    vision_encoder.onnx   pixel_values -> image_embeds
    text_decoder.onnx     input_ids, attention_mask, encoder_hidden_states
                          -> logits

There is no KV cache in the decoder, so the greedy loop lives here: feed
the tokens produced so far, take the argmax of the last position, stop at
EOS. Captions are ~15 tokens, so re-running the decoder each step costs
far less than it sounds, and it keeps the graph numerically identical to
PyTorch (verified: 3/3 identical captions).

Placement of the two sessions is deliberate and asymmetric:

* **CUDA (NVIDIA):** both vision encoder and text decoder run on the GPU.
  The decoder graph works with ``CUDAExecutionProvider``.
* **DirectML (AMD/Intel):** vision on DirectML, decoder on CPU — DirectML
  rejects a Reshape in the decoder graph:

      Non-zero status code ... Reshape node 'node_view_1' ... 0x8007023E

* **ONNX CPU:** both halves on CPU.

Reports name both placements when they differ, so "DirectML" is never
read as "the whole model ran on the GPU".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

# Where a model pack may live, in priority order.
_ENV_VAR = "FILESIGHT_ONNX_MODEL_DIR"
_MODEL_SUBDIR = Path("FileSight") / "models" / "blip-onnx"

MAX_NEW_TOKENS = 20

CUDA_PROVIDER = "CUDAExecutionProvider"
DML_PROVIDER = "DmlExecutionProvider"
CPU_PROVIDER = "CPUExecutionProvider"

# Legacy alias: DirectML / default hybrid decoder placement.
DECODER_PROVIDER = CPU_PROVIDER


def decoder_provider_for(vision_provider: str) -> str:
    """Where the text decoder should run for a given vision provider.

    CUDA can host both graphs. DirectML cannot host the decoder (Reshape),
    so it falls back to CPU. CPU stays on CPU.
    """
    if vision_provider == CUDA_PROVIDER:
        return CUDA_PROVIDER
    return CPU_PROVIDER


def model_dir_candidates() -> list[Path]:
    """Every place a model pack may live, in priority order.

    Deliberately does not rely on %LOCALAPPDATA% alone: a process spawned
    by the desktop app does not always inherit it, and a missing variable
    used to make the model silently invisible — the scan then ran on the
    CPU while the user had explicitly chosen the GPU.
    """
    candidates: list[Path] = []
    override = os.environ.get(_ENV_VAR)
    if override:
        candidates.append(Path(override))

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / _MODEL_SUBDIR)

    # Same location derived without the environment, as a safety net.
    try:
        home = Path.home()
        candidates.append(home / "AppData" / "Local" / _MODEL_SUBDIR)
    except (OSError, RuntimeError):
        pass

    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / _MODEL_SUBDIR)

    # Repo-local checkout, handy during development.
    candidates.append(Path(__file__).resolve().parents[3] / "models" / "blip-onnx")

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _is_model_dir(candidate: Path) -> bool:
    try:
        return (candidate / "vision_encoder.onnx").is_file() and (
            candidate / "text_decoder.onnx"
        ).is_file()
    except OSError:
        return False


def find_model_dir() -> Optional[Path]:
    """Locate an exported ONNX caption model, or None when absent."""
    for candidate in model_dir_candidates():
        if _is_model_dir(candidate):
            return candidate
    return None


def describe_model_search() -> str:
    """Human-readable account of where the model was looked for.

    Reports *why* each candidate failed. ``_is_model_dir`` deliberately
    swallows OSError so a broken path cannot crash a scan, but that also
    hides permission errors — so this path re-raises and reports them.
    """
    lines = []
    # Raw inputs first: a wrong or missing variable, and a parent that is
    # itself invisible, look identical from the candidate list alone.
    for name in (_ENV_VAR, "LOCALAPPDATA", "APPDATA", "USERPROFILE"):
        lines.append(f"env {name}={os.environ.get(name)!r}")
    try:
        lines.append(f"home={Path.home()}")
        parent = Path.home() / "AppData" / "Local"
        lines.append(f"{parent} is_dir={parent.is_dir()}")
        filesight_dir = parent / "FileSight"
        lines.append(f"{filesight_dir} is_dir={filesight_dir.is_dir()}")
    except (OSError, RuntimeError) as exc:
        lines.append(f"home lookup failed: {exc}")

    for candidate in model_dir_candidates():
        try:
            has_dir = candidate.is_dir()
            vision = (candidate / "vision_encoder.onnx").is_file()
            decoder = (candidate / "text_decoder.onnx").is_file()
            if vision and decoder:
                verdict = "HIT"
            elif not has_dir:
                verdict = "no such directory"
            else:
                missing = []
                if not vision:
                    missing.append("vision_encoder.onnx")
                if not decoder:
                    missing.append("text_decoder.onnx")
                verdict = f"directory exists but missing {', '.join(missing)}"
        except OSError as exc:
            verdict = f"{type(exc).__name__}: {exc}"
        lines.append(f"[{verdict}] {candidate}")
    return "; ".join(lines)


def model_is_available() -> bool:
    return find_model_dir() is not None


def model_id(model_dir: Optional[Path] = None) -> Optional[str]:
    """The upstream model this pack was exported from, per its manifest."""
    model_dir = model_dir or find_model_dir()
    if model_dir is None:
        return None
    manifest = model_dir / "filesight-model.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return model_dir.name
    return data.get("model_id") or model_dir.name


class OnnxBlipCaptioner:
    """Greedy BLIP captioning over two ONNX Runtime sessions."""

    def __init__(
        self,
        model_dir: Path,
        vision_provider: str,
        decoder_provider: Optional[str] = None,
    ) -> None:
        self.model_dir = model_dir
        self.vision_provider = vision_provider
        self.decoder_provider = decoder_provider or decoder_provider_for(
            vision_provider
        )
        self._vision = None
        self._decoder = None
        self._processor = None
        self._config: dict = {}

    # -- setup -------------------------------------------------------------

    def _session_options(self, provider: str):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        # DirectML requires mem_pattern off; CUDA/CPU prefer it on.
        options.enable_mem_pattern = provider != DML_PROVIDER
        return options

    def initialize(self) -> None:
        if self._vision is not None:
            return
        import onnxruntime as ort
        from transformers import BlipProcessor

        manifest = self.model_dir / "filesight-model.json"
        self._config = (
            json.loads(manifest.read_text(encoding="utf-8"))
            if manifest.is_file()
            else {}
        )
        self._processor = BlipProcessor.from_pretrained(str(self.model_dir))

        self._vision = ort.InferenceSession(
            str(self.model_dir / "vision_encoder.onnx"),
            self._session_options(self.vision_provider),
            providers=[self.vision_provider],
        )
        try:
            self._decoder = ort.InferenceSession(
                str(self.model_dir / "text_decoder.onnx"),
                self._session_options(self.decoder_provider),
                providers=[self.decoder_provider],
            )
        except Exception:
            # CUDA path may still hit an unsupported op; fall back to CPU
            # decoder rather than failing the whole scan. Report stays honest
            # via actual_providers().
            if self.decoder_provider != CPU_PROVIDER:
                self.decoder_provider = CPU_PROVIDER
                self._decoder = ort.InferenceSession(
                    str(self.model_dir / "text_decoder.onnx"),
                    self._session_options(self.decoder_provider),
                    providers=[self.decoder_provider],
                )
            else:
                raise

    # -- inference ---------------------------------------------------------

    def caption(self, image: Image.Image) -> str:
        self.initialize()
        bos = int(self._config.get("bos_token_id", 30522))
        eos = int(self._config.get("eos_token_id", 102))

        pixel_values = self._processor(images=image, return_tensors="np")[
            "pixel_values"
        ].astype(np.float32)
        image_embeds = self._vision.run(None, {"pixel_values": pixel_values})[0]

        ids = np.array([[bos]], dtype=np.int64)
        for _ in range(MAX_NEW_TOKENS):
            logits = self._decoder.run(
                None,
                {
                    "input_ids": ids,
                    "attention_mask": np.ones_like(ids, dtype=np.int64),
                    "encoder_hidden_states": image_embeds,
                },
            )[0]
            next_token = int(np.argmax(logits[0, -1]))
            if next_token == eos:
                break
            ids = np.concatenate(
                [ids, np.array([[next_token]], dtype=np.int64)], axis=1
            )

        return self._processor.decode(ids[0], skip_special_tokens=True).strip()

    # -- diagnostics -------------------------------------------------------

    def actual_providers(self) -> tuple[Optional[str], Optional[str]]:
        """(vision, decoder) providers actually in use, or (None, None)."""
        if self._vision is None or self._decoder is None:
            return None, None
        vision = self._vision.get_providers()
        decoder = self._decoder.get_providers()
        return (vision[0] if vision else None, decoder[0] if decoder else None)

    def close(self) -> None:
        # Sessions are owned by the backend's cache; just detach.
        self._vision = None
        self._decoder = None
