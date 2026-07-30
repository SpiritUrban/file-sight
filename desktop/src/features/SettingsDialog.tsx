import { useEffect, useState } from "react";

import { Dialog } from "@/components/Dialog";
import { FfmpegDownloadButton } from "@/features/FfmpegSetup";
import {
  chooseFile,
  getAppSettings,
  getAppVersion,
  getLogDirectory,
  openExternal,
  openPath,
  saveAppSettings,
} from "@/lib/platform";
import { PRODUCT_METADATA } from "@/lib/productMetadata";
import { useAppStore } from "@/stores/appStore";
import type {
  AppSettings,
  BackendDiagnostics,
  BenchmarkResult,
  WorkerEnvironment,
} from "@/types";

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
  backend: "auto",
  allow_fallback: true,
};

const BACKEND_LABELS: Array<{ value: string; label: string }> = [
  { value: "auto", label: "Auto (best available)" },
  { value: "onnx-cuda", label: "NVIDIA GPU (CUDA)" },
  { value: "onnx-directml", label: "AMD / Intel GPU (DirectML)" },
  { value: "onnx-cpu", label: "CPU (ONNX Runtime)" },
  { value: "pytorch-cpu", label: "CPU (PyTorch)" },
];

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
  const [backendDiag, setBackendDiag] = useState<BackendDiagnostics | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkResult | null>(null);
  const [backendBusy, setBackendBusy] = useState<string | null>(null);

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

  const runBackendTest = async () => {
    if (!client) return;
    setBackendBusy("test");
    setBackendDiag(null);
    try {
      const diag = (await client.request("test_backend", {
        backend: settings.backend,
      })) as unknown as BackendDiagnostics;
      setBackendDiag(diag);
    } catch (error) {
      setBackendDiag({
        backend_id: settings.backend,
        available: false,
        runtime: "unknown",
        initialized: false,
        model_loaded: false,
        execution_provider: null,
        device_name: null,
        runtime_version: null,
        model_id: null,
        self_test_passed: false,
        inference_ms: null,
        error: error instanceof Error ? error.message : "Backend test failed.",
        notes: [],
      });
    } finally {
      setBackendBusy(null);
    }
  };

  const runBenchmark = async () => {
    if (!client) return;
    setBackendBusy("bench");
    setBenchmark(null);
    try {
      // "auto" is a policy, not a benchmarkable backend: benchmark the
      // best accelerator this machine actually has, else the CPU path.
      const present = new Set(
        (testResult?.inference?.backends ?? [])
          .filter((b) => b.available)
          .map((b) => b.backend_id),
      );
      const best =
        ["onnx-cuda", "onnx-directml", "onnx-cpu", "pytorch-cpu"].find((id) =>
          present.has(id),
        ) ?? "onnx-cpu";
      const backend = settings.backend === "auto" ? best : settings.backend;
      const result = (await client.request("benchmark_backend", {
        backend,
        runs: 5,
      })) as unknown as BenchmarkResult;
      setBenchmark(result);
    } catch (error) {
      setBenchmark({
        backend: settings.backend,
        available: false,
        execution_provider: null,
        device_name: null,
        runtime: "unknown",
        runtime_version: null,
        runs: 0,
        warmup_runs: 0,
        cold_start_ms: null,
        per_run_ms: [],
        average_ms: null,
        error: error instanceof Error ? error.message : "Benchmark failed.",
      });
    } finally {
      setBackendBusy(null);
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
        <div className="rounded border border-slate-200 bg-slate-50 p-2">
          <p className="mb-2 text-xs text-slate-600">
            Video support needs FFmpeg. Leave the fields above empty and let
            FileSight fetch a build into its own folder — nothing else on the
            system is changed, and no PATH edit is needed.
          </p>
          <FfmpegDownloadButton />
        </div>

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
          <h3 className="mb-2 font-medium">Inference</h3>
          <label className="block">
            <span className="mb-1 block text-slate-600">Backend</span>
            <select
              className="field w-full"
              value={settings.backend}
              onChange={(event) => patch({ backend: event.target.value })}
            >
              {BACKEND_LABELS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-2 flex items-center gap-1.5">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={settings.allow_fallback}
              onChange={(event) => patch({ allow_fallback: event.target.checked })}
            />
            Allow automatic fallback
          </label>
          <p className="mt-1 text-xs text-slate-500">
            GPU backends need the ONNX model pack installed; without it they
            cannot caption and this falls back to CPU. Captions are identical
            on every backend, and a GPU is not currently faster for a whole
            scan. Each report names the backend that actually ran.
          </p>

          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void runBackendTest()}
              disabled={backendBusy !== null}
            >
              {backendBusy === "test" ? "Testing…" : "Test backend"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void runBenchmark()}
              disabled={backendBusy !== null}
            >
              {backendBusy === "bench" ? "Running…" : "Run benchmark"}
            </button>
          </div>

          {backendDiag ? (
            <dl className="mt-2 space-y-0.5 rounded border border-slate-200 p-2 text-xs">
              <div className="flex justify-between">
                <dt>Backend</dt>
                <dd>{backendDiag.backend_id}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Provider</dt>
                <dd>{backendDiag.execution_provider ?? "—"}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Device</dt>
                <dd>{backendDiag.device_name ?? "—"}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Self-test</dt>
                <dd
                  className={
                    backendDiag.self_test_passed
                      ? "text-emerald-700"
                      : "font-medium text-red-700"
                  }
                >
                  {backendDiag.self_test_passed
                    ? "Passed"
                    : `Failed${backendDiag.error ? `: ${backendDiag.error}` : ""}`}
                </dd>
              </div>
              {backendDiag.inference_ms !== null ? (
                <div className="flex justify-between">
                  <dt>Warm inference</dt>
                  <dd>{backendDiag.inference_ms} ms</dd>
                </div>
              ) : null}
            </dl>
          ) : null}

          {benchmark ? (
            <dl className="mt-2 space-y-0.5 rounded border border-slate-200 p-2 text-xs">
              <div className="flex justify-between">
                <dt>Benchmark backend</dt>
                <dd>{benchmark.execution_provider ?? benchmark.backend}</dd>
              </div>
              {benchmark.error ? (
                <p className="text-red-700">{benchmark.error}</p>
              ) : (
                <>
                  <div className="flex justify-between">
                    <dt>Cold start</dt>
                    <dd>{benchmark.cold_start_ms} ms</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Average of {benchmark.runs}</dt>
                    <dd>{benchmark.average_ms} ms</dd>
                  </div>
                  {benchmark.peak_ram_mb ? (
                    <div className="flex justify-between">
                      <dt>Peak RAM</dt>
                      <dd>{benchmark.peak_ram_mb} MB</dd>
                    </div>
                  ) : null}
                </>
              )}
            </dl>
          ) : null}
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

        <AboutSection />
      </div>
    </Dialog>
  );
}

/**
 * Settings -> About: a surface the user reached deliberately, so the
 * author's name and a link to what else he builds belong here (section 7).
 * The version is read from the bundle, never written down (rule 18).
 */
function AboutSection() {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    void (async () => setVersion(await getAppVersion()))();
  }, []);

  return (
    <div className="border-t border-slate-200 pt-3">
      <h3 className="mb-2 font-medium">About</h3>
      <dl className="space-y-0.5 text-xs">
        <div className="flex justify-between">
          <dt className="text-slate-600">{PRODUCT_METADATA.productName}</dt>
          <dd>{version ?? "—"}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-600">Author</dt>
          <dd>{PRODUCT_METADATA.author}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-slate-600">License</dt>
          <dd>{PRODUCT_METADATA.license}</dd>
        </div>
      </dl>
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-secondary"
          onClick={() => void openExternal(PRODUCT_METADATA.authorUrl)}
        >
          More projects and services
        </button>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => void openExternal(PRODUCT_METADATA.repositoryUrl)}
        >
          Source code
        </button>
      </div>
    </div>
  );
}
