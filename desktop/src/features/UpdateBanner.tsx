import { Download, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useTranslation } from "@/lib/i18n";
import { logMessage } from "@/lib/platform";

/**
 * Update check and install banner (rule 28).
 *
 * The plugin in Cargo.toml and the config in tauri.conf.json only make an
 * update *possible*. Without this component nothing ever calls `check()`,
 * and an installed copy never learns a new version exists.
 *
 * Everything is dynamically imported and every failure is swallowed: a
 * missing network, a 404 endpoint before the first release, or running
 * outside Tauri must all leave the app fully usable.
 */

type Phase = "idle" | "available" | "downloading" | "installing" | "ready" | "failed";

interface UpdateInfo {
  version: string;
  /** The plugin's Update object; typed loosely so the import stays lazy. */
  handle: { downloadAndInstall: (onEvent?: (e: unknown) => void) => Promise<void> };
}

export function UpdateBanner() {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>("idle");
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      try {
        const updater = await import("@tauri-apps/plugin-updater");
        const found = await updater.check();
        if (cancelled || !found) return;
        setUpdate({
          version: found.version,
          handle: found as unknown as UpdateInfo["handle"],
        });
        setPhase("available");
        void logMessage(`update available: ${found.version}`);
      } catch (error) {
        // No endpoint yet, offline, or not running in Tauri. Not worth a
        // visible error: the user did not ask for an update check.
        void logMessage(`update check skipped: ${String(error)}`);
      }
    };

    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  const install = useCallback(async () => {
    if (!update) return;
    setPhase("downloading");
    setDetail(null);
    try {
      await update.handle.downloadAndInstall((event) => {
        const kind = (event as { event?: string } | null)?.event;
        if (kind === "Finished") setPhase("installing");
      });
      setPhase("ready");
      // Windows installers relaunch the app themselves; on Linux/macOS the
      // new version is in place after a restart.
      try {
        const process = await import("@tauri-apps/plugin-process");
        await process.relaunch();
      } catch {
        /* no process plugin: the message below tells the user to restart */
      }
    } catch (error) {
      setPhase("failed");
      setDetail(String(error));
      void logMessage(`update install failed: ${String(error)}`);
    }
  }, [update]);

  if (phase === "idle" || dismissed || !update) return null;

  const busy = phase === "downloading" || phase === "installing";

  return (
    <div
      role="status"
      className="flex items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm"
    >
      <span className="shrink-0" aria-hidden>
        🎉
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-medium text-indigo-900">
          {t("Update available — FileSight {version}", {
            version: update.version,
          })}
        </p>
        {phase === "downloading" ? (
          <p className="text-indigo-800">{t("Downloading…")}</p>
        ) : phase === "installing" ? (
          <p className="text-indigo-800">{t("Installing…")}</p>
        ) : phase === "ready" ? (
          <p className="text-indigo-800">
            {t("Installed. Restart FileSight to use it.")}
          </p>
        ) : phase === "failed" ? (
          <p className="break-all font-mono text-xs text-red-700">{detail}</p>
        ) : null}
      </div>

      {phase !== "ready" ? (
        <button
          type="button"
          className="btn-primary shrink-0"
          onClick={() => void install()}
          disabled={busy}
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Download className="h-4 w-4" aria-hidden />
          )}
          {phase === "failed" ? t("Try again") : t("Update now")}
        </button>
      ) : null}

      <button
        type="button"
        className="btn-secondary shrink-0"
        onClick={() => setDismissed(true)}
        aria-label={t("Dismiss update notice")}
        disabled={busy}
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}
