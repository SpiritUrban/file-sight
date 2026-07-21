# FileSight — ітерація 4

## Мета

Додати керовану систему іменування: профілі, категорії, правила й шаблони.
Назва більше не будується напряму з caption — між аналізом і файлом
з'явився детермінований, конфігурований і пояснюваний шар.

## Фактична архітектура

```text
caption + metadata
→ features.py        subject / action / location / objects
→ categories.py      категорія + confidence + matched_rules
→ media_dates.py     captured_at + date_source
→ profiles.py        активний профіль (built-in / TOML / CLI)
→ templates.py       підстановка, очищення, довжина, Windows-safe
→ naming_preview.py  NamingSession: індекси + дедуплікація
→ suggested_name
```

Нові модулі:

| Модуль | Відповідальність |
| --- | --- |
| `config.py` | читання TOML (`tomllib`), валідація, вибір профілю |
| `config_template.py` | зразок конфігурації для `config init` |
| `profiles.py` | `NamingProfile`, вбудовані профілі, merge |
| `features.py` | caption → `MediaFeatures`, fallback-логіка |
| `categories.py` | таксономія, `CategoryRule`, `MediaCategorizer`, score |
| `templates.py` | `FilenameTemplateEngine` |
| `localization.py` | українські мітки категорій і словник слів |
| `transliteration.py` | КМУ-2010 транслітерація |
| `media_dates.py` | EXIF / video creation_time / filesystem + date_source |
| `naming_preview.py` | спільний пайплайн + `NamingSession` |
| `report_transform.py` | повторна генерація назв без моделі |
| `constants.py` | усі числові константи (винесені зі старого `config.py`) |

Константи відео переїхали з `config.py` у `constants.py`, бо `config.py`
тепер відповідає за конфігурацію.

## Формат конфігурації

TOML, читається стандартним `tomllib` (без нових залежностей):

```toml
config_version = "1.0"
default_profile = "photos"

[profiles.photos]
template = "{date}-{category}-{subject}-{location}"
language = "en"                # en | uk
separator = "-"                # - | _ | (пробіл)
case_style = "lower"           # lower | upper | title | preserve
transliterate = false
max_filename_length = 100      # 20..240
max_objects = 3
max_caption_words = 8
date_format = "%Y-%m-%d"
time_format = "%H-%M-%S"
index_start = 1
index_padding = 3
index_scope = "global"         # global | category | directory
clean_original_stem = true

[categories.receipts]
enabled = true
priority = 150
keywords_any = ["receipt", "invoice", "total"]
filename_contains = ["scan"]
extensions = [".jpg", ".png"]
media_types = ["image"]
min_matches = 1
```

Пошук конфігурації: `--config PATH` → `./filesight.toml` → вбудовані
значення. Відсутність файла **не** є помилкою.

## Порядок пріоритетів

```text
CLI override (--template/--profile/--language/--transliterate)
→ вибраний профіль у TOML
→ default_profile у TOML
→ вбудований профіль
```

Користувацький профіль з іменем вбудованого **частково перевизначає** його:
незадані поля успадковуються (напр. `[profiles.compact]` з одним
`template` зберігає `max_filename_length = 70`).

## Вбудовані профілі

| Профіль | Шаблон |
| --- | --- |
| `default` | `{subject}-{action}-{location}` (поведінка ітерацій 1–3) |
| `photos` | `{date}-{category}-{subject}-{location}` |
| `compact` | `{subject}-{action}` |
| `archive` | `{date}-{media_type}-{category}-{subject}-{index}` |
| `screenshots` | `{date}-{category}-{text}` |

## Шаблонний двигун

Підтримувані змінні:

```text
{subject} {action} {location} {objects} {text} {category} {media_type}
{date} {time} {year} {month} {day} {original_stem} {index} {caption}
{width} {height} {duration}
```

Порядок обробки: підстановка → видалення порожніх сегментів →
нормалізація роздільників → злиття повторів сусідніх слів → видалення
заборонених символів → case style → транслітерація (якщо увімкнена) →
обмеження довжини по цілих словах → перевірка зарезервованих імен →
дедуплікація в межах звіту.

