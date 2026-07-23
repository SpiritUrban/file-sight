# FileSight — прогрес

Останнє оновлення: 2026-07-23 (підготовка NVIDIA/CUDA для GTX ПК).

## Поточний стан

Ітерації 1–5 завершені. Ітерація 6 — **величезна** (bundled Python,
ONNX-captioning, offline installer, clean-machine test). За узгодженням із
користувачем ця сесія зробила **inference-ядро з реально перевіреним
DirectML на RX 580**; пакувальні критерії свідомо відкладені й чесно
позначені як обмеження (див. нижче та `docs/iteration-06.md`).

## Що зроблено (ітерація 6, сесія 2 — три бекенди + автовибір)

- Доданий **`onnx-cuda` (NVIDIA)** — четвертий бекенд поряд із
  `onnx-directml`, `onnx-cpu`, `pytorch-cpu`.
- **Справжній пріоритетний автовибір** (`select_auto_backend`):
  CUDA → DirectML → ONNX CPU → PyTorch CPU. Раніше `auto` був жорстко
  зашитий на `pytorch-cpu`; тепер це результат обходу пріоритету.
- Введено **`can_caption()`** окремо від `is_available()`. Автовибір бере
  лише той бекенд, який *і доступний, і вміє робити підписи*, тому він
  фізично не може обрати пристрій, що потім перекине роботу на інший.
- Кожен кандидат потрапляє у звіт (`considered`) із причиною, чому його
  взяли або пропустили — UI не здогадується, а читає.
- `detect_gpu_name(vendor)` із фільтром вендора: **CUDA-бекенд ніколи не
  підписується чужою відеокартою** (RX 580 не стане «CUDA device»).
- UI: п'ять варіантів у Settings (Auto / NVIDIA / AMD-Intel / CPU ONNX /
  CPU PyTorch), у статус-барі пілюля **GPU** називає наявний прискорювач
  і API, який ним керує.
- Benchmark для `auto` більше не зашитий на DirectML — бере найкращий
  наявний прискорювач.

**Оновлено:** ONNX pack у `models/blip-onnx` + wiring у `cmd_scan` /
CLI. `can_caption()` True коли pack знайдено; `auto` на RX 580 →
`onnx-directml`. Раніше звіт міг писати DirectML, а пайплайн ішов через
preloaded PyTorch — виправлено (`BackendCaptioner(selection)`).

**NVIDIA не перевірена на залізі** — тут RX 580. Код і автовизначення
написані, `is_available()` чесно повертає False, `test_backend` каже
«CUDAExecutionProvider is not available». Статус: *написано, не
підтверджено на реальному NVIDIA GPU*.

## Що зроблено (ітерація 6, сесія 1)

- Абстракція `InferenceBackend` (`src/filesight/inference/`): base, registry,
  pytorch_cpu, onnx_backends, captioner_adapter.
- Backend IDs: `auto`, `onnx-directml`, `onnx-cpu`, `pytorch-cpu`.
- Автовибір + fallback policy (`allow_fallback`); вимкнений fallback → чітка
  помилка, без тихого CPU.
- **DirectML session реально створюється на RX 580, self-test проходить,
  device_name читається чесно** (`Radeon RX 580 Series` через Win32).
- Session reuse (кеш per-provider) — обов'язковий: другий DirectML session
  вішає D3D12 під piped stdio.
- `--preload` розширено: прогріває ONNX Runtime + DirectML DLL і psapi перед
  reader-потоком (той самий loader-lock deadlock, що й torch в іт.5).
- Worker-команди `test_backend`, `benchmark_backend`, `list_backends`; події
  `backend_detection_started/detected`, `benchmark_started/completed`.
- Звіт: корневий блок `inference` (schema 1.4) + per-file `inference_backend`.
- UI: Settings → Inference (backend, fallback, Test backend, Benchmark),
  індикатор DirectML у статус-барі, фактичний backend у футері.

## Фактична модель і backend

- Captioning: ONNX BLIP pack (vision на DirectML / CUDA / CPU, decoder на
  CPU для DirectML) або fallback **PyTorch** `Salesforce/blip-image-captioning-base`.
