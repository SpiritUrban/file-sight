/**
 * Theme and interface language.
 *
 * These are the parts that decide what the user sees before anything else
 * loads, so the tests are about the decisions, not about pixels: which theme
 * a fresh install starts in, whose choice wins, and whether a broken stored
 * value can take the app down with it.
 */

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
