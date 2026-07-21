import { CheckCircle2, Film, ImageIcon, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { useAppStore, type LiveResult } from "@/stores/appStore";

/** Local paths must be converted before a webview may load them. */
function useAssetUrl(path: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (!path) {
      setUrl(null);
      return;
    }
    void (async () => {
      try {
        const core = await import("@tauri-apps/api/core");
        if (!cancelled) setUrl(core.convertFileSrc(path));
      } catch {
        if (!cancelled) setUrl(path);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [path]);
  return url;
}

function ResultLine({ result }: { result: LiveResult }) {
  const failed = result.status !== "success";
  return (
    <li className="flex items-start gap-1.5 text-xs">
      {failed ? (
        <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" aria-hidden />
      ) : (
        <CheckCircle2
          className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500"
          aria-hidden
        />
      )}
      <span className="min-w-0">
        <span className="text-slate-500">{result.name}</span>
        <span className="mx-1 text-slate-400">→</span>
        <span className="break-all font-medium">
          {result.suggestedName ?? result.error ?? result.status}
        </span>
      </span>
    </li>
  );
}

/**
 * The stage shown while an analysis runs: a large preview of the file
 * being worked on, its sub-step progress, and the values as they are
 * determined. Replaces the empty screen so the app never looks frozen.
 */
export function LiveStage() {
  const progress = useAppStore((s) => s.progress);
  const uiState = useAppStore((s) => s.uiState);
  const previewUrl = useAssetUrl(progress.currentThumbnail);

  const loadingModel = uiState === "loading_model";
  const hasStep = progress.stepTotal > 0;
  const stepPercent = hasStep
    ? Math.min(100, Math.round((progress.stepCurrent / progress.stepTotal) * 100))
    : 0;
  const result = progress.lastResult;

  return (
    <section
      className="panel flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-6"
      aria-label="Analysis in progress"
    >
      {loadingModel ? (
        <div className="text-center">
          <div
            className="mx-auto mb-3 h-2 w-56 overflow-hidden rounded bg-slate-200"
            role="progressbar"
            aria-label="Loading the model"
          >
            <div className="h-full w-1/3 animate-pulse rounded bg-blue-600" />
          </div>
          <p className="font-medium">Loading the AI model…</p>
          <p className="mt-1 text-sm text-slate-500">
            This happens once per session. The first ever run also downloads it.
          </p>
        </div>
      ) : (
        <>
          {/* Large preview of the file being analyzed */}
          <div className="flex h-64 w-64 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
            {previewUrl ? (
              <img
                src={previewUrl}
                alt={`Preview of ${progress.currentFile ?? "the current file"}`}
                className="h-full w-full object-contain"
              />
            ) : progress.currentMediaType === "video" ? (
              <Film className="h-16 w-16 text-slate-300" aria-hidden />
            ) : (
              <ImageIcon className="h-16 w-16 text-slate-300" aria-hidden />
            )}
          </div>

          <div className="w-full max-w-xl text-center">
            <p className="truncate font-medium" title={progress.currentFile ?? ""}>
              {progress.currentFile ?? "Preparing…"}
            </p>
            <p className="text-sm text-slate-500">
              File {progress.currentIndex || progress.completed} of {progress.total}
              {progress.currentMediaType === "video" ? " · video" : ""}
            </p>

            {/* Per-file progress: exact for videos, animated for images */}
            <div
              className="mx-auto mt-3 h-1.5 w-full overflow-hidden rounded bg-slate-200"
              role="progressbar"
              aria-label="Current file progress"
              aria-valuenow={hasStep ? stepPercent : undefined}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={`h-full rounded bg-blue-500 ${hasStep ? "" : "w-1/3 animate-pulse"}`}
                style={hasStep ? { width: `${stepPercent}%` } : undefined}
              />
            </div>
            <p className="mt-1 h-4 text-xs text-slate-500">
              {progress.stepLabel
                ? `${progress.stepLabel} ${progress.stepCurrent}/${progress.stepTotal}`
                : uiState === "cancelling"
                  ? "Cancelling…"
                  : "Analyzing…"}
            </p>

            {/* Values appear as soon as the file is done */}
            <div className="mt-4 min-h-[5.5rem] rounded-md border border-slate-200 bg-slate-50 p-3 text-left">
              {result ? (
                <dl className="space-y-1 text-sm">
                  {result.caption ? (
                    <div>
                      <dt className="text-xs text-slate-500">Caption</dt>
                      <dd>{result.caption}</dd>
                    </div>
                  ) : null}
                  {result.category ? (
                    <div>
                      <dt className="text-xs text-slate-500">Category</dt>
                      <dd>{result.category}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt className="text-xs text-slate-500">New name</dt>
                    <dd className="break-all font-medium text-blue-800">
                      {result.suggestedName ?? result.error ?? "—"}
                    </dd>
                  </div>
                </dl>
              ) : (
                <p className="text-sm text-slate-400">
                  Waiting for the result of this file…
                </p>
              )}
            </div>
          </div>

          {progress.recent.length > 1 ? (
            <ul className="w-full max-w-xl space-y-0.5 border-t border-slate-200 pt-2">
              {progress.recent.slice(1).map((item, index) => (
                <ResultLine key={`${item.name}-${index}`} result={item} />
              ))}
            </ul>
          ) : null}
        </>
      )}
    </section>
  );
}
