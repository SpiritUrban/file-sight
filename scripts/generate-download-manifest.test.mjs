/**
 * Tests for the download manifest (`node --test scripts/`).
 *
 * Asset classification is where the site fails *silently*: a `.rpm` filed
 * under Windows still renders a button, and an "MSI" card pointing at the
 * `.exe` looks perfectly fine until someone clicks it. Names below are the
 * real shapes Tauri and GitHub produce -- note `File.Sight`, because GitHub
 * replaces the space in `productName`.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buildManifest, classify, isDownloadable } from './generate-download-manifest.mjs';

test('platform comes from the extension, not from a word in the name', () => {
  // `.rpm` and `.app.tar.gz` contain no platform word at all.
  assert.equal(classify('File.Sight-0.6.0-1.x86_64.rpm').platform, 'linux');
  assert.equal(classify('File.Sight.app.tar.gz').platform, 'macos');
  assert.equal(classify('File.Sight_0.6.0_amd64.deb').platform, 'linux');
  assert.equal(classify('File.Sight_0.6.0_amd64.AppImage').platform, 'linux');
  assert.equal(classify('File.Sight_0.6.0_x64-setup.exe').platform, 'windows');
  assert.equal(classify('File.Sight_0.6.0_x64_en-US.msi').platform, 'windows');
  assert.equal(classify('File.Sight_0.6.0_aarch64.dmg').platform, 'macos');
});

test('architecture is read from the name', () => {
  assert.equal(classify('File.Sight_0.6.0_aarch64.dmg').architecture, 'arm64');
  assert.equal(classify('File.Sight_0.6.0_arm64.AppImage').architecture, 'arm64');
  assert.equal(classify('File.Sight_0.6.0_x64-setup.exe').architecture, 'x64');
});

test('the suffix is exposed so a card cannot match the wrong package', () => {
  // Windows ships two packages and Linux ships two; platform plus
  // architecture is not a unique key.
  const exe = classify('File.Sight_0.6.0_x64-setup.exe');
  const msi = classify('File.Sight_0.6.0_x64_en-US.msi');
  assert.equal(exe.platform, msi.platform);
  assert.equal(exe.architecture, msi.architecture);
  assert.notEqual(exe.extension, msi.extension);
  assert.equal(exe.extension, '.exe');
  assert.equal(msi.extension, '.msi');
});

test('the longest matching suffix wins over a shorter one', () => {
  assert.equal(classify('File.Sight.app.tar.gz').extension, '.app.tar.gz');
  assert.equal(classify('File.Sight_0.6.0_x64-setup.nsis.zip').extension, '.nsis.zip');
});

test('signatures and the updater manifest are not downloads', () => {
  assert.equal(isDownloadable('File.Sight_0.6.0_x64-setup.exe'), true);
  assert.equal(isDownloadable('File.Sight_0.6.0_x64-setup.exe.sig'), false);
  assert.equal(isDownloadable('latest.json'), false);
  assert.equal(isDownloadable('LATEST.JSON'), false);
});

test('a release payload becomes a manifest with the tag as the version', () => {
  const manifest = buildManifest({
    url: 'https://api.github.com/x',
    reason: null,
    data: {
      tag_name: 'v1.2.3',
      html_url: 'https://github.com/o/r/releases/tag/v1.2.3',
      published_at: '2026-07-30T00:00:00Z',
      assets: [
        {
          name: 'File.Sight_1.2.3_x64-setup.exe',
          browser_download_url: 'https://x/setup.exe',
          size: 12,
        },
        {
          name: 'File.Sight_1.2.3_x64-setup.exe.sig',
          browser_download_url: 'https://x/setup.exe.sig',
          size: 1,
        },
        { name: 'latest.json', browser_download_url: 'https://x/latest.json', size: 1 },
      ],
    },
  });

  assert.equal(manifest.version, '1.2.3');
  assert.equal(manifest.hasRelease, true);
  assert.equal(manifest.assets.length, 1, '.sig and latest.json must be filtered out');
  assert.equal(manifest.assets[0].fileName, 'File.Sight_1.2.3_x64-setup.exe');
});

test('with no release the manifest is empty and points at the releases page', () => {
  const manifest = buildManifest({
    url: 'https://api.github.com/x',
    reason: 'no release found',
    data: null,
  });

  assert.equal(manifest.hasRelease, false);
  assert.deepEqual(manifest.assets, [], 'file names must never be invented');
  assert.match(manifest.releaseUrl, /\/releases$/);
  assert.match(manifest.version, /^\d+\.\d+\.\d+/, 'falls back to package.json');
});
