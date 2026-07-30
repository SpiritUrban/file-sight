import { useEffect, useState } from "react";

import { useTranslation } from "@/lib/i18n";
import { useAppStore } from "@/stores/appStore";

function elapsed(startedAt: number | null): string {
  if (!startedAt) return "0:00";
  const seconds = Math.floor((Date.now() - startedAt) / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function ProgressBar() {
  const { t } = useTranslation();
  const progress = useAppStore((s) => s.progress);
  const uiState = useAppStore((s) => s.uiState);
  const [, tick] = useState(0);

  const active =
    uiState === "scanning" ||
    uiState === "analyzing" ||
    uiState === "loading_model" ||
    uiState === "cancelling";

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => tick((value) => value + 1), 1000);
    return () => clearInterval(id);
  }, [active]);

  if (!active) return null;

  // Model download/load has no reliable percentage; show it as indeterminate.
  const indeterminate = uiState === "loading_model" || progress.total === 0;

  return (
    <div className="panel p-3" role="status" aria-live="polite">
      <div className="mb-1.5 flex items-baseline justify-between text-sm">
        <span className="font-medium">
          {progress.phase ? t(progress.phase) : t("Working")}
          {progress.currentFile ? (
            <span className="ml-2 font-normal text-slate-500">
              {progress.currentFile}
            </span>
          ) : null}
        </span>
        <span className="text-slate-600">
          {indeterminate
            ? t("{elapsed} elapsed", { elapsed: elapsed(progress.startedAt) })
            : `${progress.completed} / ${progress.total} · ${progress.percent.toFixed(0)}% · ${elapsed(progress.startedAt)}`}
        </span>
      </div>

      <div
        className="h-2 overflow-hidden rounded bg-slate-200"
        role="progressbar"
        aria-valuenow={indeterminate ? undefined : Math.round(progress.percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={t("Analysis progress")}
      >
        <div
          className={`h-full bg-blue-600 ${indeterminate ? "w-1/3 animate-pulse" : ""}`}
          style={indeterminate ? undefined : { width: `${progress.percent}%` }}
        />
      </div>

      <p className="mt-1 text-xs text-slate-500">
        {progress.succeeded} succeeded · {progress.failed} failed
      </p>
    </div>
  );
}
