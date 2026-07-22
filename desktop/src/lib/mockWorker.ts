/**
 * In-memory worker used by tests and by `VITE_MOCK_WORKER=1` UI work.
 *
 * It emits the same event sequence as the Python worker so the whole
 * flow (scan → edit → validate → dry-run → rename → undo) can be driven
 * without Python, FFmpeg or a model. Never bundled into a normal build.
 */
import { BaseWorkerClient } from "@/lib/worker";
import type { ScanFileEntry, ScanReport, WorkerCommand } from "@/types";

function entry(
  overrides: Partial<ScanFileEntry> & Pick<ScanFileEntry, "original_name">,
): ScanFileEntry {
  const name = overrides.original_name;
  return {
    original_path: `C:\\Photos\\${name}`,
    extension: name.slice(name.lastIndexOf(".")),
    status: "success",
    caption: "a black dog running through snow",
    suggested_name: "animals-black-dog-running.jpg",
    processing_time_ms: 1200,
    media_type: "image",
    error: null,
    rename_enabled: true,
    source_metadata: { size_bytes: 1024, modified_at_ns: 1 },
    features: {
      subject: "black dog",
      action: "running",
      location: "snow",
      objects: ["snow", "trees"],
      text: null,
    },
    classification: {
      category: "animals",
      category_label: "animals",
      confidence: 0.55,
      method: "rules",
      matched_rules: ["keyword:dog"],
    },
    naming: {
      profile: "default",
      template: "{subject}-{action}-{location}",
      language: "en",
      transliterated: false,
      base_name: "animals-black-dog-running",
      suggested_name: "animals-black-dog-running.jpg",
      warnings: [],
    },
    captured_at: "2026-01-14T15:42:10",
    date_source: "exif_datetime_original",
    ...overrides,
  };
}

export const MOCK_ENTRIES: ScanFileEntry[] = [
  entry({
    original_name: "IMG_0001.jpg",
    suggested_name: "animals-black-dog-running.jpg",
  }),
  entry({
    original_name: "IMG_0002.jpg",
    caption: "a woman standing near a red car",
    suggested_name: "people-woman-standing-red-car.jpg",
    classification: {
      category: "people",
      category_label: "people",
      confidence: 0.55,
      method: "rules",
      matched_rules: ["keyword:woman"],
    },
    features: {
      subject: "woman",
      action: "standing",
      location: "red car",
      objects: ["car"],
      text: null,
    },
  }),
  entry({
    original_name: "clip.mp4",
    media_type: "video",
    caption: "a tv screen showing colors",
    suggested_name: "other-tv-screen.mp4",
    video_metadata: {
      duration_seconds: 3.2,
      width: 640,
      height: 360,
      frame_rate: 30,
      video_codec: "h264",
      container: "mp4",
      has_audio: false,
      rotation_degrees: 0,
    },
    video_analysis: {
      requested_frames: 6,
      extracted_frames: 6,
      usable_frames: 2,
      analyzed_frames: 2,
      frames: [
        {
          index: 1,
          timestamp_seconds: 0.5,
          status: "success",
          caption: "a tv screen",
          skip_reason: null,
          error: null,
        },
        {
          index: 2,
          timestamp_seconds: 1.5,
          status: "skipped",
          caption: null,
          skip_reason: "near_duplicate",
          error: null,
        },
      ],
      warnings: ["partial_frame_analysis"],
    },
  }),
  entry({
    original_name: "broken.png",
    status: "failed",
    caption: null,
    suggested_name: null,
    rename_enabled: false,
    features: null,
    classification: null,
    naming: null,
    error: { type: "UnidentifiedImageError", message: "cannot identify image file" },
  }),
];

