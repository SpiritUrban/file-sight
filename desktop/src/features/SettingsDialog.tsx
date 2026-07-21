import { useEffect, useState } from "react";

import { Dialog } from "@/components/Dialog";
import {
  chooseFile,
  getAppSettings,
  getLogDirectory,
  openPath,
  saveAppSettings,
} from "@/lib/platform";
import { useAppStore } from "@/stores/appStore";
import type { AppSettings, WorkerEnvironment } from "@/types";

const EMPTY: AppSettings = {
  python_path: null,
  ffmpeg_path: null,
  ffprobe_path: null,
  config_path: null,
  default_profile: "default",
  default_recursive: false,
  default_include_videos: false,
  report_filename: "filesight-report.json",
  last_directory: null,
  last_report_path: null,
  last_log_path: null,
  onboarding_seen: false,
};

function PathField({
  label,
  value,
  onChange,
  onBrowse,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
  onBrowse: () => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-slate-600">{label}</span>
      <span className="flex gap-2">
        <input
          type="text"
          className="field flex-1"
          value={value ?? ""}
          placeholder="auto-detect"
          onChange={(event) => onChange(event.target.value || null)}
        />
        <button type="button" className="btn-secondary" onClick={onBrowse}>
          Browse
        </button>
      </span>
    </label>
  );
}

export function SettingsDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const client = useAppStore((s) => s.client);
  const refreshEnvironment = useAppStore((s) => s.refreshEnvironment);
  const [settings, setSettings] = useState<AppSettings>(EMPTY);
  const [logDir, setLogDir] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<WorkerEnvironment | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      const loaded = await getAppSettings();
      if (loaded) setSettings(loaded);
      setLogDir(await getLogDirectory());
    })();
  }, [open]);

  const patch = (changes: Partial<AppSettings>) =>
    setSettings((current) => ({ ...current, ...changes }));

  const runTest = async () => {
    setTesting(true);
    setTestError(null);
    setTestResult(null);
    try {
      if (!client) throw new Error("The worker is not running.");
      const result = (await client.request("get_environment", {
        ffmpeg_path: settings.ffmpeg_path,
        ffprobe_path: settings.ffprobe_path,
        config: settings.config_path,
      })) as unknown as WorkerEnvironment;
      setTestResult(result);
    } catch (error) {
      setTestError(error instanceof Error ? error.message : "Environment test failed.");
    } finally {
      setTesting(false);
    }
  };

  return (
    <Dialog
      open={open}
      title="Settings"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              void (async () => {
                await saveAppSettings(settings);
                // Re-check so the status bar reflects the new paths at once.
                await refreshEnvironment();
                onClose();
              })();
            }}
          >
            Save settings
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <PathField
          label="Python executable"
          value={settings.python_path}
          onChange={(value) => patch({ python_path: value })}
          onBrowse={async () => {
            const picked = await chooseFile("Python", ["exe"]);
            if (picked) patch({ python_path: picked });
          }}
        />
        <PathField
          label="FFmpeg executable"
          value={settings.ffmpeg_path}
          onChange={(value) => patch({ ffmpeg_path: value })}
          onBrowse={async () => {
            const picked = await chooseFile("FFmpeg", ["exe"]);
            if (picked) patch({ ffmpeg_path: picked });
          }}
        />
        <PathField
          label="ffprobe executable"
          value={settings.ffprobe_path}
          onChange={(value) => patch({ ffprobe_path: value })}
          onBrowse={async () => {
            const picked = await chooseFile("ffprobe", ["exe"]);
            if (picked) patch({ ffprobe_path: picked });
          }}
        />
        <PathField
          label="Config file (filesight.toml)"
          value={settings.config_path}
          onChange={(value) => patch({ config_path: value })}
          onBrowse={async () => {
            const picked = await chooseFile("TOML", ["toml"]);
            if (picked) patch({ config_path: picked });
          }}
        />

        <label className="block">
          <span className="mb-1 block text-slate-600">Default profile</span>
          <input
            type="text"
            className="field w-full"
            value={settings.default_profile}
            onChange={(event) => patch({ default_profile: event.target.value })}
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-slate-600">Report filename</span>
          <input
            type="text"
            className="field w-full"
            value={settings.report_filename}
            onChange={(event) => patch({ report_filename: event.target.value })}
          />
        </label>

        <div className="flex gap-4">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={settings.default_recursive}
              onChange={(event) => patch({ default_recursive: event.target.checked })}
            />
            Recursive by default
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={settings.default_include_videos}
              onChange={(event) =>
                patch({ default_include_videos: event.target.checked })
              }
            />
            Include videos by default
          </label>
        </div>

        <div className="border-t border-slate-200 pt-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void runTest()}
              disabled={testing}
            >
              {testing ? "Testing…" : "Test environment"}
            </button>
            {logDir ? (
              <button
                type="button"
                className="btn-secondary"
                onClick={() => void openPath(logDir)}
              >
                Open logs folder
              </button>
            ) : null}
          </div>

          {testError ? (
            <p role="alert" className="mt-2 text-red-700">
              {testError}
            </p>
          ) : null}

          {testResult ? (
            <dl className="mt-2 space-y-0.5 text-xs">
              <div className="flex justify-between">
                <dt>Python</dt>
                <dd>{testResult.python.version} ({testResult.python.ok ? "ok" : "too old"})</dd>
              </div>
              <div className="flex justify-between">
                <dt>FileSight core</dt>
                <dd>{testResult.filesight.version}</dd>
              </div>
              <div className="flex justify-between">
                <dt>FFmpeg</dt>
                <dd>{testResult.ffmpeg.available ? "ready" : "not found"}</dd>
              </div>
              <div className="flex justify-between">
                <dt>ffprobe</dt>
                <dd>{testResult.ffprobe.available ? "ready" : "not found"}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Model cache</dt>
                <dd>{testResult.model.cached ? "present" : "empty"}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Config</dt>
                <dd>{testResult.config.ok ? testResult.config.source : testResult.config.message}</dd>
              </div>
            </dl>
          ) : null}
        </div>
      </div>
    </Dialog>
  );
}
