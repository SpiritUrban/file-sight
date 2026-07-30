/**
 * The single list of places FileSight's version is written down.
 *
 * Both `sync-version.mjs` and `check-version.mjs` import this list, so a new
 * file that carries the version has to be added in exactly one place.
 *
 * Every target edits the raw text through an anchored regex instead of
 * parsing and re-serializing. Round-tripping JSON would reformat lockfiles
 * and reorder nothing but still produce a huge diff; a regex touches only
 * the version literal.
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');

/** Semver with an optional pre-release suffix (`0.7.0-rc.1`). */
export const SEMVER_SOURCE = '\\d+\\.\\d+\\.\\d+(?:-[0-9A-Za-z.]+)*';
export const SEMVER = new RegExp(`^${SEMVER_SOURCE}$`);

/**
 * `name = "<pkg>"` immediately followed by `version = "..."` -- the shape
 * both Cargo.toml and every `[[package]]` block in Cargo.lock use. Anchoring
 * on the crate name matters: Cargo.lock holds three unrelated crates that
 * also happen to sit at 0.6.0, and a bare version regex would rewrite them.
 */
const cargoPackage = (name) =>
  new RegExp(`(^name = "${name}"\\r?\\nversion = ")(${SEMVER_SOURCE})(")`, 'm');

/** A line-initial `"version": "..."` key in a JSON file. */
const jsonVersionKey = new RegExp(
  `(^[ \\t]*"version":[ \\t]*")(${SEMVER_SOURCE})(")`,
  'm',
);

/** npm lockfiles repeat the root version twice, both times after the name. */
const npmLockVersion = new RegExp(
  `("name":[ \\t]*"filesight-desktop",\\r?\\n[ \\t]*"version":[ \\t]*")(${SEMVER_SOURCE})(")`,
  'g',
);

/**
 * @typedef {object} Target
 * @property {string} label      human name used in messages
 * @property {string} file       path relative to the repo root
 * @property {RegExp} pattern    three capture groups: prefix, version, suffix
 * @property {number} count      how many matches must be present
 */

/** @type {Target[]} */
export const targets = [
  { label: 'package.json', file: 'package.json', pattern: jsonVersionKey, count: 1 },
  {
    label: 'desktop/package.json',
    file: 'desktop/package.json',
    pattern: jsonVersionKey,
    count: 1,
  },
  {
    label: 'desktop/package-lock.json',
    file: 'desktop/package-lock.json',
    pattern: npmLockVersion,
    count: 2,
  },
  {
    label: 'tauri.conf.json',
    file: 'desktop/src-tauri/tauri.conf.json',
    pattern: jsonVersionKey,
    count: 1,
  },
  {
    label: 'Cargo.toml',
    file: 'desktop/src-tauri/Cargo.toml',
    pattern: cargoPackage('filesight-desktop'),
    count: 1,
  },
  {
    label: 'Cargo.lock',
    file: 'desktop/src-tauri/Cargo.lock',
    pattern: cargoPackage('filesight-desktop'),
    count: 1,
  },
  {
    label: 'pyproject.toml',
    file: 'pyproject.toml',
    pattern: cargoPackage('filesight'),
    count: 1,
  },
  {
    label: 'filesight/__init__.py',
    file: 'src/filesight/__init__.py',
    pattern: new RegExp(`(^__version__ = ")(${SEMVER_SOURCE})(")`, 'm'),
    count: 1,
  },
];

function matchesOf(text, pattern) {
  const global = pattern.global
    ? pattern
    : new RegExp(pattern.source, `${pattern.flags}g`);
  return [...text.matchAll(global)];
}

/**
 * Read every target's version.
 *
 * @returns {{label: string, file: string, version: string|null, problem: string|null}[]}
 */
export function readVersions() {
  return targets.map((target) => {
    const path = join(repoRoot, target.file);
    let text;
    try {
      text = readFileSync(path, 'utf8');
    } catch (error) {
      return { ...target, version: null, problem: `cannot read: ${error.message}` };
    }
    const found = matchesOf(text, target.pattern);
    if (found.length !== target.count) {
      return {
        ...target,
        version: null,
        problem: `expected ${target.count} version match(es), found ${found.length}`,
      };
    }
    const versions = new Set(found.map((m) => m[2]));
    if (versions.size !== 1) {
      return {
        ...target,
        version: null,
        problem: `disagrees with itself: ${[...versions].join(', ')}`,
      };
    }
    return { ...target, version: found[0][2], problem: null };
  });
}

/**
 * Write `version` into every target.
 *
 * @param {string} version
 * @returns {{label: string, from: string, to: string, changed: boolean}[]}
 */
export function writeVersions(version) {
  const current = readVersions();
  const broken = current.filter((entry) => entry.problem);
  if (broken.length > 0) {
    const detail = broken.map((e) => `  ${e.file}: ${e.problem}`).join('\n');
    throw new Error(`cannot rewrite versions, some files are unreadable:\n${detail}`);
  }

  return current.map((entry) => {
    const path = join(repoRoot, entry.file);
    const text = readFileSync(path, 'utf8');
    const pattern = entry.pattern.global
      ? entry.pattern
      : new RegExp(entry.pattern.source, `${entry.pattern.flags}g`);
    const updated = text.replace(pattern, (_all, prefix, _old, suffix) =>
      `${prefix}${version}${suffix}`,
    );
    const changed = updated !== text;
    if (changed) {
      // Newline style is whatever the file already used: `.gitattributes`
      // forces LF, and rewriting it here would be an invisible extra diff.
      writeFileSync(path, updated);
    }
    return { label: entry.label, from: entry.version, to: version, changed };
  });
}
