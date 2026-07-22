# FileSight — Windows performance report (iteration 6)

All numbers below are **measured**, not estimated. Where a comparison is
not apples-to-apples it is stated.

## Test machine

| | |
| --- | --- |
| CPU | (as reported by the OS on the dev machine) |
| GPU | AMD Radeon RX 580 Series, 4 GB VRAM, driver 31.0.21923.11000 |
| RAM | 32 GB |
| OS | Windows 11 Pro for Workstations |
| App version | 0.6.0 |
| Python | 3.14.0 |
| onnxruntime-directml | 1.24.4 |
| Caption model | Salesforce/blip-image-captioning-base (PyTorch) |

## Backend self-test / benchmark (measured)

`benchmark_backend`, 5 runs, 1 warm-up:

| Backend | Execution provider | Cold start | Avg per run | Model timed |
| --- | --- | --- | --- | --- |
| `pytorch-cpu` | CPU | 9216 ms | **7145 ms** | real BLIP caption |
| `onnx-cpu` | CPUExecutionProvider | 68 ms | 0.035 ms | self-test 32×32 |
| `onnx-directml` | DmlExecutionProvider | 283 ms | 0.417 ms | self-test 32×32 |

### How to read this honestly

- **PyTorch CPU is the only row that captions a real image.** ~7.1 s per
  image is the actual captioning cost today (and what a scan spends).
- The ONNX rows time the tiny **self-test** model (32×32 MatMul+Add), used
  to prove the runtime + execution provider work — **not** a caption model.
  They are not comparable to the PyTorch row.
- On that tiny model DirectML (0.417 ms) is **slower** than ONNX CPU
  (0.035 ms). That is expected: GPU dispatch/marshalling overhead dominates
  a 32×32 op. A real caption model (millions of parameters) is where
  DirectML would win — but that model is not exported to ONNX yet
  (see docs/model-quality-report.md and docs/iteration-06.md).
- `peak_ram_mb` reads via `K32GetProcessMemoryInfo`; it is best-effort and
  may be null when unavailable. It is never fabricated.

## DirectML verification on the RX 580 (measured)

`test_backend onnx-directml`, over the real worker pipe:

```
Backend: onnx-directml
Execution provider: DmlExecutionProvider
Device: Radeon RX 580 Series      (Win32 EnumDisplayDevices, not invented)
Model loaded: Yes
Self-test: Passed                  (output matches the CPU reference)
Runtime: onnxruntime 1.24.4
```

The self-test creates a genuine `DmlExecutionProvider` session, runs
inference on the GPU, and verifies the numeric output against the known
reference — so this is a real GPU compute path, not a "provider is listed"
check.

## Scan timing (measured, PyTorch CPU)

- Cold app start incl. `--preload` model load: ~18–29 s (from app logs).
- Per image: ~7 s (dominated by BLIP generation).
- Short video (2 frames): ~10–18 s.
- Light commands (validate / plan / undo / thumbnail / list_backends):
  sub-second.

## Not measured this session (deferred)

- 100-image and 10-video batch runs on a packaged build.
- Peak VRAM (no reliable cross-vendor API wired yet).
- ONNX-CPU vs ONNX-DirectML on a **real caption model** — blocked on the
  ONNX export (documented limitation).
