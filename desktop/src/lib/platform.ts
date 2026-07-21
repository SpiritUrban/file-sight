/**
 * Thin wrappers over the Tauri APIs the UI is allowed to use.
 *
 * Everything degrades to a no-op outside Tauri so components can be
 * rendered in tests without mocking the whole runtime.
 */
import type { AppSettings, EnvironmentStatus } from "@/types";

async function tauriInvoke<T>(command: string, args?: Record<string, unknown>): Promise<T | null> {
  try {
    const core = await import("@tauri-apps/api/core");
    return (await core.invoke(command, args)) as T;
  } catch {
    return null;
  }
}

export async function chooseDirectory(): Promise<string | null> {
  try {
    const dialog = await import("@tauri-apps/plugin-dialog");
    const selected = await dialog.open({ directory: true, multiple: false });
    return typeof selected === "string" ? selected : null;
  } catch {
    return null;
  }
}

export async function chooseFile(
  name: string,
  extensions: string[],
): Promise<string | null> {
  try {
    const dialog = await import("@tauri-apps/plugin-dialog");
    const selected = await dialog.open({
      multiple: false,
      filters: [{ name, extensions }],
    });
    return typeof selected === "string" ? selected : null;
  } catch {
    return null;
  }
}

/** Open a folder in Explorer. Paths come from our own state, never user text. */
export async function openPath(path: string): Promise<void> {
  if (!path) return;
  try {
    const opener = await import("@tauri-apps/plugin-opener");
    await opener.openPath(path);
  } catch {
    /* not running inside Tauri */
  }
}

/** Reveal a specific file, selecting it in Explorer. */
export async function revealPath(path: string): Promise<void> {
  if (!path) return;
  try {
    const opener = await import("@tauri-apps/plugin-opener");
    await opener.revealItemInDir(path);
  } catch {
    /* not running inside Tauri */
  }
}

export async function getEnvironmentStatus(): Promise<EnvironmentStatus | null> {
  return tauriInvoke<EnvironmentStatus>("get_environment_status");
}

export async function getAppSettings(): Promise<AppSettings | null> {
  return tauriInvoke<AppSettings>("get_app_settings");
}

export async function saveAppSettings(settings: AppSettings): Promise<void> {
  await tauriInvoke("save_app_settings", { settingsValue: settings });
}

export async function getLogDirectory(): Promise<string | null> {
  return tauriInvoke<string>("get_log_directory");
}

export async function logMessage(message: string): Promise<void> {
  await tauriInvoke("log_message", { message });
}
