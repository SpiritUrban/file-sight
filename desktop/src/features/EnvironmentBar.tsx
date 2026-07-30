import { FfmpegDownloadButton } from "@/features/FfmpegSetup";
import { useTranslation } from "@/lib/i18n";
import { useAppStore } from "@/stores/appStore";
import type { WorkerEnvironment } from "@/types";

function Pill({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <span className="flex items-center gap-1">
      {/* Status is conveyed by text too, never by colour alone. */}
      <span
        className={`inline-block h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`}
        aria-hidden
      />
      <span className="text-slate-500">{label}:</span>
      <span className={ok ? "text-slate-700" : "font-medium text-red-700"}>{value}</span>
    </span>
  );
}

export function EnvironmentBar() {
  const { t } = useTranslation();
  const environment = useAppStore((s) => s.environment);
  const uiState = useAppStore((s) => s.uiState);

  if (!environment) {
    return (
      <p className="text-xs text-slate-500">
        {uiState === "environment_check"
          ? t("Checking environment…")
          : t("Environment unknown")}
      </p>
    );
  }

  const modelLoaded = environment.model.loaded || uiState === "analyzing";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <Pill
        label={t("Python")}
        value={environment.python.ok ? environment.python.version : t("Not found")}
        ok={environment.python.ok}
      />
      <Pill
        label={t("FileSight core")}
        value={environment.filesight.ok ? t("Ready") : t("Missing")}
        ok={environment.filesight.ok}
      />
      <Pill
        label={t("Model")}
        value={
          uiState === "loading_model"
            ? t("Loading…")
            : modelLoaded
              ? t("Loaded")
              : environment.model.cached
                ? t("Not loaded")
                : t("Not downloaded")
        }
        ok={modelLoaded || Boolean(environment.model.cached)}
      />
      <Pill
        label={t("FFmpeg")}
        value={environment.ffmpeg.available ? t("Ready") : t("Not found")}
        ok={environment.ffmpeg.available}
      />
      {/* Rule 29: where a passive "Not found" would sit, offer the fix. */}
      {environment.ffmpeg.available ? null : <FfmpegDownloadButton compact />}
      <GpuPill inference={environment.inference} />
    </div>
  );
}

/** Names the accelerator that is actually present, or says there is none.
 *
 * Deliberately reports GPU *availability*, not what captioning uses: the
 * footer states the backend that really ran, and the two must never be
 * conflated. */
function GpuPill({
  inference,
}: {
  inference: WorkerEnvironment["inference"];
}) {
  const { t } = useTranslation();
  if (inference?.cuda_available) {
    return (
      <Pill
        label={t("GPU")}
        value={`CUDA · ${inference.cuda_device_name ?? "NVIDIA"}`}
        ok
      />
    );
  }
  if (inference?.directml_available) {
    return (
      <Pill
        label={t("GPU")}
        value={`DirectML · ${inference.gpu_name ?? t("Available")}`}
        ok
      />
    );
  }
  return <Pill label={t("GPU")} value={t("Not available")} ok={false} />;
}
