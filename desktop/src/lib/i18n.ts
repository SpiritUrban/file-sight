/**
 * Interface translation.
 *
 * The English text *is* the key. Retrofitting keys onto an existing UI means
 * inventing a couple of hundred names, and every one is a chance to write
 * `t("settings.ffmpeg.label")` next to a component that says something else.
 * With the source string as the key three things follow for free: the code
 * still reads like the screen, no English dictionary has to be maintained in
 * parallel with the markup, and anything not yet translated falls back to
 * real English rather than to a visible identifier.
 *
 *     t("Choose folder")
 *     t("{done} of {total} files", { done: 3, total: 10 })
 */

import { useSyncExternalStore } from "react";

import {
  applyLanguage,
  initialLanguage,
  storeLanguage,
  type Language,
} from "@/lib/preferences";

export type { Language };

/** Ukrainian only: English comes from the keys themselves. */
const UK: Record<string, string> = {
  // --- progress and filters ----------------------------------------------
  Working: "Робота",
  "{elapsed} elapsed": "минуло {elapsed}",
  "Analysis progress": "Прогрес аналізу",
  "Filter files": "Фільтр файлів",
  "Filter by category": "Фільтр за категорією",
  All: "Усі",
  Success: "Успішно",
  Failed: "Помилка",
  Skipped: "Пропущено",
  Enabled: "Увімкнено",
  Disabled: "Вимкнено",
  Category: "Категорія",
  "All categories": "Усі категорії",
  "Search name, caption or category": "Пошук за назвою, описом або категорією",
  "Search files": "Пошук файлів",

  // Phase names and stages the worker sends as plain English.
  "Scanning folder": "Сканування теки",
  Analyzing: "Аналіз",
  "Loading model": "Завантаження моделі",
  Renaming: "Перейменування",
  downloading: "завантаження",
  extracting: "розпакування",
  starting: "запуск",
  working: "робота",

  // --- shell -------------------------------------------------------------
  "Choose folder": "Вибрати теку",
  "No folder selected": "Теку не вибрано",
  "Start analysis": "Почати аналіз",
  Cancel: "Скасувати",
  "Cancelling…": "Скасування…",
  Settings: "Налаштування",
  Profile: "Профіль",
  Images: "Зображення",
  Videos: "Відео",
  Recursive: "З підтеками",
  "Max files": "Макс. файлів",
  all: "усі",
  "Frames/video": "Кадрів на відео",

  // --- environment bar ---------------------------------------------------
  Python: "Python",
  "FileSight core": "Ядро FileSight",
  Model: "Модель",
  FFmpeg: "FFmpeg",
  GPU: "GPU",
  "Not found": "Не знайдено",
  Ready: "Готово",
  Missing: "Відсутнє",
  "Loading…": "Завантаження…",
  Loaded: "Завантажена",
  "Not loaded": "Не завантажена",
  "Not downloaded": "Не завантажена з мережі",
  "Not available": "Недоступний",
  Available: "Доступний",
  "Checking environment…": "Перевірка середовища…",
  "Environment unknown": "Середовище невідоме",

  // --- empty state -------------------------------------------------------
  "Choose a folder with images or short videos.":
    "Виберіть теку із зображеннями або короткими відео.",
  "FileSight analyzes files locally. Nothing is uploaded. The first analysis may download an AI model. No file is renamed until you confirm the plan.":
    "FileSight аналізує файли локально. Нічого не завантажується в мережу. Перший аналіз може завантажити модель. Жоден файл не перейменовується, поки ви не підтвердите план.",
  "Built by": "Зроблено",

  // --- errors ------------------------------------------------------------
  "No files were changed.": "Жоден файл не змінено.",
  Dismiss: "Закрити",
  "Run analysis again": "Запустити аналіз знову",
  "…and {count} more. Use Validate to see them all.":
    "…і ще {count}. Натисніть «Перевірити», щоб побачити всі.",
  "These files changed on disk after the analysis. Run the analysis again.":
    "Ці файли змінилися на диску після аналізу. Запустіть аналіз знову.",
  "These files no longer exist. Run the analysis again.":
    "Цих файлів більше немає. Запустіть аналіз знову.",
  "Another file already uses that name. Edit the suggested name, or turn that file off.":
    "Таку назву вже має інший файл. Змініть запропоновану назву або вимкніть цей файл.",
  "Two files would get the same name. Edit one of them.":
    "Два файли отримали б однакову назву. Змініть одну з них.",
  "The extension must stay the same as the original file.":
    "Розширення має лишитися таким самим, як в оригіналі.",
  "Fix the highlighted names in the table.":
    "Виправте підсвічені назви в таблиці.",
  "Use Validate to review every problem.":
    "Натисніть «Перевірити», щоб переглянути всі проблеми.",

  // --- footer actions ----------------------------------------------------
  "Unsaved changes": "Незбережені зміни",
  Saved: "Збережено",
  "{enabled} of {total} selected for rename":
    "{enabled} з {total} вибрано для перейменування",
  "Save report": "Зберегти звіт",
  Validate: "Перевірити",
  "Dry run": "Пробний запуск",
  "Rename files": "Перейменувати файли",
  "Undo last rename": "Скасувати останнє перейменування",
  "Fix the highlighted names first": "Спершу виправте підсвічені назви",
  "Enable at least one file": "Увімкніть хоча б один файл",
  "· Inference: {backend}": "· Аналіз: {backend}",

  // --- update banner -----------------------------------------------------
  "Update available — FileSight {version}":
    "Доступне оновлення — FileSight {version}",
  "Downloading…": "Завантаження…",
  "Installing…": "Встановлення…",
  "Installed. Restart FileSight to use it.":
    "Встановлено. Перезапустіть FileSight, щоб користуватися.",
  "Update now": "Оновити зараз",
  "Try again": "Спробувати ще раз",
  "Dismiss update notice": "Сховати повідомлення про оновлення",

  // --- ffmpeg ------------------------------------------------------------
  "Download FFmpeg automatically": "Завантажити FFmpeg автоматично",
  "Downloads a static FFmpeg build into FileSight's own folder. Nothing else on the system is changed.":
    "Завантажує готову збірку FFmpeg у власну теку FileSight. Більше нічого в системі не змінюється.",
  "The analysis worker is not running yet.": "Робочий процес аналізу ще не запущено.",
  "The download failed.": "Не вдалося завантажити.",
  "Installed in {directory}": "Встановлено в {directory}",
  Installed: "Встановлено",
  "Video support needs FFmpeg. Leave the fields above empty and let FileSight fetch a build into its own folder — nothing else on the system is changed, and no PATH edit is needed.":
    "Для відео потрібен FFmpeg. Лишіть поля вище порожніми, і FileSight завантажить збірку у власну теку — більше нічого в системі не змінюється, PATH правити не треба.",

  // --- settings ----------------------------------------------------------
  Appearance: "Вигляд",
  Theme: "Тема",
  Dark: "Темна",
  Light: "Світла",
  Language: "Мова",
  "Python executable": "Виконуваний файл Python",
  "FFmpeg executable": "Виконуваний файл FFmpeg",
  "ffprobe executable": "Виконуваний файл ffprobe",
  "Config file (filesight.toml)": "Файл конфігурації (filesight.toml)",
  "Default profile": "Профіль за замовчуванням",
  "Report filename": "Ім'я файлу звіту",
  "Recursive by default": "З підтеками за замовчуванням",
  "Include videos by default": "Включати відео за замовчуванням",
  Browse: "Огляд",
  "auto-detect": "визначити автоматично",
  "Save settings": "Зберегти налаштування",
  Inference: "Аналіз",
  Backend: "Бекенд",
  "Auto (best available)": "Авто (найкращий доступний)",
  "NVIDIA GPU (CUDA)": "GPU NVIDIA (CUDA)",
  "AMD / Intel GPU (DirectML)": "GPU AMD / Intel (DirectML)",
  "CPU (ONNX Runtime)": "CPU (ONNX Runtime)",
  "CPU (PyTorch)": "CPU (PyTorch)",
  "Allow automatic fallback": "Дозволити автоматичний відкат",
  "GPU backends need the ONNX model pack installed; without it they cannot caption and this falls back to CPU. Captions are identical on every backend, and a GPU is not currently faster for a whole scan. Each report names the backend that actually ran.":
    "GPU-бекендам потрібен встановлений ONNX-пакет моделі; без нього вони не вміють описувати зображення, і аналіз відкочується на CPU. Описи однакові на будь-якому бекенді, і GPU наразі не пришвидшує весь скан. Кожен звіт називає бекенд, який реально працював.",
  "Test backend": "Перевірити бекенд",
  "Testing…": "Перевірка…",
  "Run benchmark": "Виміряти швидкодію",
  "Running…": "Виконується…",
  "Test environment": "Перевірити середовище",
  "Open logs folder": "Відкрити теку журналів",
  "Environment test failed.": "Перевірка середовища не вдалася.",
  "Backend test failed.": "Перевірка бекенда не вдалася.",
  "Benchmark failed.": "Вимірювання не вдалося.",
  "The worker is not running.": "Робочий процес не запущено.",
  Provider: "Провайдер",
  Device: "Пристрій",
  "Self-test": "Самоперевірка",
  Passed: "Пройдено",
  // Not "Failed": that key already means a failed FILE in the filter bar.
  // Same English word, two meanings -- the one drawback of using source text
  // as the key, and the fix is to say something more precise anyway.
  "Not passed": "Не пройдено",
  "Warm inference": "Гарячий прохід",
  "Benchmark backend": "Бекенд вимірювання",
  "Cold start": "Холодний старт",
  "Average of {runs}": "Середнє з {runs}",
  "Peak RAM": "Пік RAM",
  About: "Про програму",
  Author: "Автор",
  License: "Ліцензія",
  "More projects and services": "Інші проєкти та послуги",
  "Source code": "Вихідний код",
  "More by {author}": "Інші проєкти: {author}",
  "More projects and services by {author}": "Інші проєкти та послуги: {author}",

  // --- environment report ------------------------------------------------
  ok: "ок",
  "too old": "застара",
  ready: "готово",
  "not found": "не знайдено",
  present: "є",
  empty: "порожній",
  "Model cache": "Кеш моделі",
  Config: "Конфігурація",
  ffprobe: "ffprobe",

  // --- onboarding --------------------------------------------------------
  "Welcome to FileSight": "Вітаємо у FileSight",
  Continue: "Продовжити",
  "FileSight analyzes files locally.": "FileSight аналізує файли локально.",
  "The first analysis may download an AI model.":
    "Перший аналіз може завантажити модель.",
  "The model and Python dependencies can use several gigabytes of disk space.":
    "Модель і залежності Python можуть зайняти кілька гігабайтів на диску.",
  "No file is renamed until you confirm the rename plan.":
    "Жоден файл не перейменовується, поки ви не підтвердите план.",
};

const DICTIONARIES: Record<Language, Record<string, string>> = {
  uk: UK,
  en: {},
};

let current: Language = "en";
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

/** Translate, filling `{name}` placeholders from `values`. */
export function t(text: string, values?: Record<string, string | number>): string {
  const translated = DICTIONARIES[current][text] ?? text;
  if (!values) return translated;
  return translated.replace(/\{(\w+)\}/g, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : whole,
  );
}

export function getLanguage(): Language {
  return current;
}

export function setLanguage(language: Language, remember = true): void {
  if (language === current) return;
  current = language;
  applyLanguage(language);
  if (remember) storeLanguage(language);
  notify();
}

/** Called once at start-up, before the first render. */
export function initLanguage(): Language {
  current = initialLanguage();
  applyLanguage(current);
  return current;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Re-render a component when the language changes.
 *
 * Components call `useTranslation()` and then `t(...)`: the hook exists for
 * the subscription, not to hand out a different `t`, so a stray `t()` in a
 * helper outside React still returns the right language.
 */
export function useTranslation(): { t: typeof t; language: Language } {
  const language = useSyncExternalStore(subscribe, getLanguage, getLanguage);
  return { t, language };
}
