/** @type {import('tailwindcss').Config} */

/**
 * The colour scales are CSS variables rather than fixed values, so a theme is
 * a change of variables and not a change of markup.
 *
 * The alternative was a `dark:` variant beside each of the 159 colour classes
 * in the components. That is 159 chances to forget one, and every new line of
 * UI written afterwards is a 160th. Here the ramp itself flips: in dark mode
 * the low numbers become dark surfaces and the high numbers become light text,
 * which is what those numbers already mean relative to one another.
 *
 * `<alpha-value>` requires the variables to hold bare `R G B` channels, which
 * is why they are not written as hex.
 */
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];

const ramp = (name, shades) =>
  Object.fromEntries(
    shades.map((shade) => [shade, `rgb(var(--c-${name}-${shade}) / <alpha-value>)`]),
  );

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Every shade, not just the ones in use today. Mapping only the
        // shades a grep found left `bg-emerald-100` on Tailwind's default
        // light green while `text-emerald-800` followed the theme: light on
        // light, unreadable, and invisible until someone looked at a status
        // badge. A partial ramp is a trap for the next person too, because
        // the class that breaks is the one they just typed.
        slate: ramp("slate", SHADES),
        red: ramp("red", SHADES),
        amber: ramp("amber", SHADES),
        emerald: ramp("emerald", SHADES),
        indigo: ramp("indigo", SHADES),
        blue: ramp("blue", SHADES),
        // Named for the job rather than a shade: places that must be a solid
        // surface in both themes, where a ramp position would be a guess.
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        "surface-raised": "rgb(var(--c-surface-raised) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