export function mockReport(files: ScanFileEntry[] = MOCK_ENTRIES): ScanReport {
  const processed = files.filter((f) => f.status === "success").length;
  return {
    schema_version: "1.3",
    created_at: "2026-07-21T12:00:00Z",
    source_directory: "C:\\Photos",
    recursive: false,
    model: {
      provider: "huggingface",
      name: "Salesforce/blip-image-captioning-base",
      device: "cpu",
    },
    summary: {
      discovered: files.length,
      processed,
      failed: files.length - processed,
      skipped: 0,
      duration_seconds: 12.5,
    },
    files,
    naming_configuration: {
      source: "built-in",
      profile: "default",
      template: "{subject}-{action}-{location}",
      language: "en",
      transliterate: false,
      config_version: null,
    },
    inference: {
      requested_backend: "auto",
      actual_backend: "pytorch-cpu",
      runtime: "pytorch",
      runtime_version: "2.13.0+cpu",
      execution_provider: "CPU",
      device_name: "CPU",
      model_id: "Salesforce/blip-image-captioning-base",
      model_version: null,
      fallback_occurred: false,
      fallback_reason: null,
      directml_available: true,
    },
  };
}

export interface MockOptions {
  /** Fail the next scan with this error code. */
  scanError?: { code: string; message: string; recoverable?: boolean };
  /** Report a partially rolled back rename. */
  partialRename?: boolean;
  /** Emit an unparseable event before completing a scan. */
  emitGarbage?: boolean;
  /** Delay between per-file events (ms); 0 keeps tests fast. */
  stepDelay?: number;
}

export class MockWorkerClient extends BaseWorkerClient {
  running = false;
  sent: Array<{ command: WorkerCommand; payload: Record<string, unknown> }> = [];
  options: MockOptions;
  private cancelled = new Set<string>();
  private report: ScanReport;

  constructor(options: MockOptions = {}) {
    super();
    this.options = options;
    this.report = mockReport();
  }

  async start(): Promise<string> {
    this.running = true;
    return "C:\\mock\\python.exe";
  }

  /** Expose dispatch for tests that inject custom event sequences. */
  emitEvent(requestId: string, event: string, data: Record<string, unknown>): void {
    this.emit(requestId, event, data);
  }

  async stop(): Promise<void> {
    this.running = false;
  }

  setReport(report: ScanReport): void {
    this.report = report;
  }

  private emit(requestId: string, event: string, data: Record<string, unknown>): void {
    this.dispatch({ request_id: requestId, event, data });
  }

  private async pause(): Promise<void> {
    const delay = this.options.stepDelay ?? 0;
    if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
  }

  async send(
    requestId: string,
    command: WorkerCommand,
    payload: Record<string, unknown> = {},
  ): Promise<void> {
    this.sent.push({ command, payload });
    // Real events arrive asynchronously; mirror that so React can settle.
    void this.handle(requestId, command, payload);
  }

