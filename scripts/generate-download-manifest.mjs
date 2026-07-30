#!/usr/bin/env node
/**
 * Build `site/download-manifest.json` from the GitHub release.
 *
 * The site never hardcodes a file name or a version (rules 15 and 18): Tauri
 * derives bundle names from `productName` and GitHub replaces spaces with
 * dots, so any name written by hand is wrong the first time the product is
 * renamed -- and a hardcoded version is wrong the moment a release is cut.
 *
 * Run with no arguments; configuration comes from the environment:
 *   GITHUB_REF_NAME   a tag (`v1.2.3`) pins that release; anything else
 *                     falls back to the latest published release
 *   GITHUB_TOKEN      lifts the 60-requests/hour-per-IP anonymous limit
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const OWNER = 'SpiritUrban';
const REPO = 'file-sight';
const OUTPUT = join(repoRoot, 'site', 'download-manifest.json');

const RELEASES_URL = `https://github.com/${OWNER}/${REPO}/releases`;

/** Assets that are not builds and must never appear as a download (rule 17). */
export function isDownloadable(name) {
  const lower = name.toLowerCase();
  if (lower.endsWith('.sig')) return false;
  if (lower === 'latest.json') return false;
  return true;
}

/**
 * Classify an asset by its file extension first (rule 16).
 *
 * `.rpm` and `.app.tar.gz` carry no platform word at all, so a name-based
 * guess silently files them under Windows.
 */
export function classify(name) {
  const lower = name.toLowerCase();

  let platform = null;
  if (lower.endsWith('.dmg') || lower.endsWith('.app.tar.gz')) platform = 'macos';
  else if (
    lower.endsWith('.appimage') ||
    lower.endsWith('.appimage.tar.gz') ||
    lower.endsWith('.deb') ||
    lower.endsWith('.rpm')
  ) {
    platform = 'linux';
  } else if (
    lower.endsWith('.exe') ||
    lower.endsWith('.msi') ||
    lower.endsWith('.nsis.zip') ||
    lower.endsWith('.msi.zip')
  ) {
    platform = 'windows';
  }

  // Only if the extension says nothing does the name get a vote.
  if (!platform) {
    if (lower.includes('macos') || lower.includes('darwin') || lower.includes('apple')) {
      platform = 'macos';
    } else if (lower.includes('linux')) platform = 'linux';
    else if (lower.includes('windows') || lower.includes('win64')) platform = 'windows';
    else platform = 'unknown';
  }

  const architecture =
    lower.includes('aarch64') || lower.includes('arm64')
      ? 'arm64'
      : lower.includes('i686') || lower.includes('x86.') || lower.includes('_x86')
        ? 'x86'
        : 'x64';

  // The suffix a download card matches on: platform + architecture alone is
  // not enough, because Windows ships two packages (.exe and .msi) and Linux
  // ships two as well (.AppImage and .deb) -- an "MSI" card would otherwise
  // link to the .exe.
  const known = [
    '.app.tar.gz',
    '.appimage.tar.gz',
    '.nsis.zip',
    '.msi.zip',
    '.appimage',
    '.dmg',
    '.deb',
    '.rpm',
    '.exe',
    '.msi',
  ];
  const extension = known.find((suffix) => lower.endsWith(suffix)) ?? '';

  return { platform, architecture, extension };
}

function packageVersion() {
  const text = readFileSync(join(repoRoot, 'package.json'), 'utf8');
  return JSON.parse(text).version;
}

async function fetchRelease() {
  const ref = process.env.GITHUB_REF_NAME ?? '';
  const isTag = /^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)*$/.test(ref);
  // A tag run must ask for *that* tag. Asking for `latest` from a tag run is
  // how a release deploy ends up publishing the previous version's manifest.
  const url = isTag
    ? `https://api.github.com/repos/${OWNER}/${REPO}/releases/tags/${ref}`
    : `https://api.github.com/repos/${OWNER}/${REPO}/releases/latest`;

  const headers = {
    'User-Agent': `${REPO}-site-builder`,
    Accept: 'application/vnd.github+json',
  };
  if (process.env.GITHUB_TOKEN) {
    headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  }

  const response = await fetch(url, { headers });
  if (response.status === 404) {
    return { data: null, url, reason: `no release found at ${url}` };
  }
  if (!response.ok) {
    const body = await response.text();
    return {
      data: null,
      url,
      reason: `GitHub API ${response.status}: ${body.slice(0, 300)}`,
    };
  }
  return { data: await response.json(), url, reason: null };
}

/** Turn a release payload (or the absence of one) into the manifest object. */
export function buildManifest({ data, url, reason }) {
  let manifest;
  if (!data) {
    // No release yet (or the API is unreachable). Never invent file names:
    // the buttons must lead to the releases page, not to a 404.
    console.warn(`download manifest: falling back (${reason})`);
  manifest = {
    generatedAt: new Date().toISOString(),
    resolvedFrom: url,
    version: packageVersion(),
    tag: null,
    releaseUrl: RELEASES_URL,
    releasesUrl: RELEASES_URL,
    publishedAt: null,
    hasRelease: false,
    note: reason,
    assets: [],
  };
} else {
  const assets = (data.assets ?? [])
    .filter((asset) => isDownloadable(asset.name))
    .map((asset) => ({
      fileName: asset.name,
      downloadUrl: asset.browser_download_url,
      size: asset.size,
      ...classify(asset.name),
    }))
    .sort((a, b) => a.fileName.localeCompare(b.fileName));

  manifest = {
    generatedAt: new Date().toISOString(),
    resolvedFrom: url,
    // The version comes from the release tag, never from a literal.
    version: String(data.tag_name ?? '').replace(/^v/, '') || packageVersion(),
    tag: data.tag_name ?? null,
    releaseUrl: data.html_url ?? RELEASES_URL,
    releasesUrl: RELEASES_URL,
    publishedAt: data.published_at ?? null,
    hasRelease: true,
    note: null,
    assets,
  };
  }
  return manifest;
}

async function main() {
  const manifest = buildManifest(await fetchRelease());

  mkdirSync(dirname(OUTPUT), { recursive: true });
  writeFileSync(OUTPUT, `${JSON.stringify(manifest, null, 2)}\n`);

  console.log(`download manifest -> ${OUTPUT}`);
  console.log(`  resolved from : ${manifest.resolvedFrom}`);
  console.log(
    `  version       : ${manifest.version}${manifest.hasRelease ? '' : ' (fallback)'}`,
  );
  console.log(`  assets        : ${manifest.assets.length}`);
  for (const asset of manifest.assets) {
    console.log(
      `    ${asset.platform}/${asset.architecture}${asset.extension} ${asset.fileName}`,
    );
  }
}

// Importable for tests, executable as a script.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
