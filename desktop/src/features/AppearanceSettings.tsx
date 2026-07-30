import { Languages, Moon, Sun } from "lucide-react";
import { useState } from "react";

import { setLanguage, useTranslation, type Language } from "@/lib/i18n";
import {
  applyTheme,
  initialTheme,
  storeTheme,
  type Theme,
} from "@/lib/preferences";

/**
 * Theme and interface language.
 *
 * Both apply on click rather than on Save: the effect is the whole feedback,
 * and a theme you cannot see until you press Save is a theme you cannot
 * choose. They are also stored immediately, because they live in
 * localStorage rather than in the settings file Rust writes -- see
 * `lib/preferences.ts` for why.
 */
export function AppearanceSettings() {
  const { t, language } = useTranslation();
  // Language names stay in their own language, never translated: somebody
  // looking at an interface they cannot read needs to recognise the name of
  // the one they can.
  const [theme, setTheme] = useState<Theme>(initialTheme);

  const chooseTheme = (next: Theme) => {
    setTheme(next);
    applyTheme(next);
    storeTheme(next);
  };

  return (
    <div className="border-t border-slate-200 pt-3">
      <h3 className="mb-2 font-medium">{t("Appearance")}</h3>

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-slate-600">{t("Theme")}</span>
          <div className="flex gap-1" role="group" aria-label={t("Theme")}>
            <Choice
              active={theme === "dark"}
              onClick={() => chooseTheme("dark")}
              icon={<Moon className="h-3.5 w-3.5" aria-hidden />}
              label={t("Dark")}
            />
            <Choice
              active={theme === "light"}
              onClick={() => chooseTheme("light")}
              icon={<Sun className="h-3.5 w-3.5" aria-hidden />}
              label={t("Light")}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-slate-600">{t("Language")}</span>
          <div className="flex gap-1" role="group" aria-label={t("Language")}>
            <Choice
              active={language === "uk"}
              onClick={() => setLanguage("uk" as Language)}
              icon={<Languages className="h-3.5 w-3.5" aria-hidden />}
              label="Українська"
            />
            <Choice
              active={language === "en"}
              onClick={() => setLanguage("en" as Language)}
              icon={<Languages className="h-3.5 w-3.5" aria-hidden />}
              label="English"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/** A toggle marked by more than colour, so the state survives greyscale. */
function Choice({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium transition-colors ${
        active
          ? "bg-blue-600 text-white"
          : "bg-slate-100 text-slate-700 hover:bg-slate-200"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}