  private async handle(
    requestId: string,
    command: WorkerCommand,
    payload: Record<string, unknown>,
  ): Promise<void> {
    await this.pause();
    switch (command) {
      case "ping":
        return this.emit(requestId, "completed", { pong: true, version: "0.5.0" });

      case "cancel": {
        const target = String(payload.target_request_id ?? "");
        this.cancelled.add(target);
        return this.emit(requestId, "completed", { cancelled: true });
      }

      case "get_environment":
        return this.emit(requestId, "completed", {
          python: { executable: "C:\\mock\\python.exe", version: "3.11.9", ok: true },
          filesight: { version: "0.5.0", ok: true },
          model: { loaded: false, name: "blip", cache: "C:\\cache", cached: true },
          ffmpeg: { available: true, path: "C:\\ffmpeg.exe", version: "ffmpeg 8.1" },
          ffprobe: { available: true, path: "C:\\ffprobe.exe", version: "ffprobe 8.1" },
          config: { ok: true, source: "built-in", default_profile: "default" },
          inference: {
            backends: [
              { backend_id: "onnx-directml", available: true },
              { backend_id: "onnx-cpu", available: true },
              { backend_id: "pytorch-cpu", available: true },
            ],
            directml_available: true,
            gpu_name: "Radeon RX 580 Series",
          },
        });

      case "list_backends":
        return this.emit(requestId, "completed", {
          backends: [
            { backend_id: "onnx-directml", available: true },
            { backend_id: "onnx-cpu", available: true },
            { backend_id: "pytorch-cpu", available: true },
          ],
        });

      case "test_backend":
        return this.emit(requestId, "completed", {
          backend_id: String(payload.backend ?? "onnx-directml"),
          available: true,
          runtime: "onnxruntime",
          initialized: true,
          model_loaded: true,
          execution_provider: "DmlExecutionProvider",
          device_name: "Radeon RX 580 Series",
          runtime_version: "1.24.4",
          model_id: "filesight-selftest",
          self_test_passed: true,
          inference_ms: 3,
          error: null,
          notes: [],
        });

      case "benchmark_backend":
        this.emit(requestId, "benchmark_started", { backend: payload.backend });
        return this.emit(requestId, "benchmark_completed", {
          backend: String(payload.backend ?? "onnx-directml"),
          available: true,
          execution_provider: "DmlExecutionProvider",
          device_name: "Radeon RX 580 Series",
          runtime: "onnxruntime",
          runtime_version: "1.24.4",
          runs: 5,
          warmup_runs: 1,
          cold_start_ms: 120,
          per_run_ms: [0.3, 0.28, 0.27, 0.29, 0.28],
          average_ms: 0.284,
          peak_ram_mb: 240,
          error: null,
        });

      case "get_profiles":
        return this.emit(requestId, "completed", {
          profiles: [
            {
              name: "default",
              template: "{subject}-{action}-{location}",
              language: "en",
              max_filename_length: 80,
              built_in: true,
            },
            {
              name: "photos",
              template: "{date}-{category}-{subject}-{location}",
              language: "en",
              max_filename_length: 100,
              built_in: true,
            },
          ],
          default_profile: "default",
          source: "built-in",
          warning: null,
        });

      case "scan":
        return this.runScan(requestId);

      case "load_report":
        return this.emit(requestId, "completed", { report: this.report });

      case "save_report":
        return this.emit(requestId, "completed", {
          path: String(payload.path ?? "C:\\Photos\\filesight-report.json"),
          backup_path: "C:\\Photos\\filesight-report.backup-20260721-120000.json",
        });

      case "validate_report": {
        const report = (payload.report as ScanReport) ?? this.report;
        const ready = report.files.filter(
          (f) => f.status === "success" && f.rename_enabled,
        ).length;
        return this.emit(requestId, "completed", {
          valid: true,
          entries: report.files.length,
          ready,
          skipped: report.files.length - ready,
          conflicts: 0,
          missing: 0,
          errors: [],
          warnings: [
            {
              severity: "warning",
              code: "NO_METADATA",
              message: "1 entry has no source_metadata.",
              path: null,
              entry_index: null,
            },
          ],
        });
      }

      case "build_rename_plan": {
        const report = (payload.report as ScanReport) ?? this.report;
        const items = report.files.map((file, index) => ({
          entry_index: index,
          original_path: file.original_path,
          original_name: file.original_name,
          action:
            file.status === "success" && file.rename_enabled ? "rename" : "skip",
          target_name: file.suggested_name,
          final_path: file.suggested_name
            ? `C:\\Photos\\${file.suggested_name}`
            : null,
          skip_reason:
            file.status !== "success"
              ? `report status is ${file.status}`
              : file.rename_enabled
                ? null
                : "rename_enabled is false in report",
          conflict_resolved: false,
        }));
        return this.emit(requestId, "completed", {
          items,
          rename_count: items.filter((i) => i.action === "rename").length,
          skip_count: items.filter((i) => i.action === "skip").length,
          errors: [],
          warnings: [],
          valid: true,
          log_path: "C:\\Photos\\filesight-rename-log-20260721-120000.json",
        });
      }

      case "apply_rename":
        if (this.options.partialRename) {
          return this.emit(requestId, "completed", {
            status: "partially_rolled_back",
            renamed: 8,
            failed: 1,
            rolled_back: 7,
            skipped: 0,
            log_path: "C:\\Photos\\filesight-rename-log.json",
            error: "OSError: injected failure",
            all_restored: false,
            operations: [],
          });
        }
        return this.emit(requestId, "completed", {
          status: "completed",
          renamed: 3,
          failed: 0,
          rolled_back: 0,
          skipped: 1,
          log_path: "C:\\Photos\\filesight-rename-log-20260721-120000.json",
          error: null,
          all_restored: true,
          operations: [],
        });

      case "undo":
        if (payload.dry_run) {
          return this.emit(requestId, "completed", {
            status: "dry_run",
            restored: 0,
            operations: [
              { from: "C:\\Photos\\animals-black-dog-running.jpg", to: "C:\\Photos\\IMG_0001.jpg" },
            ],
          });
        }
        return this.emit(requestId, "completed", {
          status: "undone",
          restored: 3,
          failed: 0,
          error: null,
          log_path: "C:\\Photos\\filesight-rename-log.json",
        });

      case "regenerate_names": {
        const regenerated: ScanReport = {
          ...this.report,
          files: this.report.files.map((file) =>
            file.status === "success"
              ? { ...file, suggested_name: `compact-${file.original_name}` }
              : file,
          ),
        };
        return this.emit(requestId, "completed", {
          report: regenerated,
          changed: regenerated.files.filter((f) => f.status === "success").length,
          skipped: 1,
          changes: [],
        });
      }

      case "make_thumbnail":
        return this.emit(requestId, "completed", {
          path: payload.path,
          thumbnail: null,
        });

      default:
        return this.emit(requestId, "error", {
          code: "UNKNOWN_COMMAND",
          message: `Unknown command: ${command}`,
          recoverable: true,
        });
    }
  }

