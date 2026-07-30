/**
 * Theme and interface language.
 *
 * These are the parts that decide what the user sees before anything else
 * loads, so the tests are about the decisions, not about pixels: which theme
 * a fresh install starts in, whose choice wins, and whether a broken stored
 * value can take the app down with it.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { AppearanceSettings } from "@/features/AppearanceSettings";
import { getLanguage, initLanguage, setLanguage, t } from "@/lib/i18n";
import { applyTheme, initialLanguage, initialTheme } from "@/lib/preferences";

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.className = "";
  setLanguage("en", false);
});

describe("theme", () => {
  it("starts dark on a fresh install", () => {
    // The product's own look. Deliberately not taken from the OS: a machine
    // set to light would otherwise never show it.
    expect(initialTheme()).toBe("dark");
  });

  it("honours a stored choice over the default", () => {
    window.localStorage.setItem("filesight.theme", "light");
    expect(initialTheme()).toBe("light");
  });

  it("ignores a stored value that is not a theme", () => {
    window.localStorage.setItem("filesight.theme", "solarized");
    expect(initialTheme()).toBe("dark");
  });

  it("puts the class Tailwind reads on the document", () => {
    applyTheme("dark");
    expect(document.documentElement).toHaveClass("dark");
    applyTheme("light");
    expect(document.documentElement).not.toHaveClass("dark");
  });
});

describe("language", () => {
  it("prefers an explicit stored choice to the browser", () => {
    window.localStorage.setItem("filesight.language", "en");
    expect(initialLanguage()).toBe("en");
  });

  it("remembers what it detected, so the answer is stable next start", () => {
    expect(window.localStorage.getItem("filesight.language")).toBeNull();
    const detected = initialLanguage();
    expect(window.localStorage.getItem("filesight.language")).toBe(detected);
  });

  it("falls back to English rather than guessing from a related language", () => {
    // Only `uk` means Ukrainian. Anything else is a guess about who reads what.
    window.localStorage.setItem("filesight.language", "de");
    expect(initialLanguage()).toBe("en");
  });

  it("survives storage being unavailable", () => {
    const original = window.localStorage.getItem;
    window.localStorage.getItem = () => {
      throw new Error("storage disabled");
    };
    try {
      expect(() => initLanguage()).not.toThrow();
    } finally {
      window.localStorage.getItem = original;
    }
  });
});

describe("translation", () => {
  it("returns the English source when nothing is translated", () => {
    setLanguage("en", false);
    expect(t("Choose folder")).toBe("Choose folder");
  });

  it("translates into Ukrainian", () => {
    setLanguage("uk", false);
    expect(t("Choose folder")).toBe("Вибрати теку");
    setLanguage("en", false);
  });

  it("fills placeholders", () => {
    setLanguage("uk", false);
    expect(t("{enabled} of {total} selected for rename", { enabled: 2, total: 7 })).toBe(
      "2 з 7 вибрано для перейменування",
    );
    setLanguage("en", false);
  });

  it("falls back to the English source for an untranslated string", () => {
    setLanguage("uk", false);
    expect(t("a string nobody has translated")).toBe("a string nobody has translated");
    setLanguage("en", false);
  });
});

describe("the appearance controls", () => {
  it("switches the theme on click, without waiting for Save", async () => {
    const user = userEvent.setup();
    applyTheme("dark");
    render(<AppearanceSettings />);

    await user.click(screen.getByRole("button", { name: /light/i }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(window.localStorage.getItem("filesight.theme")).toBe("light");

    await user.click(screen.getByRole("button", { name: /dark/i }));
    expect(document.documentElement).toHaveClass("dark");
  });

  it("switches the language and re-renders the labels around it", async () => {
    const user = userEvent.setup();
    setLanguage("en", false);
    render(<AppearanceSettings />);

    expect(screen.getByText("Appearance")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Українська/ }));

    expect(getLanguage()).toBe("uk");
    expect(screen.getByText("Вигляд")).toBeInTheDocument();
    setLanguage("en", false);
  });

  it("marks the active choice by more than colour", () => {
    applyTheme("dark");
    render(<AppearanceSettings />);
    expect(screen.getByRole("button", { name: /dark/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /light/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

describe("the colour palettes", () => {
  // Read the stylesheet rather than the rendered page: jsdom does not apply
  // Tailwind, and the question here is whether the two themes DEFINE a
  // readable pair, which is exactly what the CSS says.
  // `import.meta.url` is an http URL under Vite's test transform, not a file
  // one, so the path is resolved from the working directory instead.
  const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

  function palette(selector: string): Record<string, [number, number, number]> {
    const body = css.split(selector)[1].split("}")[0];
    const out: Record<string, [number, number, number]> = {};
    for (const match of body.matchAll(/--c-([a-z]+-\d+): ([\d ]+);/g)) {
      const [r, g, b] = match[2].trim().split(/\s+/).map(Number);
      out[match[1]] = [r, g, b];
    }
    return out;
  }

  function contrast(fg: [number, number, number], bg: [number, number, number]) {
    const luminance = ([r, g, b]: [number, number, number]) => {
      const channel = (v: number) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    };
    const a = luminance(fg);
    const b = luminance(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  }

  const themes = { light: palette(":root {"), dark: palette(".dark {") };
  const families = ["slate", "red", "amber", "emerald", "indigo", "blue"];
  const shades = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];

  it.each(Object.keys(themes))("defines every shade in the %s theme", (name) => {
    // A shade left undefined silently falls back to Tailwind's own value,
    // which is how a light-green badge ended up with light-green text.
    const table = themes[name as keyof typeof themes];
    for (const family of families) {
      for (const shade of shades) {
        expect(table[`${family}-${shade}`], `${name}: ${family}-${shade}`).toBeDefined();
      }
    }
  });

  it.each(Object.keys(themes))("keeps status badges readable in %s", (name) => {
    const table = themes[name as keyof typeof themes];
    for (const family of ["emerald", "red", "amber"]) {
      const ratio = contrast(table[`${family}-800`], table[`${family}-100`]);
      expect(ratio, `${name}: ${family}-800 on ${family}-100`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps body text readable on the page background in both themes", () => {
    for (const [name, table] of Object.entries(themes)) {
      const ratio = contrast(table["slate-900"], table["slate-100"]);
      expect(ratio, name).toBeGreaterThanOrEqual(4.5);
    }
  });
});
