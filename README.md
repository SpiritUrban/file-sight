# FileSight

FileSight — локальна консольна програма, яка аналізує вміст зображень за
допомогою vision-моделі та пропонує зрозумілі назви файлів.

Програма **нічого не перейменовує і не змінює** — вона лише створює JSON-звіт
зі старими та запропонованими назвами.

## Можливості (ітерація 1)

- Сканування папки з зображеннями (`.jpg`, `.jpeg`, `.png`, `.webp`, без урахування регістру).
- Локальний image captioning на CPU (модель `Salesforce/blip-image-captioning-base`).
- Генерація безпечної запропонованої назви з опису (lowercase, дефіси, без заборонених символів Windows).
- Стабільна нумерація дублікатів назв у межах звіту (`-002`, `-003`, ...).
- Читабельний JSON-звіт у UTF-8 з помилками окремих файлів.
- Пошкоджений файл не зупиняє обробку інших.

## Обмеження ітерації 1

- Немає графічного інтерфейсу, відео, реального перейменування, undo, бази даних, GPU.
- Українські назви (`--language uk`) — експериментальна функція: наразі виводиться
  попередження і використовуються англійські назви.
- Замість Florence-2 використано BLIP: Florence-2 потребує `trust_remote_code`
  і несумісна з поточними версіями Transformers (див. `docs/iteration-01.md`).

## Системні вимоги

- Windows 10/11 (працює і на Linux/macOS).
- Python 3.11+ (перевірено на 3.14).
- ~2 ГБ вільного місця (PyTorch + модель ~1 ГБ, кешується Hugging Face).
- Інтернет потрібен лише один раз — для завантаження моделі.
- GPU не потрібен, CUDA не потрібна.

## Встановлення (Windows PowerShell)

Якщо Python ще не встановлено — завантажте з <https://www.python.org/downloads/>
(позначте "Add python.exe to PATH").

```powershell
git clone https://github.com/your-user/file-sight.git
cd file-sight
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
```

> Рядок з `--index-url` ставить CPU-версію PyTorch (менша й швидша за CUDA-збірку).
> Якщо його пропустити, `pip install -e .` також встановить torch, але це може бути більший пакет.

## Перший запуск

```powershell
filesight scan "D:\Photos" --max-files 10
```

Або без встановлення пакета:

```powershell
python -m filesight scan "D:\Photos" --max-files 10
```

При першому запуску модель (~1 ГБ) автоматично завантажується та кешується в
стандартній папці Hugging Face (`%USERPROFILE%\.cache\huggingface`). Наступні
запуски працюють повністю офлайн.

## Параметри CLI

| Параметр | За замовчуванням | Опис |
| --- | --- | --- |
| `PATH` | — | шлях до папки з зображеннями |
| `--recursive` | вимкнено | сканувати вкладені папки |
| `--output` | `filesight-report.json` у `PATH` | шлях до JSON-звіту |
| `--max-files` | без обмеження | обмежити кількість файлів (для тестових запусків) |
| `--language` | `en` | мова назв: `en` або `uk` (uk — експериментально) |
| `--overwrite-report` | вимкнено | дозволити перезапис існуючого звіту |

Приклади:

```powershell
filesight scan "D:\Photos"
filesight scan "D:\Photos" --recursive --output "D:\reports\photos.json"
filesight scan "D:\Photos" --max-files 5 --overwrite-report
```

## Звіт

Звіт зберігається за замовчуванням у `PATH\filesight-report.json`. Приклад запису:

```json
{
  "original_name": "IMG_9482.JPG",
  "status": "success",
  "caption": "a black dog running through the snow",
  "suggested_name": "black-dog-running-through-snow.JPG"
}
```

Повний формат описано в `docs/iteration-01.md`.

## Тести

Тести швидкі й не завантажують нейромережу:

```powershell
.venv\Scripts\Activate.ps1
pytest
```

## Типові помилки

- **`Report already exists`** — звіт уже існує; додайте `--overwrite-report`
  або вкажіть інший `--output`.
- **`Folder does not exist`** — перевірте шлях; шляхи з пробілами беріть у лапки.
- **Перший запуск довго "висить"** — іде завантаження моделі (~1 ГБ); дочекайтеся.
- **`Could not load model`** — немає інтернету при першому запуску або
  пошкоджений кеш (`%USERPROFILE%\.cache\huggingface` можна видалити і спробувати знову).
- **Скрипт активації заблоковано** — виконайте
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` і повторіть.
- **Повільна обробка** — це нормально для CPU: приблизно 2–6 с на зображення.

## Важливо

FileSight у цій версії **не перейменовує файли**. Він лише пропонує назви у
JSON-звіті. Вихідні зображення ніколи не змінюються.

## Roadmap (наступні ітерації)

1. Реальне перейменування за звітом з підтвердженням та undo.
2. Якісні українські назви.
3. Прискорення (ONNX/DirectML, батчинг) для Radeon RX 580.
4. Підтримка додаткових форматів і відео.
5. Графічний інтерфейс.
