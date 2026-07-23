# FileSight on NVIDIA GeForce / GTX / RTX

How to run FileSight with **CUDA** (`onnx-cuda`) on a second Windows PC.

## What you need

| Item | Notes |
| --- | --- |
| Windows 10/11 64-bit | Same as the AMD build |
| NVIDIA GeForce GTX/RTX | Driver current from nvidia.com |
| Python **3.11 or 3.12** | Best wheel support for `onnxruntime-gpu`. 3.13/3.14 may lack a GPU wheel. |
| This repo (or install) | Plus the ONNX model pack (~900 MB) |
| **No** `onnxruntime-directml` | Only one `onnxruntime` package can be installed |

DirectML and CUDA wheels **conflict**. On the NVIDIA box install **only**
`onnxruntime-gpu`.

## One-shot setup

From the repo root (PowerShell):

```powershell
# Optional: create a dedicated venv with Python 3.12
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# Core app + CUDA ONNX Runtime
pip install -U pip
pip install -e ".[dev,cuda]"

# Sanity check (must list CUDAExecutionProvider)
python scripts/check_inference.py
```

Or run the helper (creates/uses `.venv`, installs CUDA extra, checks providers):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_nvidia.ps1
```

## Model pack

Captioning needs the exported BLIP ONNX pack (same files as on the AMD PC):

```
models/blip-onnx/
  vision_encoder.onnx (+ .data)
  text_decoder.onnx (+ .data)
  tokenizer* / preprocessor* / filesight-model.json
```

Copy that folder to the GTX PC, then either:

1. Keep it at `<repo>/models/blip-onnx` (auto-discovered), or  
2. Set a fixed path:

```powershell
$env:FILESIGHT_ONNX_MODEL_DIR = "D:\models\blip-onnx"
```

Do **not** rely on a sandboxed `%LOCALAPPDATA%` copy from another machine.

## What `auto` should pick

Priority: **CUDA → DirectML → ONNX CPU → PyTorch CPU**.

On a healthy GTX box with the model pack:

```text
actual_backend = onnx-cuda
device_name    = NVIDIA GeForce GTX …
execution_provider = CUDAExecutionProvider   # both halves when decoder stays on GPU
```

If CUDA is missing or the model pack is absent, FileSight falls back and
records why (`fallback_occurred`, `considered`).

## CUDA vs DirectML caption layout

| Backend | Vision | Decoder |
| --- | --- | --- |
| `onnx-cuda` | CUDA | CUDA (falls back to CPU if the graph is rejected) |
| `onnx-directml` | DirectML | CPU (Reshape not supported) |
| `onnx-cpu` | CPU | CPU |

So a GTX **can** be faster than the RX 580 path, because the long decoder
loop may finally run on the GPU. Wall-clock of a full scan still includes
~10 s/file outside inference (thumbnails, I/O, naming) — see
`docs/onnx-export.md`.

## Verify before a real folder scan

```powershell
# Providers + auto choice (no full model load beyond cheap probes)
python scripts/check_inference.py

# Worker self-test on CUDA
python -c "from filesight.inference import test_backend; print(test_backend('onnx-cuda').to_dict())"

# One image, force CUDA, no silent fallback
python -m filesight scan path\to\photos --max-files 1 --backend onnx-cuda --no-allow-fallback --overwrite-report
```

In Task Manager on NVIDIA, open the GPU pane and watch **CUDA** (not only
3D). Decoder work shows up more clearly than the short DirectML vision
burst on AMD.

## Desktop app

1. Install Python deps as above (same `.venv` the Tauri app discovers).
2. Copy the model pack.
3. Settings → Inference → **Automatic** or **NVIDIA GPU (CUDA)**.
4. Test backend / scan; footer must say `onnx-cuda`, not `pytorch-cpu`.

## Common failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| `cuda_available: false` | `onnxruntime-directml` or CPU-only wheel | `pip uninstall onnxruntime onnxruntime-directml -y` then `pip install onnxruntime-gpu` |
| `CUDAExecutionProvider` missing | Old driver / wrong Python | Update NVIDIA driver; use Python 3.11–3.12 |
| Auto stays on `pytorch-cpu` | No model pack | Set `FILESIGHT_ONNX_MODEL_DIR` or copy `models/blip-onnx` |
| Import/DLL errors on first CUDA session | Incomplete CUDA redistributables | Install latest Game Ready / Studio driver; reboot |

## Package reference

```toml
# pyproject.toml optional extras — install only ONE onnxruntime flavor
[project.optional-dependencies]
directml = ["onnxruntime-directml>=1.24"]  # AMD PC
cuda     = ["onnxruntime-gpu>=1.18"]       # NVIDIA PC
onnx     = ["onnxruntime>=1.18"]           # CPU only
```
