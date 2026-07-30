# FileSight — Windows packaging

## Current status

| Component | Status |
| --- | --- |
| Inference backend abstraction | Done, tested |
| ONNX Runtime CPU / DirectML backends | Done, verified on RX 580 |
| `onnxruntime-directml` install (Py 3.14) | Works (1.24.4) |
| Backend diagnostics / benchmark | Done |
| Report + UI backend metadata | Done |
| **Bundled Python worker (PyInstaller)** | **Done, Windows** — `scripts/build-worker.py` |
| **Worker resolution in Rust** | **Done** — `src-tauri/src/worker_program.rs` |
| **Worker packaged into the installer** | **Done** — `tauri.windows.conf.json` |
| Bundled FFmpeg in installer | Not done, and not planned: one-click download in the app avoids redistributing GPL builds |
| ONNX caption model pack | **Not yet** (see model-quality-report.md) |
| Frozen worker for macOS / Linux | **Not yet** — PyInstaller cannot cross-compile |
| Clean-machine offline smoke test | **Not yet** |

On Windows the installer now carries the analysis core, so no Python is
needed. macOS and Linux builds still spawn an external interpreter.

## The worker bundle

`python scripts/build-worker.py` produces
`desktop/src-tauri/resources/filesight-worker/` (~615 MB, one folder), and
`tauri.windows.conf.json` maps it into the bundle as `filesight-worker`.

Choices worth keeping:

* **one-folder, not one-file.** A one-file build unpacks hundreds of
  megabytes of native libraries into temp on every start: slow, and a
  reliable antivirus false positive.
* **The model is not frozen in.** ~1 GB, versioned independently, and
  already downloaded on demand into the Hugging Face cache.
* **Do not exclude torch submodules.** `torch.distributed` was on the
  exclude list because "captioning never touches it"; `torch.utils.data.
  dataloader` imports it unconditionally, so transformers could not load any
  model at all. The symptom was `Could not import module 'BlipProcessor'` --
  a message naming a different package entirely. Trim the model, not torch.
* **Licence texts are moved, never dropped.** torch ships 107 licence files
  nested up to 144 characters deep, which breaks Windows' 260-character
  limit. The build flattens them into `third-party-licenses/` with an
  `INDEX.txt` recording each original path.

### Verification

`python scripts/verify-worker.py [--scan DIR]` speaks the real JSON-Lines
protocol over real pipes: ping, environment probe, a backend self-test, and
optionally a full scan. It exists because a frozen build that *links* is not
a frozen build that *works* -- and because an earlier version of this check
reported success while every caption path in the bundle was broken.

Note that without `--preload` the worker deadlocks on Windows by design: the
native runtimes cannot be imported once the reader thread is blocked in a
stdin read. `--preload` is the default here for that reason.

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
