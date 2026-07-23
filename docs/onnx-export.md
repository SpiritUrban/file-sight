# BLIP → ONNX export and the DirectML result

Status: **export works, parity proven, GPU path wired into the worker and
CLI.** `cmd_scan` and `filesight scan --backend` route captions through
the selected ONNX / PyTorch backend (not a preloaded PyTorch-only path).

## Why a manual export

`optimum` has no ONNX config for BLIP:

```
ValueError: Trying to export a blip model, that is a custom or unsupported
architecture, but no custom onnx configuration was passed
```

So `scripts/export_blip_onnx.py` exports the two halves directly with
`torch.onnx.export`:

| File | Inputs | Output |
| --- | --- | --- |
| `vision_encoder.onnx` | `pixel_values` | `image_embeds` |
| `text_decoder.onnx` | `input_ids`, `attention_mask`, `encoder_hidden_states` | `logits` |

The decoder is exported **without a KV cache**. Captions are ~15 tokens,
so the quadratic re-computation is cheap next to running on the GPU at
all, and a cacheless graph is much easier to keep numerically identical
to PyTorch. The greedy loop lives in our code, not the graph.

Sizes (fp32): vision 344 MB + decoder 551 MB ≈ **900 MB**.

## The earlier blocker is gone

Iteration 6 session 1 recorded that `optimum` forced `transformers`
5.14 → 4.57 and a conflicting plain `onnxruntime`. With `optimum` 2.x the
ONNX exporter is a separate `optimum-onnx` package, and the export runs in
an **isolated** venv anyway, so the runtime stack is untouched. The
downgrade still happens *inside the export venv* — it just no longer
matters.

## How to run it

Use a **short path** — the scratchpad path exceeds Windows' limit and pip
fails mid-install:

```bash
python -m venv C:/Users/spiri/fsx
C:/Users/spiri/fsx/Scripts/python -m pip install optimum optimum-onnx onnx onnxruntime pillow onnxscript
PYTHONIOENCODING=utf-8 C:/Users/spiri/fsx/Scripts/python scripts/export_blip_onnx.py C:/Users/spiri/fsx-model
```

`PYTHONIOENCODING=utf-8` is required: torch prints ✅ and the default
cp1251 console raises `UnicodeEncodeError` mid-export.

## Results (measured on this machine, RX 580 + i5-2500)

Three images, greedy decoding, captions compared against PyTorch:

| Configuration | Captions identical | Per image |
| --- | --- | --- |
| PyTorch CPU (baseline) | — | 2615–2758 ms |
| ONNX, all CPU | **3/3** | 2483–4290 ms |
| ONNX, **vision on DirectML** + decoder CPU | **3/3** | **1669–2144 ms** |

The hybrid is roughly **1.3–1.6× faster than PyTorch CPU with byte-identical
captions** *when captioning is measured on its own*.

### …but the full scan is not faster

Same three images through the real worker, `allow_fallback: false` so
neither run could quietly switch device:

| Backend | Wall time, 3 images | Captions |
| --- | --- | --- |
| `pytorch-cpu` | **38.1 s** | identical |
| `onnx-directml` | **41.1 s** | identical |

The GPU path is *slightly slower end to end*. The arithmetic says why:
~12.7 s per file, of which captioning is ~2.7 s. Roughly **10 s per file is
spent somewhere other than inference**, so the ~1 s captioning win vanishes
into that overhead while DirectML's dispatch cost remains.

Conclusion to carry forward: **the GPU is not the bottleneck in a scan.**
Before optimising inference further, profile the other ~10 s per file
(image loading/decoding, thumbnailing, feature extraction, metadata,
report assembly). Choosing a GPU backend today buys correctness parity and
lower CPU load, not wall-clock speed.

## Why hybrid and not all-GPU

The decoder fails on DirectML:

```
Non-zero status code returned while running Reshape node. Name:'node_view_1'
DmlExecutionProvider ... 0x8007023E
```

The vision encoder runs on DirectML fine. The decoder hits a Reshape the
DirectML kernel rejects. Options not yet tried: re-export the decoder with
static shapes, simplify the graph (onnxsim), or fold the reshape.

Note the failure surfaces oddly: onnxruntime's localised error message is
not UTF-8, so Python raises `UnicodeDecodeError` while building the
exception rather than reporting the DirectML error itself.

## Gotcha: install the model where the app can actually see it

`%LOCALAPPDATA%` is **not** a safe install location when the model is placed
there by a sandboxed (MSIX/AppContainer) process. Windows silently redirects
such writes into the package's private store, e.g.

```
C:\Users\<user>\AppData\Local\FileSight
  -> C:\Users\<user>\AppData\Local\Packages\<Package>\LocalCache\Local\FileSight
```

The writing process then sees the model at the virtual path and reports it
found, while FileSight — running outside the sandbox — looks at the real
`AppData\Local\FileSight`, which does not exist. The symptom is a scan that
silently runs on the CPU after the user explicitly chose the GPU.

Diagnose it with the worker's own log line, which reports every candidate
path and the raw environment:

```
model pack search: env LOCALAPPDATA=... ;
  C:\Users\<user>\AppData\Local is_dir=True ;
  C:\Users\<user>\AppData\Local\FileSight is_dir=False ;
  [no such directory] ...
```

`AppData\Local is_dir=True` together with `…\FileSight is_dir=False` is the
redirection signature. Check for it with:

```powershell
(Get-Item "$env:LOCALAPPDATA\FileSight" -Force).Target
```

A non-empty `Target` means the folder is redirected. Install the model on a
plain, non-redirected path instead and point `FILESIGHT_ONNX_MODEL_DIR` at
it.

## Wiring (done) and remaining product work

**Done in the app:**

1. `OnnxDirectMlBackend` / `OnnxCpuBackend` caption via `OnnxBlipCaptioner`
   (vision on the requested provider, decoder on CPU for DirectML).
2. `can_caption()` is True only when the model pack is present.
3. `cmd_scan` uses `BackendCaptioner(resolve_backend(...))` so report
   `actual_backend` matches who really captioned (regression test in
   `test_scan_captions_via_resolved_backend_not_preloaded_pytorch`).
4. CLI: `filesight scan --backend onnx-directml` / `--no-allow-fallback`.
5. `--preload` warms the auto-selected caption backend and does **not**
   force-load PyTorch when ONNX can caption.

**Still open:**

1. Prefer installing the ~900 MB pack outside OneDrive-synced trees;
   point `FILESIGHT_ONNX_MODEL_DIR` at a local path if needed.
2. Profile the non-inference ~10 s/file (thumbnails, naming, I/O) — that
   is where wall-clock wins live, not the GPU encoder.
3. Broader quality comparison on real photographs beyond the three
   parity fixtures.
