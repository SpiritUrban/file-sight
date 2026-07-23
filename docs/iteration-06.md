# FileSight — ітерація 6

## Мета

Перетворити FileSight на автономний Windows-застосунок і додати апаратне
прискорення через ONNX Runtime + DirectML для AMD Radeon RX 580.

## Що фактично зроблено в цій сесії

Ітерація 6 — величезна (ONNX-експорт авторегресивної VLM, PyInstaller-бандл,
офлайн-інсталятор, тест на чистій машині). За узгодженням із користувачем ця
сесія зосереджена на **inference-ядрі з реально перевіреним DirectML**;
пакування та ONNX-captioning винесені в наступні кроки й **чесно позначені
як обмеження** нижче.

**Виконано і перевірено на реальному RX 580:**

- Абстракція `InferenceBackend` (protocol + діагностика).
- Три backend'и: `pytorch-cpu`, `onnx-cpu`, `onnx-directml`.
- Автовибір і політика fallback.
- **DirectML session реально створюється на RX 580, self-test проходить,
  назва пристрою читається чесно** (`Radeon RX 580 Series`).
- Backend diagnostics, benchmark.
- Worker-команди `test_backend`, `benchmark_backend`, `list_backends`.
- Метадані inference у корені звіту + подія `backend_detected`.
- UI: секція Inference у Settings (вибір backend, fallback, Test backend,
  Benchmark), індикатор DirectML у статус-барі, фактичний backend у футері звіту.
- `onnxruntime-directml==1.24.4` встановлюється на Python 3.14.

## Архітектура inference

```text
src/filesight/inference/
├─ base.py             InferenceBackend, CaptionResult, BackendDiagnostics,
│                      detect_gpu_name (Win32 EnumDisplayDevices)
├─ pytorch_cpu.py      PyTorchCpuBackend — BLIP (fallback / baseline)
├─ onnx_backends.py    OnnxCpu/DirectML/CUDA + session + caption cache
├─ onnx_caption.py     OnnxBlipCaptioner (hybrid vision GPU / decoder CPU)
├─ registry.py         make_backend, resolve_backend, test_backend,
│                      benchmark_backend, fallback policy
└─ captioner_adapter.py  BackendCaptioner → інтерфейс пайплайна
```

Backend IDs — стабільні й однозначні: `auto`, `onnx-directml`, `onnx-cpu`,
`pytorch-cpu`. Ніяких «gpu/fast/best».

## Чесність backend (ключове)

`resolve_backend` повертає об'єкт, яким **реально** captionить пайплайн
(`BackendCaptioner`), а не лише метадані для звіту. Раніше `cmd_scan`
записував `actual_backend` з selection, але передавав у
`process_media_files` preloaded PyTorch — звіт брехав. Це виправлено.

- Якщо pack `models/blip-onnx` (або `FILESIGHT_ONNX_MODEL_DIR`) на місці
  і DirectML доступний, `auto` → `onnx-directml` і captioning іде туди.
- Без pack `can_caption()` для ONNX = False; auto падає на `pytorch-cpu`
  із причиною в `considered` / `fallback_reason`.
- Hybrid: vision encoder на DirectML, decoder на CPU (Reshape у decoder
  графі відхиляє драйвер) — це відображається в `execution_provider`.

Приклад звіту з pack + RX 580:

```json
"inference": {
  "requested_backend": "auto",
  "actual_backend": "onnx-directml",
  "runtime": "onnxruntime",
  "execution_provider": "DmlExecutionProvider (vision) + CPUExecutionProvider (decoder)",
  "device_name": "Radeon RX 580 Series",
  "fallback_occurred": false,
  "directml_available": true
}
```

## DirectML: фактична конфігурація session

`onnxruntime-directml==1.24.4`, провайдер `DmlExecutionProvider`.

Параметри session (`onnx_backends.py`):

- `graph_optimization_level = ORT_ENABLE_ALL`;
- `execution_mode = ORT_SEQUENTIAL` (DirectML вимагає послідовного виконання);
- `enable_mem_pattern = False` для DirectML (True для CPU);
- `providers = ["DmlExecutionProvider"]`.

