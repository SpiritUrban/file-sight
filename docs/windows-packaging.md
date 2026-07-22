# FileSight — Windows packaging (iteration 6 status)

This documents the packaging **plan and current status**. In this session
the inference core with verified DirectML was delivered; the standalone
bundling is the next step and is honestly marked as not-yet-done.

## Current status

| Component | Status |
| --- | --- |
| Inference backend abstraction | Done, tested |
| ONNX Runtime CPU / DirectML backends | Done, verified on RX 580 |
| `onnxruntime-directml` install (Py 3.14) | Works (1.24.4) |
| Backend diagnostics / benchmark | Done |
| Report + UI backend metadata | Done |
| Bundled Python worker (PyInstaller) | **Not yet** |
| Bundled FFmpeg in installer | **Not yet** (auto-detected from folder, iter-5) |
| ONNX caption model pack | **Not yet** (see model-quality-report.md) |
| Offline NSIS installer | **Not yet** (dev/test installer exists from iter-5) |
| Clean-machine offline smoke test | **Not yet** |

The app still runs as in iteration 5 (external Python interpreter; FFmpeg
auto-detected from PATH / project folder / explicit path).

## Planned bundling (next step)

### Worker (PyInstaller, one-folder)

`scripts/build-worker.ps1` (to be added): clean venv → install
`requirements-worker.lock` → `pyinstaller` one-folder build of
`filesight.worker`. One-folder is preferred over one-file for an ML worker
(faster start, no giant temp extraction of onnxruntime/torch DLLs, fewer
antivirus false positives). Output:
`filesight-worker-x86_64-pc-windows-msvc/`.

Native DLLs to include explicitly: `onnxruntime*.dll`, `DirectML.dll`,
D3D12/DXGI (system), VC++ runtime, torch DLLs, Pillow, tokenizers native.
Each bundled native component's origin must be recorded here.

### FFmpeg

Ship a fixed, redistributable FFmpeg build (the gyan.dev essentials build
used in dev is LGPL/GPL — the exact license of the shipped build must be
verified before redistribution and its NOTICE included). Resolution order
in a bundled build: bundled → explicit user path (if allowed) → PATH.

### Model pack

`models/<model-id>/` with `model-manifest.json` (SHA-256 per file,
license, redistribution_checked), the ONNX graphs + tokenizer + configs.
Blocked on the ONNX caption export (see model-quality-report.md). Integrity
check: fast size check on normal start, full SHA-256 on first run / on
demand / after a load failure.

### Installer & WebView2

Tauri NSIS installer, per-user, settings/logs in AppData, reports/logs
preserved on uninstall. WebView2: choose bootstrapper vs fixed runtime;
for a truly offline installer, embed the fixed WebView2 runtime.

### Offline policy

`FILESIGHT_OFFLINE=1` forces `local_files_only=True` for the caption model
so a bundled build never reaches Hugging Face. Already implemented in
`inference/pytorch_cpu.py`.

## Build scripts (to be added)

`scripts/build-worker.ps1`, `scripts/package-model.ps1`,
`scripts/build-windows.ps1`, `scripts/verify-package.ps1`,
`scripts/smoke-test-windows.ps1` — with `verify-package.ps1` asserting no
`.venv`, `node_modules`, caches, test data, or absolute dev paths leak in.

## Dependency locks

`Cargo.lock` and `desktop/package-lock.json` are committed. A
`requirements-worker.lock` for the worker's Python deps will accompany the
PyInstaller build.