  private async runScan(requestId: string): Promise<void> {
    if (this.options.scanError) {
      return this.emit(requestId, "error", {
        recoverable: true,
        ...this.options.scanError,
      });
    }
    const files = this.report.files;
    this.emit(requestId, "started", {
      total_files: files.length,
      images: files.filter((f) => f.media_type === "image").length,
      videos: files.filter((f) => f.media_type === "video").length,
      directory: "C:\\Photos",
      profile: "default",
      template: "{subject}-{action}-{location}",
    });
    this.emit(requestId, "phase", { phase: "Loading model" });

    for (let index = 0; index < files.length; index += 1) {
      await this.pause();
      if (this.cancelled.has(requestId)) {
        this.emit(requestId, "phase", { phase: "Cancelled" });
        this.emit(requestId, "completed", {
          report_path: "C:\\Photos\\filesight-report.json",
          processed: index,
          failed: 0,
          skipped: 0,
          total: files.length,
          cancelled: true,
          report: mockReport(files.slice(0, index)),
        });
        return;
      }
      const file = files[index];
      this.emit(requestId, "file_started", {
        index: index + 1,
        total: files.length,
        path: file.original_path,
        name: file.original_name,
        thumbnail: `C:\\cache\\${file.original_name}.jpg`,
        media_type: file.media_type,
      });
      if (file.media_type === "video") {
        // videos report per-frame progress inside the file
        this.emit(requestId, "frame_progress", {
          label: "Analyzing frame",
          current: 1,
          total: 2,
        });
        await this.pause();
      }
      this.emit(requestId, "file_completed", {
        path: file.original_path,
        name: file.original_name,
        status: file.status,
        caption: file.caption,
        media_type: file.media_type,
        category: file.classification?.category ?? null,
        suggested_name: file.suggested_name,
        error: file.error,
      });
      this.emit(requestId, "progress", {
        completed: index + 1,
        total: files.length,
        percent: Math.round(((index + 1) / files.length) * 10000) / 100,
      });
    }

    if (this.options.emitGarbage) {
      // Exercise the "unreadable event" path.
      this.dispatch({
        request_id: requestId,
        event: "error",
        data: {
          code: "WORKER_PROTOCOL_ERROR",
          message: "Unreadable worker output.",
          recoverable: true,
        },
      });
      return;
    }

    this.emit(requestId, "completed", {
      report_path: "C:\\Photos\\filesight-report.json",
      processed: this.report.summary.processed,
      failed: this.report.summary.failed,
      skipped: 0,
      total: files.length,
      cancelled: false,
      duration_seconds: 12.5,
      report: this.report,
    });
  }
}
