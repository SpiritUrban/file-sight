# FileSight

FileSight — локальна консольна програма, яка аналізує вміст зображень за
допомогою vision-моделі, пропонує зрозумілі назви файлів і вміє **безпечно
застосовувати** ці назви з журналом та скасуванням.

Головний принцип: **без явного `--apply` жоден файл не змінюється**, а
сторонні файли ніколи не перезаписуються.

## Можливості

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

## Робочий процес

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
- **Перший `scan` довго "висить"** — завантажується модель (~1 ГБ).
- **Скрипт активації заблоковано** —
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Обмеження поточної версії

- Українські назви (`--language uk`) — експериментально: попередження і
  англійський fallback.
- Перейменування лише в межах папки файла (без переміщення між папками).
- Перевірка "той самий файл" — за розміром і mtime, без криптографічного хешу.
- Шляхи довші за 259 символів не підтримуються.
- Немає GUI, відео, GPU.

## Roadmap (наступні ітерації)

1. Якісні українські назви.
2. Прискорення inference (ONNX/DirectML, батчинг) для Radeon RX 580.
3. Кращі описи скриншотів; додаткові формати.
4. Графічний інтерфейс.
