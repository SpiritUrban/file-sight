/**
 * Shell preferences: theme and interface language.
 *
 * These live in `localStorage`, not in the app settings file that Rust owns,
 * for one reason: they must be applied before the first paint. Settings are
 * read from disk asynchronously after mount, so sourcing the theme from there
 * would show a flash of the light theme on every start, and the wrong
 * language for a frame.
 *
 * Storage can be unavailable (a locked-down profile, a stripped WebView), so
 * every access is guarded. A preference that cannot be saved must degrade to
 * "not remembered", never to a crash.
 */

export type Theme = "dark" | "light";
export type Language = "uk" | "en";

const THEME_KEY = "filesight.theme";
const LANGUAGE_KEY = "filesight.language";

const THEMES: Theme[] = ["dark", "light"];
const LANGUAGES: Language[] = ["uk", "en"];

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* not remembered; the current session still honours the choice */
  }
}

/**
 * The theme to start with.
 *
 * Dark by default, as asked, and deliberately not derived from the operating
 * system: this is the product's own look, and a machine set to light would
 * otherwise never show it.
 */
export function initialTheme(): Theme {
  const stored = read(THEME_KEY) as Theme | null;
  return stored && THEMES.includes(stored) ? stored : "dark";
}

/**
 * The language to start with: a previous explicit choice, else the system's
 * language if it is Ukrainian, else English.
 *
 * Only `uk` maps to Ukrainian. Inferring it from any other language would be
 * a guess about who reads what.
 */
export function initialLanguage(): Language {
  const stored = read(LANGUAGE_KEY) as Language | null;
  if (stored && LANGUAGES.includes(stored)) return stored;

  const tags =
    typeof navigator !== "undefined" && navigator.languages?.length
      ? navigator.languages
      : [typeof navigator !== "undefined" ? navigator.language : ""];
  const detected = tags.some((tag) => String(tag).toLowerCase().startsWith("uk"))
    ? "uk"
    : "en";
  // Remembered straight away, so the answer is stable from the second start
  // even if the system language later changes.
  write(LANGUAGE_KEY, detected);
  return detected;
}

/** Put the theme on the document. Tailwind's `darkMode: "class"` reads this. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.dataset.theme = theme;
}

export function storeTheme(theme: Theme): void {
  write(THEME_KEY, theme);
}

export function applyLanguage(language: Language): void {
  document.documentElement.lang = language;
}

export function storeLanguage(language: Language): void {
  write(LANGUAGE_KEY, language);
}
