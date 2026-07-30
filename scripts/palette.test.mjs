/**
 * The desktop app's colour themes (`node --test scripts/`).
 *
 * Two invariants, both learned the hard way from a screenshot of a status
 * badge that was light green text on light green: every shade must exist in
 * both themes, and the pairs the UI actually puts together must be readable.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { FAMILIES, SHADES, THEMES, contrast, palette } from './palette.mjs';

const themes = Object.fromEntries(
  Object.entries(THEMES).map(([name, selector]) => [name, palette(selector)]),
);

for (const [name, table] of Object.entries(themes)) {
  test(`${name}: every shade of every family is defined`, () => {
    // A shade left out does not fail loudly. It quietly keeps Tailwind's own
    // value, so a background can stay light while the text on it follows the
    // theme and turns light too. The class that breaks is whichever one
    // somebody types next, which is why the whole ramp is required.
    for (const family of FAMILIES) {
      for (const shade of SHADES) {
        assert.ok(table[`${family}-${shade}`], `${name}: --c-${family}-${shade} is missing`);
      }
    }
  });

  test(`${name}: status badges are readable`, () => {
    for (const family of ['emerald', 'red', 'amber']) {
      const ratio = contrast(table[`${family}-800`], table[`${family}-100`]);
      assert.ok(
        ratio >= 4.5,
        `${name}: ${family}-800 on ${family}-100 is ${ratio.toFixed(2)}:1, below 4.5:1`,
      );
    }
  });

  test(`${name}: body text is readable on the page background`, () => {
    const ratio = contrast(table['slate-900'], table['slate-100']);
    assert.ok(ratio >= 4.5, `${name}: ${ratio.toFixed(2)}:1, below 4.5:1`);
  });

  test(`${name}: muted text is still readable on a panel`, () => {
    // `text-slate-500` on a panel is the most common pairing in the app; it
    // is allowed to be quieter than body text, but not decorative.
    const ratio = contrast(table['slate-500'], table['slate-50']);
    assert.ok(ratio >= 4.5, `${name}: ${ratio.toFixed(2)}:1, below 4.5:1`);
  });
}

test('the two themes are genuinely different', () => {
  // Guards against a copy-paste that leaves one theme pointing at the other's
  // values, which would look like "dark mode does nothing".
  assert.notDeepEqual(themes.light['slate-100'], themes.dark['slate-100']);
  assert.notDeepEqual(themes.light['slate-900'], themes.dark['slate-900']);
});
