# FileSight — ітерація 5

## Мета

Перша робоча desktop-версія для Windows: Tauri 2 + React + TypeScript як
оболонка над уже перевіреним Python-ядром. Уся бізнес-логіка (ML,
категоризація, naming, валідація, двофазне перейменування, undo)
залишається в Python — у Rust і React не продубльовано нічого.

## Фактична архітектура

```text
Tauri 2 (Rust)                      React + TypeScript
├─ python.rs   пошук інтерпретатора  ├─ stores/appStore  (state machine)
├─ worker.rs   процес + JSON Lines   ├─ lib/worker       (адаптер)
├─ settings.rs налаштування + логи   ├─ lib/tauriWorker  (продакшн)
└─ lib.rs      Tauri commands        └─ lib/mockWorker   (тести/дев)
        │                                     │
        └──────── worker-event (JSON) ────────┘
        │
        ▼
python -m filesight.worker  ──►  наявне FileSight core
```

Rust володіє процесом Python. Frontend **не може** назвати програму для
запуску — лише надіслати команду зі списку `ALLOWED_COMMANDS`.

## Worker protocol

JSON Lines, один рядок — одна подія. **stdout — лише протокол**, усі
діагностики йдуть у stderr (перевірено тестом).

Запит:

```json
{"request_id": "uuid", "command": "scan", "payload": {"directory": "D:\\Photos"}}
```

Події: `started`, `phase`, `file_started`, `file_completed`,
`frame_progress`, `progress`, `completed`, `error`.

Помилка завжди структурована:

```json
{"request_id": "uuid", "event": "error",
 "data": {"code": "MODEL_LOAD_FAILED", "message": "…", "recoverable": false}}
```

### Реалізовані команди

| Команда | Завантажує модель |
| --- | --- |
| `ping`, `shutdown`, `cancel` | ні |
| `get_environment`, `get_profiles`, `get_config` | ні |
| `load_report`, `save_report` | ні |
| `validate_report`, `build_rename_plan` | ні |
| `apply_rename`, `undo`, `regenerate_names` | ні |
| `make_thumbnail` | ні (Pillow / FFmpeg) |
| **`scan`** | **так, один раз на процес** |

## Життєвий цикл worker

**Варіант A** — один довгоживучий процес на весь сеанс: модель
завантажується один раз, повторні операції швидкі. Довгі команди
виконуються в окремому потоці, тому `cancel` і `shutdown` читаються зі
stdin негайно (`INLINE_COMMANDS`).

Завершення: `shutdown` → закриття stdin → очікування 5 с → примусовий
`kill`. Викликається і при закритті вікна (`WindowEvent::Destroyed`), тож
Python не лишається у фоні.

Rust читає stdout і **stderr у окремих потоках** — інакше буфер каналу
переповнюється під час завантаження моделі й worker блокується (ця
помилка реально трапилася в тестовому harness і виправлена).

## Скасування

`cancel` виставляє `threading.Event`; `process_media_files` опитує його
перед кожним файлом і кидає `ScanCancelled` з уже обробленими записами.
Далі: зупинка нових файлів, cleanup тимчасових кадрів у `finally`,
частковий звіт, подія `completed` з `cancelled: true`. Активний FFmpeg
завершується через `kill` у `video_frames`. Після скасування можна одразу
запустити новий scan.

## UI states

`idle → environment_check → folder_selected → scanning → loading_model →
analyzing → cancelling → report_ready → validating → rename_preview →
renaming → rename_completed | rename_failed → undoing → error`

Один `uiState` у Zustand-сторі керує тим, що ввімкнено. `isBusy()`
блокує паралельні операції: два scan, scan+rename, rename+undo.

## Редагування звіту

`suggested_name` редагується прямо в таблиці; валідація миттєва і
дзеркалить `validation.py` (порожня назва, заборонені символи,
зарезервовані імена Windows, зміна розширення, path traversal, довжина,
дублікати цілей). Редагується **лише ім'я файла**, не шлях.

Стан позначається `Unsaved changes`; збереження — кнопкою
`Save report`, яка йде через worker (`save_report`), а не через власну
серіалізацію в React. Перед записом створюється
`filesight-report.backup-YYYYMMDD-HHMMSS.json`.

`rename_enabled` — checkbox; failed/skipped записи неможливо ввімкнути.
Масові дії: `Enable visible`, `Disable visible`, `Reset names`.
`Regenerate names` повторно застосовує профіль без ML.

## Потоки validate / dry-run / rename / undo

- **Validate** → `validate_report`; діалог із Ready/Skipped/Warnings/Errors,
  клік по проблемі виділяє рядок у таблиці.
