/**
 * Inline filename validation, mirroring src/filesight/validation.py.
 *
 * This is for instant feedback while typing only — the Python core stays
 * the authority and re-checks everything before any file is touched.
 */

export const FORBIDDEN_CHARS = '<>:"/\\|?*';

export const RESERVED_NAMES = new Set([
  "CON", "PRN", "AUX", "NUL",
  ...Array.from({ length: 9 }, (_, i) => `COM${i + 1}`),
  ...Array.from({ length: 9 }, (_, i) => `LPT${i + 1}`),
]);

/** Same practical ceiling the Python side enforces. */
export const MAX_NAME_LENGTH = 255;

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot);
}

/**
 * Returns a human-readable problem, or null when the name is usable.
 * `originalName` supplies the extension that must be preserved.
 */
export function validateFilename(
  name: string,
  originalName: string,
): string | null {
  const trimmed = name ?? "";
  if (!trimmed.trim()) {
    return "The name cannot be empty.";
  }
  if (trimmed.includes("/") || trimmed.includes("\\")) {
    return "The name must be a file name, not a path.";
  }
  if (trimmed === "." || trimmed === "..") {
    return "That is not a valid file name.";
  }
  const forbidden = [...new Set([...trimmed].filter((c) => FORBIDDEN_CHARS.includes(c)))];
  if (forbidden.length > 0) {
    return `Windows does not allow these characters: ${forbidden.join(" ")}`;
  }
  if (!trimmed.replace(/[. ]/g, "")) {
    return "The name cannot be only dots or spaces.";
  }
  if (trimmed !== trimmed.replace(/[. ]+$/, "")) {
    return "The name cannot end with a space or a dot.";
  }
  const base = trimmed.split(".")[0].trim().toUpperCase();
  if (RESERVED_NAMES.has(base)) {
    return `"${base}" is a name Windows reserves.`;
  }
  const expected = extensionOf(originalName);
  const actual = extensionOf(trimmed);
  if (expected && actual.toLowerCase() !== expected.toLowerCase()) {
    return `The extension must stay ${expected}.`;
  }
  if (!actual && expected) {
    return `The name must keep the ${expected} extension.`;
  }
  if (trimmed.length > MAX_NAME_LENGTH) {
    return `The name is too long (${trimmed.length} of ${MAX_NAME_LENGTH} characters).`;
  }
  return null;
}
