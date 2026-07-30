#!/usr/bin/env node
/**
 * Write one version into every file that carries it.
 *
 *   node scripts/sync-version.mjs 0.7.0
 *   node scripts/sync-version.mjs v0.7.0     (leading `v` is accepted)
 *
 * Cargo.lock is edited with a regex on purpose: running `cargo update` here
 * would need the network and a full registry index just to change one line,
 * and the release workflow must not depend on that.
 */

import { SEMVER, readVersions, writeVersions } from './version-files.mjs';

const raw = process.argv[2];
if (!raw) {
  const current = readVersions();
  console.error('usage: node scripts/sync-version.mjs <version>');
  console.error('');
  console.error('current:');
  for (const entry of current) {
    console.error(`  ${entry.version ?? `?? (${entry.problem})`}  ${entry.file}`);
  }
  process.exit(2);
}

const version = raw.startsWith('v') ? raw.slice(1) : raw;
if (!SEMVER.test(version)) {
  console.error(`not a version: ${raw} (expected x.y.z)`);
  process.exit(2);
}

const results = writeVersions(version);
for (const result of results) {
  const mark = result.changed ? '->' : '==';
  console.log(`${mark} ${result.label}: ${result.from} ${mark} ${version}`);
}
const changed = results.filter((r) => r.changed).length;
console.log(`\n${changed} file(s) updated, ${results.length - changed} already at ${version}.`);
