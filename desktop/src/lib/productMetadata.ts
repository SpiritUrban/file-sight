/**
 * Product and author metadata, defined once.
 *
 * Every surface that shows the author's name (toolbar link, Settings ->
 * About, the empty state) reads it from here, so changing the name or the
 * hub URL is a one-line edit instead of a grep.
 *
 * The version is deliberately absent: it must come from the bundle at
 * runtime via `getAppVersion()`, never from a literal (rule 18).
 */
export const PRODUCT_METADATA = {
  productName: "FileSight",
  author: "Vitaliy Dyachuk",
  /** Personal hub: who the author is and what else he builds. */
  authorUrl: "https://spiriturban.github.io/",
  authorGithubUrl: "https://github.com/SpiritUrban",
  repositoryUrl: "https://github.com/SpiritUrban/file-sight",
  siteUrl: "https://spiriturban.github.io/file-sight/",
  license: "MIT",
  copyright: "Copyright (c) 2026 Vitaliy Dyachuk",
} as const;
