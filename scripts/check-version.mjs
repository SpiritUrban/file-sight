#!/usr/bin/env node
/**
 * Assert that every file carrying the version agrees -- and, on a tag run,
 * that they agree with the tag name too.
 *
 * This runs as the first job of the release workflow. A version mismatch
 * caught here costs 20 seconds; caught after the release is published it
 * costs a tag that must not be moved (rule 13).
 */

import { SEMVER, readVersions } from './version-files.mjs';

const entries = readVersions();
const problems = [];

for (const entry of entries) {
  const shown = entry.version ?? `?? (${entry.problem})`;
  console.log(`${shown.padEnd(24)} ${entry.file}`);
  if (entry.problem) problems.push(`${entry.file}: ${entry.problem}`);
}

const versions = new Set(entries.filter((e) => e.version).map((e) => e.version));
if (versions.size > 1) {
  problems.push(`files disagree: ${[...versions].sort().join(' != ')}`);
}

// Only a real tag ref constrains the version. On a branch push or a manual
// dispatch GITHUB_REF_NAME is a branch name and must be ignored, otherwise
// the dry-run release (phase F step 3) could never pass.
const ref = process.env.GITHUB_REF_NAME ?? '';
const isTag = /^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)*$/.test(ref);
if (isTag) {
  const tagVersion = ref.slice(1);
  console.log(`\ntag ${ref} -> expected version ${tagVersion}`);
  for (const entry of entries) {
    if (entry.version && entry.version !== tagVersion) {
      problems.push(`${entry.file} is ${entry.version}, but the tag says ${tagVersion}`);
    }
  }
} else if (ref) {
  console.log(`\nref "${ref}" is not a version tag; only cross-file agreement is checked.`);
}

const single = [...versions][0];
if (single && !SEMVER.test(single)) {
  problems.push(`"${single}" is not a plain x.y.z version`);
}

if (problems.length > 0) {
  console.error('\nversion check FAILED:');
  for (const problem of problems) console.error(`  - ${problem}`);
  console.error('\nFix with:  node scripts/sync-version.mjs <version>');
  process.exit(1);
}

console.log(`\nversion check OK: ${single}`);
