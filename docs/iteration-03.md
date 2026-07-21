# FileSight — ітерація 3

## Мета

Додати аналіз коротких відео через вибрані кадри й повністю інтегрувати
відео в наявний цикл `scan → validate → rename → undo`. Без важкої
video-language моделі, без аудіо/транскрипції, без перекодування.

## Архітектура відеоаналізу

```text
video
→ video_probe (ffprobe JSON)      метадані, тривалість, rotation, audio
→ video_frames.compute_timestamps  часові позиції
→ video_frames.extract_frames      FFmpeg, 1 кадр на позицію, temp
→ frame_quality.assess_frame       відсів чорних/білих/low-var/дублікатів
→ video_caption.analyze_frames     caption кожного придатного кадру
→ VideoCaptionAggregator           один caption для відео
→ naming (спільний модуль)          безпечна назва
→ FileEntry у той самий звіт
```

Нові модулі:

| Модуль | Відповідальність |
| --- | --- |
| `video_probe.py` | пошук ffmpeg/ffprobe, запуск ffprobe, парсинг метаданих |
| `video_frames.py` | розрахунок часових позицій, витяг кадрів, timeout, kill |
| `frame_quality.py` | евристики чорний/білий/low-variance/near-duplicate/decode |
| `video_caption.py` | аналіз кадрів + `VideoCaptionAggregator` |
| `temp_files.py` | `FrameWorkspace`: тимчасові папки, гарантоване очищення |
| `video_pipeline.py` | оркестрація одного відео → `FileEntry` |
| `config.py` | усі константи (тривалість, кадри, timeout, пороги якості) |

FFmpeg завжди запускається списком аргументів через `subprocess`
(ніколи `shell=True`). Unicode-шляхи, пробіли та кирилиця працюють.

## Підтримувані формати

`.mp4 .mov .mkv .webm .avi .m4v` — без урахування регістру. Валідність
визначається лише через ffprobe, а не за розширенням: якщо ffprobe/FFmpeg
не читає файл, помилка записується для цього файла, scan триває.

## Вибір кадрів

За замовчуванням 6 кадрів (`--video-frames`, діапазон 1–20). Часові
позиції рівномірні й детерміновані:

- відео ≤ 5 с: частки між 15% і 90% тривалості;
- відео > 5 с: частки між 5% і 95% (для 6 кадрів: 5, 23, 41, 59, 77, 95%).

Точний 0.0 і точний кінець ніколи не використовуються (уникнення чорних
заставок/фейдів). Для 1 кадру береться середина діапазону.

## Фільтрація кадрів (frame_quality)

Прості евристики без нейромережі, причини відкидання:

- `too_dark` — середня яскравість ≤ 16;
- `too_bright` — середня яскравість ≥ 240;
- `low_variance` — стандартне відхилення ≤ 6;
- `near_duplicate` — dHash (8×8) відрізняється від попереднього ≤ 6 біт;
- `decode_failed` — Pillow не відкрив кадр.

Пороги — у `config.py`. Модель не отримує явно порожні або дубльовані кадри.

## Агрегація captions

`VideoCaptionAggregator` — детермінований, без нової мовної моделі:

1. кожен caption токенізується спільним `naming.caption_to_words`
   (ті самі стоп-слова/фільтри, що й для зображень);
2. рахується, у скількох кадрах трапляється кожне значуще слово;
3. вибирається caption, чиї слова максимально покривають найчастотніші
   (за сумою частот), стабільний tie-break — найраніший кадр.

Один caption → повертається як є; порожній список → `None`
(відео стає `failed` з `NoUsableVideoFrames`). Якщо проаналізовано менше
кадрів, ніж витягнуто, додається warning `partial_frame_analysis`.
Для одного придатного кадру відео вважається `success`.

## Формат video metadata і зміни схеми

`schema_version` піднято до **1.2** (підтримуються 1.0, 1.1, 1.2). Нові
необов'язкові поля запису:

- `media_type`: `"image"` | `"video"` (відсутнє → `image`);
- `video_metadata`: duration_seconds, width, height, frame_rate,
  video_codec, container, has_audio, rotation_degrees;
- `video_analysis`: requested/extracted/usable/analyzed_frames,
  `frames[]` (index, timestamp_seconds, status, skip_reason, caption,
  error), `warnings[]`;
- `timings`: probe_ms, frame_extraction_ms, captioning_ms,
  aggregation_ms, total_ms.