Гарантії: назва ніколи не порожня, не містить шляху (`/`, `\`, `..`),
не має подвійних чи крайніх роздільників, зберігає оригінальне розширення,
не містить `none`/`null`/`unknown`/`undefined`.

Fallback: `{category}-{index}`, а якщо категорії немає — `media-{index}`.

## Правила категорій і scoring

Умови: `keywords_any`, `keywords_all` (обов'язкові всі), `filename_contains`,
`caption_contains`, `extensions`, `media_types`, `min_matches`, `priority`.

Порядок вибору переможця (детермінований):

1. більша кількість збігів;
2. вищий `priority`;
3. раніше визначена категорія;
4. інакше — `other`.

**Confidence** — це rule-based score, а не ймовірність моделі:

```text
1 збіг → 0.55   2 → 0.70   3 → 0.82   4+ → 0.92   0 → 0.0
```

Стандартна таксономія (17): people, animals, nature, food, vehicles,
documents, screenshots, code, products, buildings, travel, sports,
events, art, memes, medical, other.

Для скриншотів додано евристику за іменем файла
(`Screenshot*`, `screen shot`, `snip`, `capture`).

## Date extraction

Зображення: EXIF `DateTimeOriginal` → `DateTimeDigitized` → `DateTime` →
filesystem created → modified.
Відео: контейнерний `creation_time` → filesystem created → modified.

Записується `captured_at` і `date_source`. Дати до 1990 року та дати
далеко в майбутньому відкидаються з попередженням
`implausible_metadata_date` і замінюються filesystem-джерелом.
Часовий пояс не вигадується: naive-часи залишаються naive.

## Локалізація та транслітерація

`language = "uk"` перекладає категорію та поширені слова за вбудованими
словниками (`localization.py`); невідомі слова лишаються англійськими.
Внутрішнє значення `category` у JSON завжди стабільне й англійське,
локалізоване значення — в `category_label`.

`transliterate = true` застосовує офіційну транслітерацію КМУ-2010
(постанова №55, 2010): позиційні `є/ї/й/ю/я` (ye/yi/y/yu/ya на початку
слова, ie/i/i/iu/ia далі), `зг → zgh`, м'який знак і апостроф
відкидаються.

```text
en:          animals-black-dog-running
uk:          тварини-чорний-пес-біжить
uk + translit: tvaryny-chornyi-pes-bizhyt
```

## Зміни JSON-схеми

`schema_version` = **1.3** (підтримуються 1.0–1.3). Нові необов'язкові поля:

```json
{
  "features": {"subject": "black dog", "action": "running",
               "location": "snow", "objects": ["snow", "trees"], "text": null},
  "classification": {"category": "animals", "category_label": "animals",
                     "confidence": 0.55, "method": "rules",
                     "matched_rules": ["keyword:dog"]},
  "naming": {"profile": "photos", "template": "...", "language": "en",
             "transliterated": false, "base_name": "...",
             "suggested_name": "...", "warnings": []},
  "captured_at": "2026-01-14T15:42:10",
  "date_source": "exif_datetime_original",
  "suggested_name": "2026-01-14-animals-black-dog-snow.JPG"
}
```

У корені звіту з'явилося `naming_configuration` (source, config_version,
profile, template, language, transliterate). Верхньорівневе
`suggested_name` збережене — саме його використовує `rename`.

## Report transform

```powershell
filesight report rename-suggestions report.json --profile archive --output new.json
```

Читає збережені captions, заново будує features/classification/назви й
пише **новий** звіт. Вихідний звіт не перезаписується без `--overwrite`.
`--dry-run` показує OLD/NEW і нічого не пише. Модель не завантажується
(перевірено тестом на `sys.modules`). Медіафайли не змінюються.

## Сумісність

- `scan` без конфігурації працює як раніше (профіль `default`).
- Старі звіти (1.0–1.2) читаються; відсутній `media_type` = `image`;
  відсутність нових секцій не робить звіт невалідним.
- `rename` і `undo` не змінені й не залежать від конфігурації: вони
  беруть верхньорівневий `suggested_name`, який користувач може
  редагувати вручну. Розбіжність із `naming.suggested_name` — лише
  попередження (`NAMING_EDITED`), а не помилка.
- `validate` додатково перевіряє структуру features/classification/naming,
  підтримуваний `media_type` і відсутність шляху в `naming.base_name`.

## Продуктивність

`config validate`, `naming preview`, `category explain` і
`report rename-suggestions` не імпортують PyTorch/transformers, не
перевіряють FFmpeg і виконуються за долі секунди. Це закріплено тестами,
які запускають команду в окремому інтерпретаторі й перевіряють
`sys.modules`.

## Відомі обмеження

- `FeatureExtractor` — словниковий, не граматичний парсер: незвичні
  формулювання дають лише subject.
- OCR не реалізовано, тому `{text}` майже завжди порожній (профіль
  `screenshots` через це часто зводиться до `{date}-{category}`).
- Українська локалізація покриває ~150 поширених слів; решта лишається
  англійською (змішані назви можливі).
- `index_scope = "category"` і `"directory"` реалізовані, але корисні
  лише разом із `{index}` у шаблоні.
- Confidence — евристика, не ймовірність; не використовувати для
  автоматичних рішень без перегляду.
- Категоризація за ключовими словами плутає омоніми (напр. «terminal»
  в аеропорту vs термінал у коді).

## Ручний сценарій перевірки

Див. `progress.md` — фактично виконано: config init/validate/show,
користувацький профіль і категорія, naming preview, category explain,
реальний scan змішаної папки з конфігурацією, перевірка features /
classification / naming / captured_at у JSON, український профіль і
транслітерація, report transform (dry-run і запис), validate → rename
dry-run → apply → undo з перевіркою SHA-256, оцінка категоризації на
30 зразках.

## Критерії завершення

Усі 46 критеріїв приймання ітерації 4 виконані; фактичні результати —
у `progress.md`.