- `onnxruntime-directml==1.24.4` (Python 3.14), провайдер `DmlExecutionProvider`.
- Session: `ORT_ENABLE_ALL`, `ORT_SEQUENTIAL`, `enable_mem_pattern=False` для DML.
- `cmd_scan` / CLI `scan --backend` використовують той самий backend, що
  потрапляє в `report.inference.actual_backend`.

## Версії (зафіксовано)

Python 3.14.0, torch 2.13.0+cpu, transformers 5.14.1, pillow 12.3.0,
onnxruntime-directml 1.24.4, Node 20.19.6, Rust 1.96.1, Tauri 2.11.5,
FFmpeg 8.1.2-essentials. App version → **0.6.0** (Python, Tauri, frontend,
Cargo синхронізовано).

## Результати тестів

| Набір | Результат |
| --- | --- |
| Python (pytest) | **424 passed, 6 skipped** (skip'и = умовні GPU/CUDA/model-pack тести — жоден не є прихованим провалом) |
| React (vitest) | **85 passed** |
| Rust (cargo test) | **27 passed** |

Нове: `tests/test_inference.py` (реєстр, вибір, fallback, self-test,
benchmark, session reuse — DirectML-тести skip'аються без GPU), worker-тести
на нові команди + inference-метадані, React-тести на Settings/Inference,
Rust-тест на persist backend-настройок.

## RX 580 benchmark (виміряно)

`benchmark_backend`, 5 прогонів:

| Backend | Provider | Cold | Avg/run | Модель |
| --- | --- | --- | --- | --- |
| pytorch-cpu | CPU | 9216 ms | **7146 ms** | реальний BLIP caption |
| onnx-cpu | CPUExecutionProvider | 68 ms | 0.035 ms | self-test 32×32 |
| onnx-directml | DmlExecutionProvider | 283 ms | 0.417 ms | self-test 32×32 |

Примітка: таблиця вище — self-test 32×32 vs повний BLIP на PyTorch; це
різні моделі. Реальний ONNX BLIP caption (hybrid DML vision + CPU decoder)
виміряно в `docs/onnx-export.md` (~1.7–2.1 s/image pure inference; full
scan ~12 s/file через non-inference overhead).

## Quality comparison

Немає PyTorch-vs-ONNX порівняння captions, бо ONNX caption-моделі ще немає.
Причина задокументована (`docs/model-quality-report.md`): експорт BLIP через
`optimum` тягне downgrade transformers 5.14→4.57 + plain onnxruntime, що
конфліктує з onnxruntime-directml. Потрібен ізольований export-env +
перевірка якості — окремий крок.

## Відомі обмеження (чесно)

1. **Captioning не на GPU** — модель ще не експортована в ONNX; реальний
   scan завжди `actual_backend: pytorch-cpu`, хоч би який бекенд обрали.
   DirectML перевірено лише self-test/benchmark. Це навмисно й чесно
   відображено в звіті (`considered`, `fallback_reason`) та UI.
1a. **NVIDIA/CUDA підготовлено до GTX-ПК** (код + docs), на AMD-машині
   не перевірено на залізі. Decoder на CUDA (не hybrid); setup:
   `docs/nvidia-setup.md`, `scripts/setup_nvidia.ps1`, extra `.[cuda]`.
   Не вважати робочою, поки не буде запуску на реальній NVIDIA.
2. **Немає bundled Python / offline installer / clean-machine smoke test** у
   цій сесії — worker досі потребує встановленого Python (як в іт.5).
   PyInstaller-бандл, model pack, offline NSIS — наступний крок
   (`docs/windows-packaging.md`).
3. Antivirus/clean-machine/offline тести не проводились цієї сесії.

## Відомі проблеми, знайдені й виправлені

- Другий DirectML session вішає D3D12 під piped stdio → session reuse cache.
- onnxruntime/DirectML native DLL не можна вантажити після старту piped-сесії
  → `--preload` прогріває їх.
- `benchmark` термінальна подія — `benchmark_completed`, не `completed`;
  worker-клієнт і test-harness оновлені.

## Наступний рекомендований крок

Продовження ітерації 6: (1) ізольований `export-model-to-onnx.py` +
перевірка якості; (2) підключити ONNX-captioning до `OnnxDirectMlBackend`;
(3) PyInstaller one-folder worker + bundled FFmpeg + model pack; (4) offline
NSIS installer + WebView2; (5) clean-machine offline smoke test.
