# FileSight — прогрес

Останнє оновлення: 2026-07-21 (після реальної перевірки ітерації 5).

## Поточний стан

Ітерації 1–5 завершені. Крім CLI тепер є робоча desktop-версія для
Windows (Tauri 2 + React + TypeScript) — оболонка над незмінним
Python-ядром. Наскрізний сценарій
`scan → edit → save → validate → dry-run → rename → undo`
перевірено на реальних файлах із контролем SHA-256.

## Фактичний стек

| Компонент | Версія |
| --- | --- |
| Node.js / npm | 20.19.6 / 10.8.2 |
| Rust / cargo | 1.96.1 |
| Tauri | 2.11.5 (CLI 2) |
| React / Vite / TypeScript | 18.3 / 5.4 / 5.6 |
| Zustand / Zod | 5.0 / 3.23 |
| Python | 3.14.0 |
| torch / transformers | 2.13.0+cpu / 5.14.1 |
| FFmpeg | 8.1.2-essentials |
| MSVC Build Tools | 2022 |

## Тип інтеграції Python

**Варіант A** — один довгоживучий процес на сеанс, JSON Lines через
stdin/stdout, stderr тільки для логів. Rust володіє процесом; frontend
може надсилати лише команди з whitelist.

**Bundled Python: НІ.** Інсталятор містить лише GUI. Python 3.11+,
`pip install -e .` і FFmpeg встановлюються окремо; Environment Test
показує, чого бракує. Це свідоме обмеження ітерації.

## Реалізовані екрани та панелі

Один робочий екран: заголовок зі статусом середовища, тулбар
(папка/профіль/Images/Videos/Recursive/Max files/Frames), панель
прогресу, панель фільтрів і пошуку, таблиця результатів, панель деталей,
нижня панель дій. Діалоги: onboarding, Settings (+Test environment),
Validation, Dry run, Rename confirmation, Rename result, Undo.

## Реалізовані worker-команди

`ping`, `shutdown`, `cancel`, `scan`, `load_report`, `save_report`,
`validate_report`, `build_rename_plan`, `apply_rename`, `undo`,
`regenerate_names`, `get_profiles`, `get_config`, `get_environment`,
`make_thumbnail`. Модель завантажує лише scan (і `--preload` на старті).

## Результати тестів

| Набір | Результат |
| --- | --- |
| Python (pytest) | **361 passed** (з них 42 нових для worker) |
| Rust (cargo test) | **24 passed** |
| React (vitest) | **62 passed** (29 store + 33 UI) |

React-тести ганяють реальний store через mock worker: повний цикл,
скасування, редагування, inline-валідація, фільтри, діалоги, часткова
помилка, undo, доступність.

## Результат build

```text
desktop\src-tauri\target\release\filesight-desktop.exe        (9.3 МБ)
...\bundle\msi\FileSight_0.5.0_x64_en-US.msi
...\bundle\nsis\FileSight_0.5.0_x64-setup.exe
```

Production .exe запущено **без dev-сервера**: вікно «FileSight»
відкривається, worker стартує з автознайденого `.venv`, логи пишуться.

## Результат ручної перевірки

Наскрізний прогін реального worker'а (той самий протокол, що використовує
Tauri) на папці з 8 файлів (6 медіа + 2 пошкоджені):

- `get_environment`: Python 3.14.0 ok, ядро 0.5.0, модель cached.
- `scan`: 6 оброблено, 2 → failed, події started/phase/file_started/
  file_completed/progress/completed у правильному порядку.
- Модель завантажена рівно один раз (`ping.model_loaded=true` після).
- Ручне редагування назви + вимкнення одного файла.
- `save_report`: створив `filesight-report.backup-20260721-193342.json`.
- `validate_report`: valid, ready=5, skipped=3, errors=0.
- `build_rename_plan`: 5/3, **файли не змінені** (SHA-256 звірено).
- `apply_rename`: 5 перейменовано, набір SHA-256 незмінний.
- `undo` dry-run (5 операцій) → `undo`: **усі 8 файлів відновлено з
  ідентичними іменами та SHA-256**.
