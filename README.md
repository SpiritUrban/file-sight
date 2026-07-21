# FileSight

FileSight — локальна консольна програма, яка аналізує вміст зображень за
допомогою vision-моделі, пропонує зрозумілі назви файлів і вміє **безпечно
застосовувати** ці назви з журналом та скасуванням.

Головний принцип: **без явного `--apply` жоден файл не змінюється**, а
сторонні файли ніколи не перезаписуються.

## Можливості

**Ітерація 5 (desktop UI):**

- Windows-застосунок на Tauri 2 + React: вибір папки, аналіз із прогресом,
  таблиця результатів із прев'ю, редагування назв, validate, dry-run,
  перейменування та undo — усе з графічного інтерфейсу.
- Уся логіка залишається в Python-ядрі; GUI спілкується з ним через
  структурований JSON-Lines протокол (не парсить текст CLI).
- Див. розділ [Desktop-застосунок](#desktop-застосунок).

**Ітерація 1 (scan):**

- Сканування папки з зображеннями (`.jpg`, `.jpeg`, `.png`, `.webp`, без урахування регістру).
- Локальний image captioning на CPU (модель `Salesforce/blip-image-captioning-base`).
- Генерація безпечної запропонованої назви (lowercase, дефіси, без заборонених символів Windows).
- JSON-звіт у UTF-8; пошкоджений файл не зупиняє обробку інших.

**Ітерація 2 (validate / rename / undo):**

- `validate` — перевірка звіту перед перейменуванням (конфлікти, відсутні
  файли, заборонені й зарезервовані назви, зміна розширення тощо).
- `rename` — перейменування за звітом: dry-run за замовчуванням, двофазний
  алгоритм (підтримує обмін назвами, цикли та зміну лише регістру на
  Windows), журнал відкату, контрольований rollback при помилці.
- `undo` — скасування останньої операції за журналом, теж із dry-run.
- Команди роботи зі звітом запускаються миттєво і не завантажують нейромережу.

**Ітерація 4 (профілі, категорії, шаблони):**

- Конфігурація `filesight.toml`: профілі іменування, користувацькі категорії.
- Шаблони назв (`{date}-{category}-{subject}-{action}` тощо) замість
  прямого перетворення caption у назву.
- Автоматична категоризація за правилами (17 стандартних категорій).
- Дата зйомки з EXIF / метаданих відео + `date_source` у звіті.
- Українські назви й офіційна транслітерація (КМУ-2010).
- Команди `config`, `naming preview`, `category explain`,
  `report rename-suggestions` — усі працюють без завантаження моделі.

**Ітерація 3 (короткі відео):**

- Аналіз коротких відео (`.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.m4v`)
  через кілька вибраних кадрів (за замовчуванням 6) — потрібен FFmpeg.
- Метадані через ffprobe, витяг кадрів через FFmpeg у тимчасову папку,
  відсів чорних/білих/дубльованих кадрів, агрегація описів в один caption.
- Відео потрапляє в той самий звіт і перейменовується/скасовується тими
  самими `validate` / `rename` / `undo` (без перекодування, вміст незмінний).
- Аналіз відео вимкнено за замовчуванням — вмикається `--include-videos`.

## Desktop-застосунок

Графічний інтерфейс для Windows (Tauri 2 + React). Ядро аналізу
залишається на Python — GUI лише керує ним.

### Поточний статус

Робоча перша версія. **Python не входить до інсталятора**: застосунок
очікує встановлений Python 3.11+ з `pip install -e .` (і FFmpeg, якщо
потрібні відео). Вбудована перевірка `Test environment` показує, чого
бракує.

### Системні вимоги для розробки

| Компонент | Версія |
| --- | --- |
| Node.js | 20+ |
| Rust | 1.77+ (перевірено 1.96) |
| MSVC Build Tools | 2022 (C++ workload) |
| WebView2 Runtime | є у Windows 11 |
| Python | 3.11+ |
| FFmpeg | лише для відео |

### Запуск у режимі розробки

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"

cd desktop
npm install
npm run dev
```

`npm run dev` збирає фронтенд і **запускає сам застосунок** (Tauri).
Перша збірка Rust займає кілька хвилин, далі — секунди.

Для роботи над інтерфейсом без Python, FFmpeg і моделі (дані підставляє
вбудований mock worker, відкривається у браузері):

```powershell
cd desktop
npm run dev:mock
```

| Скрипт | Що робить |
| --- | --- |
| `npm run dev` | запускає desktop-застосунок |
| `npm run dev:mock` | лише UI у браузері на фейкових даних |
| `npm run dev:vite` | лише Vite (використовується Tauri всередині) |
| `npm test` | React-тести |
| `npm run tauri build` | збірка інсталяторів |

### Збірка для Windows

```powershell
cd desktop
npm run tauri build
```

Результат:

```text
desktop\src-tauri\target\release\filesight-desktop.exe
desktop\src-tauri\target\release\bundle\msi\FileSight_0.5.0_x64_en-US.msi
desktop\src-tauri\target\release\bundle\nsis\FileSight_0.5.0_x64-setup.exe
```

Це інсталятор **лише для GUI** — Python, залежності й модель
встановлюються окремо.

### Як користуватися

1. **Environment test** — Settings → `Test environment`: перевіряє Python,
   ядро FileSight, FFmpeg, ffprobe, кеш моделі та конфігурацію.
2. **Choose folder** — нативний діалог; аналіз не стартує сам.
3. **Start analysis** — прогрес, поточний файл, кількість успішних і
   помилок; `Cancel` зупиняє й лишає частковий результат.
4. **Таблиця** — прев'ю, стара й запропонована назва, категорія, статус.
   Назву можна редагувати прямо в таблиці (перевірка миттєва), окремий
   файл вимикається чекбоксом.
5. **Save report** — записує зміни через ядро й створює резервну копію
   `filesight-report.backup-YYYYMMDD-HHMMSS.json`.
6. **Validate** → **Dry run** → **Rename files** (окреме підтвердження) →
   **Undo last rename**.

### Логи

`%LOCALAPPDATA%\com.filesight.desktop\logs\filesight-desktop.log`
(кнопка `Open logs folder` у Settings). Вміст зображень і великі
відповіді моделі не логуються.

### Обмеження desktop-версії

- Python і модель **не** входять до інсталятора (варіант із зовнішнім
  Python). Це задокументовано і перевіряється Environment Test.
- Worker завантажує модель одразу при старті (прапорець `--preload`):
  на Windows імпорт C-розширень torch/transformers *після* початку
  роботи з каналами призводить до зависання, тому модель готується
  наперед. Через це запуск застосунку займає ~20 с.
- Таблиця без віртуалізації — перевірено на 1000 записах.
- Відеоплеєра немає, лише кадр-прев'ю та метадані.
- Немає темної теми й drag-and-drop.

### Помилки середовища

| Повідомлення | Що робити |
| --- | --- |
| `Python: Not found` | встановіть Python 3.11+ або вкажіть шлях у Settings |
| `FileSight core: Missing` | у тому ж Python виконайте `pip install -e .` |
| `FFmpeg: Not found` | встановіть FFmpeg або вкажіть шлях у Settings |
| `Model: Not downloaded` | перший аналіз завантажить модель (потрібен інтернет) |

## Робочий процес (CLI)

```powershell
filesight scan "D:\Photos"
filesight validate "D:\Photos\filesight-report.json"
filesight rename "D:\Photos\filesight-report.json"            # dry-run: тільки план
filesight rename "D:\Photos\filesight-report.json" --apply    # реальне перейменування
filesight undo "D:\Photos\filesight-rename-log-20260721-183000.json" --apply
```

## Встановлення (Windows PowerShell)

Потрібен Python 3.11+ (<https://www.python.org/downloads/>, позначте
"Add python.exe to PATH").

```powershell
git clone https://github.com/your-user/file-sight.git
cd file-sight
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
```

> Рядок з `--index-url` ставить CPU-версію PyTorch (менша за CUDA-збірку).
> GPU і CUDA не потрібні. При першому `scan` модель (~1 ГБ) завантажується
> й кешується у `%USERPROFILE%\.cache\huggingface`; далі все працює офлайн.

## Команда scan

```powershell
filesight scan "D:\Photos" --max-files 10
```

| Параметр | За замовчуванням | Опис |
| --- | --- | --- |
| `PATH` | — | папка з зображеннями |
| `--recursive` | вимкнено | сканувати вкладені папки |
| `--output` | `filesight-report.json` у `PATH` | шлях до JSON-звіту |
| `--max-files` | без обмеження | обмежити кількість файлів |
| `--language` | `en` | `en` або `uk` (uk — експериментально) |
| `--overwrite-report` | вимкнено | дозволити перезапис звіту |

`scan` нічого не перейменовує — лише створює звіт.

## Іменування: профілі, категорії, шаблони (ітерація 4)

Назва будується не напряму з опису, а через керований шар:

```text
caption → features (subject/action/location) → категорія → шаблон → назва
```

### Швидкий старт

```powershell
filesight config init --profile photos --output ".\filesight.toml"
filesight config validate ".\filesight.toml"
filesight config show ".\filesight.toml"
filesight scan "D:\Photos" --config ".\filesight.toml"
```

Без конфігурації все працює як раніше (вбудований профіль `default`).

### Вбудовані профілі

| Профіль | Шаблон |
| --- | --- |
| `default` | `{subject}-{action}-{location}` (як в ітераціях 1–3) |
| `photos` | `{date}-{category}-{subject}-{location}` |
| `compact` | `{subject}-{action}` |
| `archive` | `{date}-{media_type}-{category}-{subject}-{index}` |
| `screenshots` | `{date}-{category}-{text}` |

```powershell
filesight scan "D:\Photos" --profile compact
filesight scan "D:\Photos" --profile photos --template "{date}-{subject}-{index}"
```

Пріоритет: **CLI → вибраний профіль → default_profile → вбудований**.

### Змінні шаблону

```text
{subject} {action} {location} {objects} {text} {category} {media_type}
{date} {time} {year} {month} {day} {original_stem} {index} {caption}
{width} {height} {duration}
```

Сегмент із порожнім значенням **зникає разом із роздільником**:
якщо немає `action`, `{date}-{category}-{subject}-{action}` дасть
`2026-07-21-animals-black-dog`, а не `...-black-dog-`.
Назва ніколи не буває порожньою: резервний варіант — `{category}-{index}`,
далі `media-{index}`.

### Структура filesight.toml

```toml
config_version = "1.0"
default_profile = "photos"

[profiles.photos]
template = "{date}-{category}-{subject}-{location}"
language = "en"                # en | uk
separator = "-"                # - | _ | (пробіл)
case_style = "lower"           # lower | upper | title | preserve
transliterate = false
max_filename_length = 100      # 20..240, разом із розширенням
max_objects = 3
max_caption_words = 8
date_format = "%Y-%m-%d"
time_format = "%H-%M-%S"
index_start = 1
index_padding = 3              # 001, 002, ...
index_scope = "global"         # global | category | directory
clean_original_stem = true     # відкидає IMG_1234, DSC_0001, VID_2026...

[categories.receipts]
enabled = true
priority = 150
keywords_any = ["receipt", "invoice", "total"]
filename_contains = ["scan"]
extensions = [".jpg", ".png"]
media_types = ["image"]
min_matches = 1
```

Профіль із іменем вбудованого перевизначає його частково: незадані поля
успадковуються. Повний приклад — `examples/filesight.example.toml`.

### Категорії

Стандартні: `people animals nature food vehicles documents screenshots
code products buildings travel sports events art memes medical other`.

Користувацькі категорії додаються в `[categories.*]`; стандартну можна
вимкнути через `enabled = false`.

Переможець обирається детерміновано:

1. більша кількість збігів;
2. вищий `priority`;
3. категорія, визначена раніше;
4. інакше — `other`.

**Confidence** — це rule-based оцінка, а не ймовірність моделі:
1 збіг → 0.55, 2 → 0.70, 3 → 0.82, 4+ → 0.92.

```powershell
filesight category explain --caption "A woman standing near a red car"
```

### Мова та транслітерація

```powershell
filesight naming preview --caption "A black dog running through snow" `
  --template "{category}-{subject}-{action}" --language uk
# тварини-чорний-пес-біжить.jpg

filesight naming preview --caption "A black dog running through snow" `
  --template "{category}-{subject}-{action}" --language uk --transliterate
# tvaryny-chornyi-pes-bizhyt.jpg
```

Українська працює через вбудований словник (~150 слів); невідомі слова
лишаються англійськими. Транслітерація — офіційна КМУ-2010.

### Дата зйомки

`{date}` береться за ланцюжком: для фото — EXIF `DateTimeOriginal` →
`DateTimeDigitized` → `DateTime` → створення файла → зміна файла; для
відео — `creation_time` контейнера → створення → зміна. У звіті
зберігаються `captured_at` і `date_source`. Явно некоректні дати
(1970-01-01, далеке майбутнє) відкидаються з попередженням.

### Перевірка назв без сканування

```powershell
filesight naming preview --caption "A black dog running through snow near trees" `
  --profile photos --date "2026-01-14"
```

Не завантажує модель і не відкриває файли.

### Повторна генерація назв зі звіту

Змінити правила без повторного аналізу зображень:

```powershell
filesight report rename-suggestions "D:\Photos\filesight-report.json" `
  --config ".\new-rules.toml" --profile archive `
  --output "D:\Photos\filesight-report-archive.json"
```

`--dry-run` показує `OLD:` / `NEW:` і нічого не пише. Вихідний звіт не
перезаписується без `--overwrite`. Модель не завантажується (~0.5 с).

### Сумісність

Старі звіти (schema 1.0–1.2) читаються; відсутній `media_type`
трактується як `image`. `rename` і `undo` не змінилися й **не потребують
конфігурації** — вони беруть верхньорівневий `suggested_name`, який можна
редагувати вручну. Звіт самодостатній.

## Відео (ітерація 3)

FileSight може аналізувати короткі відео, витягуючи кілька кадрів і
описуючи їх тією самою моделлю. **Аналізується не весь відеоряд, а кілька
репрезентативних кадрів** (за замовчуванням 6). Аудіо не аналізується,
транскрипції немає, відео не перекодовується.

### FFmpeg (обов'язково для відео)

Для зображень FFmpeg не потрібен. Для відео потрібні `ffmpeg` і `ffprobe`.

Встановлення на Windows (один зі способів):

```powershell
winget install Gyan.FFmpeg
# або Chocolatey:
choco install ffmpeg
```

Або завантажити збірку з <https://www.gyan.dev/ffmpeg/builds/>, розпакувати
й додати папку `bin` до PATH. Перевірка:

```powershell
ffmpeg -version
ffprobe -version
```

Якщо FFmpeg не в PATH, передайте явні шляхи:

```powershell
filesight scan "D:\Media" --videos-only `
  --ffmpeg-path "C:\ffmpeg\bin\ffmpeg.exe" `
  --ffprobe-path "C:\ffmpeg\bin\ffprobe.exe"
```

### Параметри відео

| Параметр | За замовчуванням | Опис |
| --- | --- | --- |
| `--include-videos` | вимкнено | зображення + відео |
| `--images-only` | — | лише зображення (типова поведінка, явно) |
| `--videos-only` | — | лише відео |
| `--video-frames N` | 6 | кадрів на відео (1–20) |
| `--max-video-duration SEC` | 120 | пропускати відео, довші за SEC секунд |
| `--allow-long-videos` | вимкнено | аналізувати й довші відео |
| `--ffmpeg-path PATH` | з PATH | явний шлях до ffmpeg |
| `--ffprobe-path PATH` | з PATH | явний шлях до ffprobe |
| `--verbose` | вимкнено | діагностика (шляхи, exit code, timings) |

`--images-only` разом із `--videos-only` (або `--include-videos`) — помилка
(exit 2). Підтримувані формати: `.mp4 .mov .mkv .webm .avi .m4v`
(без урахування регістру).

### Приклади

```powershell
filesight scan "D:\Media" --include-videos
```

```powershell
filesight scan "D:\Media" --videos-only --video-frames 8
```

```powershell
filesight scan "D:\Media" `
  --include-videos `
  --max-video-duration 180 `
  --video-frames 8
```

Далі відео перевіряються, перейменовуються і скасовуються тими самими
`validate`, `rename` і `undo`, що й зображення — окремих команд для відео
немає.

### Час і обмеження

- На CPU це повільно: приблизно **6–9 секунд на кадр**, тобто відео з 6
  кадрів — близько 40–60 с. Для тесту зменшуйте `--video-frames`.
- Тимчасові кадри пишуться у `%TEMP%\filesight\...` і видаляються після
  кожного відео, при помилці та при Ctrl+C. Вихідні відео відкриваються
  лише на читання.
- Якість опису обмежена: модель бачить кадри, а не рух/звук/текст на
  екрані. Для більшості кліпів назви змістовні, для дуже динамічних —
  загальні.
- Задовгі відео пропускаються (`status: skipped`, причина
  `video_too_long`); пошкоджене відео стає `failed` і не зупиняє scan.

## Редагування звіту

Звіт — звичайний JSON, його можна правити вручну перед перейменуванням:

- **Змінити назву**: відредагуйте `suggested_name` (лише ім'я файла, без
  шляху; розширення міняти не можна — регістр розширення однаково
  береться з оригіналу).
- **Вимкнути файл**: додайте запису `"rename_enabled": false` — він буде
  пропущений. Відсутність поля означає `true`.

Збереження з BOM (Notepad) — не проблема. Після редагування запустіть
`filesight validate`, щоб перевірити результат.

## Команда validate

```powershell
filesight validate "D:\Photos\filesight-report.json"
filesight validate "D:\Photos\filesight-report.json" --strict   # попередження = помилки
```

Перевіряє звіт і показує підсумок (скільки готово, пропущено, конфліктів).
Якщо перейменування небезпечне — ненульовий exit code і список проблем.

## Команда rename

```powershell
filesight rename "D:\Photos\filesight-report.json"                    # dry-run (за замовчуванням)
filesight rename "D:\Photos\filesight-report.json" --dry-run          # те саме явно
filesight rename "D:\Photos\filesight-report.json" --apply            # реально, з підтвердженням
filesight rename "D:\Photos\filesight-report.json" --apply --yes      # для скриптів
filesight rename "D:\Photos\filesight-report.json" --apply --limit 5  # перші 5 придатних
filesight rename "D:\Photos\filesight-report.json" --apply --resolve-conflicts
```

| Параметр | Опис |
| --- | --- |
| `--dry-run` | тільки показати план (це і є поведінка за замовчуванням) |
| `--apply` | реально перейменувати; без нього файли не змінюються |
| `--yes` | пропустити інтерактивне підтвердження (не вмикає `--apply`) |
| `--log PATH` | шлях журналу (за замовчуванням — поруч зі звітом) |
| `--limit N` | максимум N файлів, стабільно в порядку звіту |
| `--resolve-conflicts` | авто-нумерація конфліктних назв (`-002`, `-003`) |

Завжди пропускаються: записи зі статусом `failed`, без `suggested_name`,
з незміненою назвою та з `rename_enabled: false`.

Перед реальним перейменуванням створюється **журнал відкату**
`filesight-rename-log-YYYYMMDD-HHMMSS.json` (поруч зі звітом або за
`--log`). Журнал оновлюється під час операції. Якщо щось пішло не так,
FileSight сам відкочує вже виконані кроки і чесно показує стан.

Сторонні файли ніколи не перезаписуються: якщо цільова назва зайнята
файлом поза планом, операція блокується ще на етапі перевірки.

## Команда undo

```powershell
filesight undo "D:\Photos\filesight-rename-log-20260721-183000.json"          # dry-run
filesight undo "D:\Photos\filesight-rename-log-20260721-183000.json" --apply  # реальне скасування
filesight undo "D:\Photos\filesight-rename-log-20260721-183000.json" --apply --yes
```

Повертає файлам початкові назви за журналом. Перед цим перевіряє, що файли
існують, не підмінені (за розміром) і початкові шляхи вільні. Повторний
`undo --apply` для вже скасованого журналу нічого не робить і каже про це.

## Що робити при частковій помилці

Якщо rename або undo завершилися зі статусом `partially_rolled_back` /
`partially_undone` (exit code 5):

1. Відкрийте журнал — у записах зі `status: failed` поле `error` містить
   фактичне розташування файла.
2. Файли можуть мати тимчасові назви виду `.filesight-tmp-<uuid>.jpg` —
   вміст файлів цілий, втрачена лише назва.
3. Поверніть назву вручну (`Rename-Item`) за даними журналу.

Дані не втрачаються: FileSight ніколи не видаляє і не перезаписує вміст.

## Exit codes

| Код | Значення |
| --- | --- |
| 0 | успіх |
| 1 | загальна помилка (звіт уже існує, модель не завантажилась, відмова від підтвердження) |
| 2 | неправильні аргументи CLI / шлях |
| 3 | помилка валідації звіту |
| 4 | перейменування не вдалося, всі зміни відкочено |
| 5 | часткова операція або неповний відкат (потрібна увага) |
| 6 | помилка undo |
| 130 | перервано користувачем (Ctrl+C) |

## Тести

Тести швидкі й не завантажують нейромережу:

```powershell
.venv\Scripts\Activate.ps1
pytest
```

## Типові помилки

- **`Report already exists`** — додайте `--overwrite-report` або інший `--output`.
- **`TARGET_ALREADY_EXISTS`** — цільова назва зайнята стороннім файлом:
  змініть `suggested_name` у звіті або запустіть з `--resolve-conflicts`.
- **`SOURCE_MODIFIED`** — файл змінено після сканування; повторіть `scan`.
- **`Confirmation required...`** — неінтерактивний запуск: додайте `--yes`.
- **`ffmpeg was not found on PATH`** — встановіть FFmpeg або передайте
  `--ffmpeg-path` / `--ffprobe-path`.
- **Відео `FAILED (ProbeFailed / NoVideoStream)`** — файл не є валідним
  відео або пошкоджений; scan продовжується для решти.
- **Перший `scan` довго "висить"** — завантажується модель (~1 ГБ).
- **Скрипт активації заблоковано** —
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Обмеження поточної версії

- Українська локалізація — словник (~150 слів); невідомі слова лишаються
  англійськими, тому назва може бути змішаною.
- Виділення ознак словникове, не граматичне: незвичні формулювання дають
  лише `subject`.
- OCR не реалізовано, тому `{text}` майже завжди порожній (профіль
  `screenshots` через це зазвичай зводиться до `{date}-{category}`).
- Категоризація за ключовими словами плутає омоніми (напр. «terminal»
  в аеропорту vs термінал у коді).
- Confidence — евристика, а не ймовірність моделі.
- Перейменування лише в межах папки файла (без переміщення між папками).
- Перевірка "той самий файл" — за розміром і mtime, без криптографічного хешу.
- Шляхи довші за 259 символів не підтримуються.
- Відео аналізується лише за кадрами (без руху/звуку/тексту на екрані),
  на CPU, послідовно; довгі набори обробляються повільно.
- Немає GUI, GPU-прискорення.

## Roadmap (наступні ітерації)

1. OCR для скриншотів і документів (наповнить `{text}`).
2. Прискорення inference (ONNX/DirectML, батчинг) для Radeon RX 580.
3. Ширші словники української та кращий розбір ознак.
4. Графічний інтерфейс.
