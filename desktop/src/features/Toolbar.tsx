import { FolderOpen, Play, Settings, X } from "lucide-react";

import { AuthorLink } from "@/features/AuthorLink";
import { isBusy, useAppStore } from "@/stores/appStore";

interface ToolbarProps {
  onChooseFolder: () => void;
  onOpenSettings: () => void;
}

export function Toolbar({ onChooseFolder, onOpenSettings }: ToolbarProps) {
  const options = useAppStore((s) => s.options);
  const setOptions = useAppStore((s) => s.setOptions);
  const profiles = useAppStore((s) => s.profiles);
  const uiState = useAppStore((s) => s.uiState);
  const startScan = useAppStore((s) => s.startScan);
  const cancelScan = useAppStore((s) => s.cancelScan);

  const busy = isBusy(uiState);
  const scanning =
    uiState === "scanning" || uiState === "analyzing" || uiState === "loading_model";
  const canStart = Boolean(options.directory) && !busy &&
    (options.includeImages || options.includeVideos);

  return (
    <div className="panel space-y-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-secondary"
          onClick={onChooseFolder}
          disabled={busy}
        >
          <FolderOpen className="h-4 w-4" aria-hidden />
          Choose folder
        </button>
        <span
          className="min-w-0 flex-1 truncate text-sm text-slate-600"
          title={options.directory}
        >
          {options.directory || "No folder selected"}
        </span>

        {scanning || uiState === "cancelling" ? (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => void cancelScan()}
            disabled={uiState === "cancelling"}
          >
            <X className="h-4 w-4" aria-hidden />
            {uiState === "cancelling" ? "Cancelling…" : "Cancel"}
          </button>
        ) : (
          <button
            type="button"
            className="btn-primary"
            onClick={() => void startScan()}
            disabled={!canStart}
          >
            <Play className="h-4 w-4" aria-hidden />
            Start analysis
          </button>
        )}

        <button
          type="button"
          className="btn-secondary"
          onClick={onOpenSettings}
          aria-label="Settings"
        >
          <Settings className="h-4 w-4" aria-hidden />
        </button>

        {/* Right after Settings: the reference placement, adapted to a
            toolbar because this app has no sidebar. */}
        <AuthorLink />
      </div>

      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-1.5">
          <span className="text-slate-600">Profile</span>
          <select
            className="field"
            value={options.profile}
            disabled={busy}
            onChange={(event) => setOptions({ profile: event.target.value })}
          >
            {profiles.length === 0 ? (
              <option value={options.profile}>{options.profile}</option>
            ) : (
              profiles.map((profile) => (
                <option key={profile.name} value={profile.name}>
                  {profile.name}
                </option>
              ))
            )}
          </select>
        </label>

        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={options.includeImages}
            disabled={busy}
            onChange={(event) => setOptions({ includeImages: event.target.checked })}
          />
          Images
        </label>

        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={options.includeVideos}
            disabled={busy}
            onChange={(event) => setOptions({ includeVideos: event.target.checked })}
          />
          Videos
        </label>

        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={options.recursive}
            disabled={busy}
            onChange={(event) => setOptions({ recursive: event.target.checked })}
          />
          Recursive
        </label>

        <label className="flex items-center gap-1.5">
          <span className="text-slate-600">Max files</span>
          <input
            type="number"
            min={1}
            className="field w-20"
            disabled={busy}
            value={options.maxFiles ?? ""}
            placeholder="all"
            onChange={(event) =>
              setOptions({
                maxFiles: event.target.value ? Number(event.target.value) : null,
              })
            }
          />
        </label>

        {options.includeVideos ? (
          <label className="flex items-center gap-1.5">
            <span className="text-slate-600">Frames/video</span>
            <input
              type="number"
              min={1}
              max={20}
              className="field w-16"
              disabled={busy}
              value={options.videoFrames}
              onChange={(event) =>
                setOptions({ videoFrames: Number(event.target.value) || 6 })
              }
            />
          </label>
        ) : null}
      </div>
    </div>
  );
}
