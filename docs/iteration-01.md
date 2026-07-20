# FileSight — ітерація 1

## Мета

Мінімальна робоча консольна версія: сканування папки, локальний image
captioning на CPU, генерація безпечних запропонованих назв, JSON-звіт.
Без перейменування файлів.

## Що реалізовано

- CLI `filesight scan PATH` (Typer) з параметрами `--recursive`, `--output`,
  `--max-files`, `--language`, `--overwrite-report`.
- Пошук `.jpg / .jpeg / .png / .webp` без урахування регістру; за замовчуванням
  без вкладених папок, `--recursive` вмикає рекурсію.
- Обробка зображення: Pillow → виправлення EXIF-орієнтації
  (`ImageOps.exif_transpose`) → конвертація в RGB → модель.
- Captioning: `Salesforce/blip-image-captioning-base`, CPU, beam search
  (3 промені), до 32 нових токенів.
- Генерація назви: видалення вступних фраз ("a photo of", "there is", ...),
  артиклів і слів-паразитів; lowercase; дефіси; тільки `[a-z0-9-]`; до 8 слів
  і до 80 символів без розширення; оригінальне розширення зберігається.
- Стабільна нумерація дублікатів у межах звіту: `name.jpg`, `name-002.jpg`,
  `name-003.jpg` (порівняння без урахування регістру).
- JSON-звіт у UTF-8 з відступами; помилка окремого файла записується у звіт і
  не зупиняє обробку решти.
- Обробка Ctrl+C: частковий звіт записується, exit code 130.
- Тести (pytest) без завантаження реальної моделі — mock captioner.

## Що свідомо НЕ реалізовано

GUI, Tauri/React/Rust, відео, FFmpeg, реальне перейменування, undo, база
даних, ONNX/DirectML, GPU (RX 580), хмарні API, розпізнавання людей,
тренування моделей, плагіни, мікросервіси, Docker.

## Заміна моделі: чому не Florence-2

`microsoft/Florence-2-base-ft` потребує `trust_remote_code=True`, а її
remote-код несумісний із Transformers 4.50+ (модель втратила успадкування
`GenerationMixin`; пізніше — помилка `_supports_sdpa`). Див. issues
transformers [#36886](https://github.com/huggingface/transformers/issues/36886)
та [#39974](https://github.com/huggingface/transformers/issues/39974).
Стабільний запуск вимагав би пінити старий transformers==4.49 або
використовувати сторонні форки.

Натомість обрано **`Salesforce/blip-image-captioning-base`**:

- нативний клас `BlipForConditionalGeneration` у Transformers — без
  `trust_remote_code`;
- ліцензія BSD-3-Clause;
- ~990 МБ, стабільно працює на CPU;
- автоматичне завантаження та кешування стандартним механізмом Hugging Face.

Мета ітерації не змінилася.

## Архітектура

```text
src/filesight/
├─ cli.py        — CLI, валідація аргументів, прогрес у терміналі, exit codes
├─ scanner.py    — пошук підтримуваних файлів (без captioner)
├─ captioner.py  — BlipCaptioner (ліниве завантаження), відкриття зображення
├─ pipeline.py   — обробка списку файлів; captioner інжектиться (тестовність)
├─ naming.py     — caption → безпечна назва; NameAllocator для дублікатів
├─ report.py     — побудова та запис JSON-звіту
└─ models.py     — dataclass-структури звіту (schema_version 1.0)
```

Логіка назв повністю відділена від нейромережі; сканер — від captioner.

## Формат JSON (schema_version 1.0)

```json
{
  "schema_version": "1.0",
  "created_at": "2026-07-20T20:30:00Z",
  "source_directory": "D:\\Photos",
  "recursive": false,
  "model": {
    "provider": "huggingface",
    "name": "Salesforce/blip-image-captioning-base",
    "device": "cpu"
  },
  "summary": {
    "discovered": 3,
    "processed": 2,
    "failed": 1,
    "duration_seconds": 18.42
  },
  "files": [
    {
      "original_path": "D:\\Photos\\IMG_9482.JPG",
      "original_name": "IMG_9482.JPG",
      "extension": ".JPG",
      "status": "success",
      "caption": "a black dog running through the snow",
      "suggested_name": "black-dog-running-through-snow.JPG",
      "processing_time_ms": 4210,
      "error": null
    },
    {
      "original_path": "D:\\Photos\\broken.png",
      "original_name": "broken.png",
      "extension": ".png",
      "status": "failed",
      "caption": null,
      "suggested_name": null,
      "processing_time_ms": 18,
      "error": {
        "type": "UnidentifiedImageError",
        "message": "cannot identify image file ..."
      }
    }
  ]
}
```

## Відомі обмеження

- `--language uk` лише попереджає, що функція експериментальна, і використовує
  англійські назви.
- BLIP описує зображення загально; скриншоти коду описує приблизно
  ("screenshot of a computer screen"), без деталей.
- Швидкість на CPU: ~2–6 с на зображення.
- Конфлікти назв перевіряються лише в межах одного звіту, не з файлами на диску.
- Анімовані WebP обробляються по першому кадру.

## Ручний сценарій перевірки

1. Створити папку з: звичайною фотографією (JPG), скриншотом (PNG), WebP,
   пошкодженим файлом (наприклад, текст із розширенням `.png`).
2. `filesight scan <папка>`.
3. Перевірити: у терміналі прогрес `[i/n]`; звіт створено; у звіті 3 успішних
   записи з caption і suggested_name та 1 failed із типом помилки.
4. Переконатися, що вихідні файли не змінені (дата зміни/хеш ті самі).
5. Повторний запуск без `--overwrite-report` → помилка, exit code ≠ 0.

## Критерії завершення

Усі критерії приймання із завдання ітерації виконані; фактичні результати
перевірки зафіксовано в `progress.md`.
