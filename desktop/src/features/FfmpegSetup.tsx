import { Download, Loader2 } from "lucide-react";
import { useState } from "react";

import { useAppStore } from "@/stores/appStore";

/**
 * One-click FFmpeg download (rule 29).
 *
 * "Install FFmpeg and add it to PATH" is the barrier most people never get
 * past, so wherever FileSight would otherwise print a passive warning it
 * offers this action instead. The worker downloads into a per-user
 * directory that the resolver already searches, so video support switches
 * on without a restart.
 *
 * The frontend passes no URL and no destination: it can only ask for the
 * `download_ffmpeg` command, and Rust and Python decide the rest.
 */
export function FfmpegDownloadButton({ compact = false }: { compact?: boolean }) {
  const client = useAppStore((s) => s.client);
  const refreshEnvironment = useAppStore((s) => s.refreshEnvironment);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const busy = stage !== null;

  const run = async () => {
    if (!client) {
      setError("The analysis worker is not running yet.");
      return;
    }
    setError(null);
    setDone(null);
    setStage("starting");
    try {
      const result = (await client.request(
        "download_ffmpeg",
        { tools: ["ffmpeg", "ffprobe"] },
        (event) => {
          if (event.event === "progress") {
            const data = event.data as { tool?: string; stage?: string };
            setStage(`${data.stage ?? "working"} ${data.tool ?? ""}`.trim());
          }
        },
      )) as { directory?: string; version?: string };
      setDone(result.directory ?? null);
      // The environment pill must stop saying "Not found" immediately.
      await refreshEnvironment();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The download failed.");
    } finally {
      setStage(null);
    }
  };

  return (
    <span className={compact ? "inline-flex items-center gap-2" : "block"}>
      <button
        type="button"
        className={compact ? "btn-secondary !py-0.5 !text-xs" : "btn-secondary"}
        onClick={() => void run()}
        disabled={busy}
        title="Downloads a static FFmpeg build into FileSight's own folder. Nothing else on the system is changed."
      >
        {busy ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <Download className="h-4 w-4" aria-hidden />
        )}
        {busy ? `${stage}…` : "Download FFmpeg automatically"}
      </button>

      {error ? (
        <span role="alert" className="ml-2 text-xs text-red-700">
          {error}
        </span>
      ) : null}
      {done && !compact ? (
        <span className="ml-2 break-all text-xs text-emerald-700">
          Installed in {done}
        </span>
      ) : null}
      {done && compact ? (
        <span className="text-xs text-emerald-700">Installed</span>
      ) : null}
    </span>
  );
}
