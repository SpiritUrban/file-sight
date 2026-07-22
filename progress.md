# FileSight — прогрес

Останнє оновлення: 2026-07-22 (після ітерації 6, сесія «inference-ядро + DirectML»).

## Поточний стан

Ітерації 1–5 завершені. Ітерація 6 — **величезна** (bundled Python,
ONNX-captioning, offline installer, clean-machine test). За узгодженням із
користувачем ця сесія зробила **inference-ядро з реально перевіреним
DirectML на RX 580**; пакувальні критерії свідомо відкладені й чесно
позначені як обмеження (див. нижче та `docs/iteration-06.md`).

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

- Captioning-модель: **`Salesforce/blip-image-captioning-base`** (PyTorch CPU),
  **без змін**. ONNX-експорт відкладено (причина нижче).
- `onnxruntime-directml==1.24.4` (Python 3.14), провайдер `DmlExecutionProvider`.
- Session: `ORT_ENABLE_ALL`, `ORT_SEQUENTIAL`, `enable_mem_pattern=False` для DML.

## Версії (зафіксовано)

Python 3.14.0, torch 2.13.0+cpu, transformers 5.14.1, pillow 12.3.0,
onnxruntime-directml 1.24.4, Node 20.19.6, Rust 1.96.1, Tauri 2.11.5,
FFmpeg 8.1.2-essentials. App version → **0.6.0** (Python, Tauri, frontend,
Cargo синхронізовано).

## Результати тестів

| Набір | Результат |
| --- | --- |
| Python (pytest) | **401 passed, 1 skipped** (skip = тест DirectML-unavailable, бо DML доступний) |
| React (vitest) | **84 passed** |
| Rust (cargo test) | **26 passed** |

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

Чесно: pytorch-cpu — єдиний рядок із реальним captioning (~7 с/зображення).
ONNX-рядки міряють крихітну self-test модель (не captioning). На ній
DirectML повільніший за CPU (dispatch overhead) — очікувано; реальна
captioning-модель була б на користь GPU, але вона ще не в ONNX.

## Quality comparison

Немає PyTorch-vs-ONNX порівняння captions, бо ONNX caption-моделі ще немає.
Причина задокументована (`docs/model-quality-report.md`): експорт BLIP через
`optimum` тягне downgrade transformers 5.14→4.57 + plain onnxruntime, що
конфліктує з onnxruntime-directml. Потрібен ізольований export-env +
перевірка якості — окремий крок.

## Відомі обмеження (чесно)

1. **Captioning не на DirectML** — модель ще не експортована в ONNX; реальний
   scan завжди `actual_backend: pytorch-cpu`. DirectML перевірено лише
   self-test/benchmark. Це навмисно й чесно відображено в звіті/UI.
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