Записи зображень залишаються без video-полів (вони не серіалізуються, коли
None), додається лише `media_type: image`. Summary отримує `skipped` і, коли
відео увімкнено, підрозділи `images`/`videos` з count'ами. Старі звіти без
`media_type` читаються як зображення; `validate`/`rename`/`undo` не ламаються.

## Інтеграція validate / rename / undo

Ці команди **не запускають FFmpeg і не завантажують модель**. Відео
проходить ті самі перевірки, що й зображення (існування файла, безпечна
назва, незмінне розширення, конфлікти, метадані, `media_type` підтримується).
Тимчасові кадри не потрібні для валідації — вони не зберігаються після scan.
`rename` та `undo` використовують той самий двофазний алгоритм; вміст
відеофайла ніколи не змінюється (лише rename, без перекодування).

Записи `status: skipped` (задовге відео) і `failed` автоматично
пропускаються при перейменуванні.

## Temp-файли

`FrameWorkspace` створює `%TEMP%/filesight/operation-<uuid>/video-<uuid>/`.
Кадри одного відео видаляються одразу після його обробки; уся папка
операції — у `finally`/на виході з контексту, тобто і при помилці, і при
Ctrl+C. FileSight видаляє лише створені ним директорії (перевірка
`is_relative_to`), ніколи чужі файли.

## Timeout-и

- ffprobe: 30 с (`FFPROBE_TIMEOUT_SECONDS`);
- витяг одного кадру: 60 с (`FRAME_EXTRACTION_TIMEOUT_SECONDS`).

При timeout процес примусово завершується (`kill` + `wait`), помилка
записується, temp очищається, scan триває. Дочірні FFmpeg ніколи не
залишаються у фоні: extraction гарантує kill у `except BaseException`.

## Ctrl+C

Переривання під час аналізу піднімає `KeyboardInterrupt` крізь
extraction (з kill поточного FFmpeg) і pipeline; CLI ловить його, чистить
`FrameWorkspace` у `finally`, пише частковий звіт і виходить з кодом 130.
Вихідні відео не змінюються.

## Обробка помилок (типи в error.type)

`NoVideoStream`, `UnknownDuration`, `ZeroDuration`, `ProbeTimeout`,
`ProbeFailed`, `ProbeError`, `NoUsableVideoFrames`, `FrameExtractionError`,
`video_too_long` (для `status: skipped`). Помилка одного відео ніколи не
зупиняє scan інших.

## CLI (нові параметри scan)

```text
--include-videos           зображення + відео
--images-only              лише зображення (типова поведінка, явно)
--videos-only              лише відео
--video-frames N           кадрів на відео (1–20, типово 6)
--max-video-duration SEC   ліміт тривалості (типово 120)
--allow-long-videos        аналізувати довші відео (кадри все одно обмежені)
--ffmpeg-path PATH         явний шлях до ffmpeg
--ffprobe-path PATH        явний шлях до ffprobe
--verbose                  діагностика (шляхи, exit code, stderr, timings)
```

Несумісні комбінації (`--images-only` + `--videos-only`, `--images-only`
+ `--include-videos`) і `--video-frames` поза діапазоном → exit 2. FFmpeg
перевіряється лише коли в наборі є відео.

## Гарантії безпеки

Вихідні відео відкриваються лише на читання; FFmpeg пише тільки в temp;
`suggested_name` не може містити шлях; розширення незмінне; rename/undo не
перекодовують; сторонні файли не перезаписуються; вміст файлів не
змінюється (перевірено SHA-256 до/після rename+undo).

## Відомі обмеження

- Аналіз лише за кадрами: немає розуміння руху, звуку, тексту на екрані.
- Якість caption для відео обмежена BLIP і стратегією «вибрати
  найрепрезентативніший кадр» — достатньо для назви, не для опису сюжету.
- Анімовані переходи/дуже динамічні відео можуть давати загальний caption.
- Rotation покладається на автоповорот FFmpeg при декодуванні (перевірено).
- Один прохід, послідовно, CPU — довгі набори відео обробляються повільно.

## Ручний сценарій перевірки

Див. `progress.md` (розділ ручної перевірки) — фактично перевірені
сценарії: звичайне, вертикальне (rotation), коротке, середнє, задовге,
пробіли в назві, кирилиця в назві, пошкоджене, змішана папка, повний
цикл rename+undo з перевіркою SHA-256.

## Критерії завершення

Усі 40 критеріїв приймання ітерації 3 виконані; фактичні результати
(тести + ручна перевірка на реальному FFmpeg) зафіксовані в `progress.md`.
