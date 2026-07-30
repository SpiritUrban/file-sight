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
        slate: ramp("slate", [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]),
        red: ramp("red", [50, 200, 300, 500, 600, 700, 800, 900]),
        amber: ramp("amber", [300, 500, 700, 800, 900]),
        emerald: ramp("emerald", [500, 700, 800]),
        indigo: ramp("indigo", [200, 400, 500, 800, 900]),
        blue: ramp("blue", [500, 600, 700, 800]),
        // Named for the job rather than a shade: places that must be a solid
        // surface in both themes, where a ramp position would be a guess.
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        "surface-raised": "rgb(var(--c-surface-raised) / <alpha-value>)",
      },
    },
  },
  plugins: [],
};