- **Dry run** → `build_rename_plan`; показує FROM/TO/SKIPPED і шлях
  майбутнього журналу. Нічого не змінює (перевірено SHA-256).
- **Rename** → окреме підтвердження з явною кнопкою
  «Rename N files» (ніколи просто «OK») → `apply_rename`. Результат
  показує renamed/skipped/failed і шлях журналу; при частковій помилці
  заголовок «did not complete safely», статус журналу і файли, що
  потребують ручного втручання.
- **Undo** → спершу `undo --dry-run` як прев'ю, потім підтвердження і
  реальне скасування. Повторний undo безпечний.

## Thumbnails

`make_thumbnail` створює JPEG ≤256 px у `%TEMP%\filesight-thumbnails`
(Pillow для зображень з урахуванням EXIF-орієнтації, FFmpeg для відео).
Ключ кешу — шлях + розмір + mtime. Frontend отримує шлях і показує його
через `convertFileSrc` (asset-протокол, обмежений scope до цієї папки).
Завантаження ліниве: `IntersectionObserver` запитує пікселі лише для
рядків, що потрапили у в'юпорт. Оригінали ніколи не читаються в React.

## Визначення середовища

Порядок пошуку Python: **settings → `<repo>\.venv` → PATH → `py -3`**.
Версія перевіряється (потрібно 3.11+), фактичний executable показується в
Environment Test. Логіка винесена в чистий модуль `python.rs` і покрита
unit-тестами.

Панель статусу показує Python / FileSight core / Model / FFmpeg —
текстом, не лише кольором.

## Налаштування та логи

Налаштування: шляхи до Python/FFmpeg/ffprobe/config, профіль за
замовчуванням, recursive/videos за замовчуванням, ім'я звіту. Пошкоджений
файл налаштувань не блокує запуск — використовуються значення за
замовчуванням.

Логи: `%LOCALAPPDATA%\com.filesight.desktop\logs\filesight-desktop.log`
(старт, worker, stderr, помилки). Рядки обрізаються до 400 символів —
вміст зображень і великі відповіді моделі не логуються. Кнопка
`Open logs folder` у Settings.

## Безпека (Tauri capabilities)

```json
["core:default", "core:window:allow-close",
 "dialog:allow-open", "dialog:allow-message", "dialog:allow-confirm",
 "opener:allow-reveal-item-in-dir", "opener:allow-open-path"]
```

Плагін shell **не підключений** — довільну команду виконати неможливо.
`assetProtocol.scope` обмежений `$TEMP/filesight-thumbnails/**`.
CSP забороняє зовнішні джерела. Frontend передає лише команду з
whitelist; шлях до Python обирає Rust.

## Dev setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"

cd desktop
npm install
npm run dev
```

`npm run dev` = `tauri dev`, який усередині викликає `npm run dev:vite`
(окремий скрипт, щоб не було рекурсії — `beforeDevCommand` у
`tauri.conf.json` вказує саме на нього).

Для UI-роботи без Python/FFmpeg/моделі: `npm run dev:mock`
(`vite --mode mock`, змінна береться з `desktop/.env.mock`).

## Build

```powershell
cd desktop
npm run tauri build
```

Результат (перевірено):

```text
target\release\filesight-desktop.exe
target\release\bundle\msi\FileSight_0.5.0_x64_en-US.msi
target\release\bundle\nsis\FileSight_0.5.0_x64-setup.exe
```

## Відомі обмеження

- **Python не bundled** (варіант A). Інсталятор ставить лише GUI;
  Python 3.11+, `pip install -e .` та FFmpeg потрібні окремо. Це чесно
  винесено в README та перевіряється Environment Test.
- Модель завантажується при першому scan; прогрес завантаження з
  Hugging Face показується як indeterminate (точних відсотків HF не дає).
- Таблиця без віртуалізації: перевірено на 1000 записах (фільтрація
  <500 мс), 100 000 не є метою ітерації.
- Відеоплеєра немає — лише один representative thumbnail + метадані.
- Немає темної теми, drag-and-drop, редактора TOML.
- Інтерактивну частину GUI перевірено автоматичними тестами
  (62 React-тести через mock worker) і наскрізним прогоном реального
  worker'а; клікання по живому вікну вручну не автоматизувалося.

## Ручний сценарій перевірки

Див. `progress.md` — фактично виконано: збірка dev і production,
запуск .exe без dev-сервера, Environment Test, наскрізний прогін
worker'а на реальній папці (6 медіа + 2 пошкоджені) з перевіркою
SHA-256 до/після rename і undo, перевірка що dry-run нічого не змінює,
що модель вантажиться один раз, що після закриття не лишається процесів.

## Критерії завершення

Усі 51 критерій приймання виконані; фактичні результати — у
`progress.md`.