- Повторний `undo` → `already_undone`, без змін.
- Worker завершився з кодом 0; після закриття застосунку не лишилося ні
  python-, ні ffmpeg-процесів.

## Проблеми worker (знайдені й виправлені)

1. **Дедлок при завантаженні моделі.** Імпорт C-розширень
   torch/transformers **після** старту роботи з каналами намертво вішав
   процес усередині завантажувача numpy (0 CPU, >10 хв). Локалізовано
   через `faulthandler.dump_traceback_later` — стек показав
   `numpy/_core/multiarray.py → create_module`. Ізольовані тести
   довели, що ті самі імпорти на старті процесу працюють.
   **Виправлення:** прапорець `--preload` — модель готується до запуску
   циклу читання; Rust завжди його передає. Наслідок: старт застосунку
   ~20 с (видно в логах: «model ready in 19.2s»).
2. **Виконання команд перенесено на головний потік** (stdin читає
   допоміжний потік). Це правильніший напрямок для C-розширень; додано
   тест, що довгі команди не виконуються на потоці-читачі.
3. **Блокування на stderr.** Якщо не вичитувати stderr, буфер каналу
   переповнюється під час завантаження моделі й worker зависає. Rust
   вичитує stderr окремим потоком; те саме довелося зробити в тестовому
   harness.
4. **`get_environment` хибно повідомляв про відсутній ffmpeg**, коли не
   було ffprobe (перевіряв обидва інструменти замість одного). Виправлено
   + тест.

## Проблеми UI (знайдені й виправлені)

- Таблиця не перемальовувалася при зміні фільтра/пошуку: селектори
  `visibleEntries`/`entryErrors` стабільні, тому компонент не був
  підписаний на `filter`/`search`/`categoryFilter`. Знайдено трьома
  тестами, виправлено явними підписками + `useMemo`.

## Проблеми packaging

- Python не bundled (див. вище).
- `assetProtocol` вимагає cargo-фічу `protocol-asset` — інакше build
  падає на етапі `tauri::generate_context!`.
- Дозволу `core:asset:allow-read` у цій версії Tauri немає: scope
  задається у `tauri.conf.json` + `asset_protocol_scope()` у Rust.
- `frontendDist` має існувати до `cargo build` — спершу `npm run build`.

## Проблеми Windows (успадковані й нові)

- PowerShell `Set-Content -Encoding utf8` додає BOM; це зламало
  `pyproject.toml` (TOML не приймає BOM). Усі торкнуті файли перезаписано
  без BOM. Для Python-джерел BOM нешкідливий, для TOML — фатальний.
- `.venv\Scripts\python.exe` на цій машині породжує дочірній процес, тому
  Popen-pid ≠ pid, який рапортує worker (важливо при вимірюванні CPU).

## Реальна швидкість і пам'ять

- Старт застосунку (з preload моделі): **~20 с**.
- Зображення: ~0.2–18 с на файл (перше після старту швидке, далі
  залежить від розміру); відео з 2 кадрами: ~10–18 с.
- Наскрізний прогін 8 файлів: ~2 хв разом із preload.
- Worker (модель у пам'яті): ~700 МБ–1 ГБ RSS; GUI-процес ~60–90 МБ.
- Легкі команди (validate/plan/undo/thumbnail): миттєві.

## Відомі обмеження

- Python і модель не в інсталяторі.
- Старт ~20 с через обов'язковий preload (наслідок обходу дедлоку).
- Таблиця без віртуалізації (перевірено на 1000 записах).
- Немає відеоплеєра, темної теми, drag-and-drop, редактора TOML.
- Інтерактивне клікання по живому вікну не автоматизовано: GUI
  перевірено 62 React-тестами через mock worker + наскрізним прогоном
  справжнього worker'а і запуском production .exe.

## Наступний рекомендований крок (ітерація 6)

1. **Bundled Python sidecar** (embeddable Python + залежності) — прибере
   головне обмеження встановлення.
2. Усунути потребу в `--preload`: винести ML в окремий процес-виконавець,
   щоб старт GUI був миттєвим, а модель вантажилась на першому скані.
3. Віртуалізація таблиці для десятків тисяч файлів.
4. OCR (перенесено з ітерації 5) — наповнить `{text}`.
