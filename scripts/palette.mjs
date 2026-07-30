/**
 * Read the desktop app's two colour palettes out of its stylesheet.
 *
 * The themes are CSS variables, so the stylesheet is the source of truth and
 * the only place these invariants can honestly be checked. It is not done in
 * the component test suite: jsdom does not apply Tailwind, and vitest is
 * configured with `css: false`, which stubs CSS imports out entirely -- a
 * check that reads an empty string and passes is worse than no check.
 */

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
export const STYLESHEET = join(repoRoot, 'desktop', 'src', 'index.css');

export const FAMILIES = ['slate', 'red', 'amber', 'emerald', 'indigo', 'blue'];
export const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];

/** `{ "slate-500": [100, 116, 139], … }` for one theme selector. */
export function palette(selector, css = readFileSync(STYLESHEET, 'utf8')) {
  const parts = css.split(selector);
  if (parts.length < 2) throw new Error(`selector not found in stylesheet: ${selector}`);
  const body = parts[1].split('}')[0];
  const out = {};
  for (const match of body.matchAll(/--c-([a-z]+-\d+): ([\d ]+);/g)) {
    out[match[1]] = match[2].trim().split(/\s+/).map(Number);
  }
  return out;
}

function channel(value) {
  const v = value / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminance([r, g, b]) {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio between two `[r, g, b]` colours. */
export function contrast(foreground, background) {
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

export const THEMES = {
  light: ':root {',
  dark: '.dark {',
};