**Session reuse** — обов'язковий: один session на execution provider на весь
процес (`_SESSION_CACHE`). Створення *другого* DirectML session після
знищення першого **намертво вішає** D3D12-девайс під piped stdio worker'а
(діагностовано `faulthandler`). Кеш вирішує це і водночас виконує вимогу
«session reuse».

## Deadlock при завантаженні native DLL (розширення iteration-5)

Як і torch/transformers, **onnxruntime + DirectML (D3D12) native DLL не
можна завантажувати після старту piped-сесії** — Windows loader lock
вішається, поки reader-потік блокований на stdin. Тому `--preload` тепер
також прогріває ONNX Runtime (створює й закриває тестовий DML session) і
psapi. Наслідок: `test_backend`/`benchmark`/`scan` не вішаються.

## Self-test і benchmark

Self-test: вбудована крихітна ONNX-модель (32×32 MatMul+Add, base64 в
`onnx_backends.py`, без потреби в `onnx` при рантаймі). Створює session на
цільовому провайдері, запускає, звіряє результат, міряє час, читає пристрій.

`benchmark_backend`: cold-start + N прогонів (обмежено 1–50) + peak RAM.
Для pytorch-cpu міряє реальний BLIP-caption; для ONNX — self-test модель.
Це різні моделі — у docs/performance-report-windows.md вказано явно.

## Fallback policy

Setting `allow_fallback` (default `true`). Порядок auto:
`CUDA → DirectML → ONNX CPU → PyTorch CPU`. Якщо вибраний backend не може
captionити (немає pack / немає provider), з fallback → наступний
придатний; без fallback → `BACKEND_CANNOT_CAPTION`.

## Зміни JSON-схеми

`schema_version` → **1.4** (підтримуються 1.0–1.4). Додано корневий блок
`inference` (InferenceInfo) і опційне per-file `inference_backend` (для
mid-scan fallback). Старі звіти читаються.

## Worker protocol

Нові команди: `test_backend`, `benchmark_backend`, `list_backends`.
Нові події: `backend_detection_started`, `backend_detected`,
`benchmark_started`, `benchmark_completed`. Усі несуть `request_id`.
Команди роботи зі звітом і легкі команди не ініціалізують backend.

## Відомі обмеження (чесно)

1. **Captioning не на ONNX/DirectML.** BLIP — авторегресивна VLM; її
   експорт через `optimum` конфліктує зі стеком (тягне downgrade
   transformers 5.14→4.57 і plain `onnxruntime`, що конфліктує з
   `onnxruntime-directml`). Потрібен ізольований export-env + перевірка
   якості на 50+ зображеннях — окремий крок. Тому реальний scan наразі
   завжди `pytorch-cpu`; DirectML перевірено лише self-test/benchmark.
2. **Немає bundled Python / installer / clean-machine test** у цій сесії.
   Worker досі потребує встановленого Python (як в іт.5). PyInstaller-бандл,
   FFmpeg-bundle, model pack, offline installer, smoke test — наступний крок.
3. Self-test модель крихітна, тож DirectML на ній повільніший за CPU
   (dispatch overhead) — це очікувано й чесно показано в benchmark.

## Наступний рекомендований крок (продовження ітерації 6)

1. Ізольований `scripts/export-model-to-onnx.py` (окремий venv,
   optimum/ORTModelForVision2Seq), перевірка якості на reference dataset,
   model manifest + SHA-256.
2. Підключити ONNX-captioning до `OnnxDirectMlBackend.caption_images`;
   лише тоді `actual_backend: onnx-directml` з'явиться у звіті scan.
3. PyInstaller one-folder worker + bundled FFmpeg + model pack.
4. Tauri sidecar + offline NSIS installer + WebView2 стратегія.
5. Clean-machine offline smoke test.

## Критерії завершення (цієї сесії)

Inference-ядро з реально перевіреним DirectML на RX 580, чесним
репортингом, fallback, тестами (Python/React/Rust) — виконано. Пакувальні
критерії приймання свідомо відкладені й задокументовані як обмеження.
