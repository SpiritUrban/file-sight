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
  const environment = useAppStore((s) => s.environment);
  const uiState = useAppStore((s) => s.uiState);

  if (!environment) {
    return (
      <p className="text-xs text-slate-500">
        {uiState === "environment_check" ? "Checking environment…" : "Environment unknown"}
      </p>
    );
  }

  const modelLoaded = environment.model.loaded || uiState === "analyzing";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <Pill
        label="Python"
        value={environment.python.ok ? environment.python.version : "Not found"}
        ok={environment.python.ok}
      />
      <Pill
        label="FileSight core"
        value={environment.filesight.ok ? "Ready" : "Missing"}
        ok={environment.filesight.ok}
      />
      <Pill
        label="Model"
        value={
          uiState === "loading_model"
            ? "Loading…"
            : modelLoaded
              ? "Loaded"
              : environment.model.cached
                ? "Not loaded"
                : "Not downloaded"
        }
        ok={modelLoaded || Boolean(environment.model.cached)}
      />
      <Pill
        label="FFmpeg"
        value={environment.ffmpeg.available ? "Ready" : "Not found"}
        ok={environment.ffmpeg.available}
      />
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
  if (inference?.cuda_available) {
    return (
      <Pill
        label="GPU"
        value={`CUDA · ${inference.cuda_device_name ?? "NVIDIA"}`}
        ok
      />
    );
  }
  if (inference?.directml_available) {
    return (
      <Pill
        label="GPU"
        value={`DirectML · ${inference.gpu_name ?? "Available"}`}
        ok
      />
    );
  }
  return <Pill label="GPU" value="Not available" ok={false} />;
}
