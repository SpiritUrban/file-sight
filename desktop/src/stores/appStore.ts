/**
 * Single source of truth for the desktop app.
 *
 * One explicit `uiState` drives what is enabled, instead of a pile of
 * loosely-related booleans. All worker traffic goes through the injected
 * client, so tests drive the real store with the mock worker.
 */
import { create } from "zustand";

import { safeParse, reportSchema } from "@/lib/schemas";
import type { WorkerClient } from "@/lib/worker";
import { BaseWorkerClient, WorkerRequestError } from "@/lib/worker";
import { validateFilename } from "@/lib/filename";
import type {
  AppSettings,
  EntryStatus,
  MediaType,
  ProfileInfo,
  RenamePlan,
  RenameResult,
  ScanFileEntry,
  ScanOptions,
  ScanReport,
  UiState,
  UndoResult,
  ValidationIssue,
  ValidationResult,
  WorkerEnvironment,
  WorkerEvent,
} from "@/types";

export type StatusFilter =
  | "all"
  | "images"
  | "videos"
  | "success"
  | "failed"
  | "skipped"
  | "enabled"
  | "disabled";

export type SortKey =
  | "original_name"
  | "suggested_name"
  | "category"
  | "status"
  | "media_type"
  | "processing_time_ms";

/** One finished file, kept so the UI can show what just happened. */
export interface LiveResult {
  name: string;
  status: EntryStatus;
  caption: string | null;
  category: string | null;
  suggestedName: string | null;
  error: string | null;
}

export interface ProgressState {
  phase: string;
  currentFile: string | null;
  /** Cached preview of the file being processed right now. */
  currentThumbnail: string | null;
  currentMediaType: MediaType;
  currentIndex: number;
  /** Sub-step inside one file, e.g. "Analyzing frame 2/6" for videos. */
  stepLabel: string | null;
  stepCurrent: number;
  stepTotal: number;
  completed: number;
  total: number;
  percent: number;
  succeeded: number;
  failed: number;
  startedAt: number | null;
  /** Result of the file that just finished. */
  lastResult: LiveResult | null;
  /** A short tail of finished files, newest first. */
  recent: LiveResult[];
}

/** The zero state; exported so callers can reset without repeating it. */
export const emptyProgress: ProgressState = {
  phase: "",
  currentFile: null,
  currentThumbnail: null,
  currentMediaType: "image",
  currentIndex: 0,
  stepLabel: null,
  stepCurrent: 0,
  stepTotal: 0,
  completed: 0,
  total: 0,
  percent: 0,
  succeeded: 0,
  failed: 0,
  startedAt: null,
  lastResult: null,
  recent: [],
};

const RECENT_LIMIT = 6;

export const defaultScanOptions: ScanOptions = {
  directory: "",
  recursive: false,
  includeImages: true,
  includeVideos: false,
  profile: "default",
  maxFiles: null,
  videoFrames: 6,
  maxVideoDuration: 120,
  allowLongVideos: false,
  configPath: null,
  language: null,
  transliterate: null,
  outputPath: null,
};

export interface AppStore {
  client: WorkerClient | null;
  uiState: UiState;
  errorMessage: string | null;
  errorDetail: string | null;
  /** Per-file reasons behind the current error, when the worker sent any. */
  errorIssues: ValidationIssue[];

  environment: WorkerEnvironment | null;
  profiles: ProfileInfo[];
  workerExecutable: string | null;
  /** Saved app settings; supplies the FFmpeg/config paths to the worker. */
  settings: AppSettings | null;

  options: ScanOptions;
  report: ScanReport | null;
  reportPath: string | null;
  logPath: string | null;
  dirty: boolean;

  progress: ProgressState;
  activeRequestId: string | null;

  validation: ValidationResult | null;
  plan: RenamePlan | null;
  renameResult: RenameResult | null;
  undoResult: UndoResult | null;

  selectedPath: string | null;
  filter: StatusFilter;
  categoryFilter: string;
  search: string;
  sortKey: SortKey;
  sortAsc: boolean;

  // wiring
  attachClient: (client: WorkerClient) => void;
  setOptions: (patch: Partial<ScanOptions>) => void;
  setDirectory: (directory: string) => void;
  reset: () => void;
  clearError: () => void;

  // worker-backed actions
  bootstrap: () => Promise<void>;
  /** Re-read settings and re-check the environment (used after Settings). */
  refreshEnvironment: () => Promise<void>;
  startScan: () => Promise<void>;
  cancelScan: () => Promise<void>;
  loadReport: (path: string) => Promise<void>;
  saveReport: () => Promise<string | null>;
  validateReport: () => Promise<ValidationResult | null>;
  buildPlan: () => Promise<RenamePlan | null>;
  applyRename: () => Promise<RenameResult | null>;
  undoLast: (logPath?: string, dryRun?: boolean) => Promise<UndoResult | null>;
  regenerateNames: (profile: string) => Promise<void>;

  // local edits
  setSuggestedName: (path: string, name: string) => void;
  setRenameEnabled: (path: string, enabled: boolean) => void;
  setVisibleEnabled: (enabled: boolean) => void;
  resetSuggestedNames: () => void;

  // view
  select: (path: string | null) => void;
  setFilter: (filter: StatusFilter) => void;
  setCategoryFilter: (category: string) => void;
  setSearch: (search: string) => void;
  setSort: (key: SortKey) => void;
  visibleEntries: () => ScanFileEntry[];
  entryErrors: () => Map<string, string>;
}

/** Tool paths every worker command that touches media needs. */
export function toolPayload(
  settings: AppSettings | null,
): Record<string, unknown> {
  return {
    ffmpeg_path: settings?.ffmpeg_path ?? null,
    ffprobe_path: settings?.ffprobe_path ?? null,
    config: settings?.config_path ?? null,
  };
}

/** Settings live in Rust; outside Tauri (tests) there simply are none. */
async function loadSettings(): Promise<AppSettings | null> {
  try {
    const platform = await import("@/lib/platform");
    return await platform.getAppSettings();
  } catch {
    return null;
  }
}

/** True when a file operation is in flight and must not be interrupted. */
export function isBusy(state: UiState): boolean {
  return (
    // The worker preloads the model at startup; sending a scan before the
    // environment check returns just races it.
    state === "environment_check" ||
    state === "scanning" ||
    state === "analyzing" ||
    state === "loading_model" ||
    state === "cancelling" ||
    state === "renaming" ||
    state === "undoing" ||
    state === "validating"
  );
}

export function isFileOperation(state: UiState): boolean {
  return state === "renaming" || state === "undoing";
}

function applyEdit(
  report: ScanReport,
  path: string,
  patch: Partial<ScanFileEntry>,
): ScanReport {
  return {
    ...report,
    files: report.files.map((file) =>
      file.original_path === path ? { ...file, ...patch } : file,
    ),
  };
}

export const useAppStore = create<AppStore>((set, get) => ({
  client: null,
  uiState: "idle",
  errorMessage: null,
  errorDetail: null,
  errorIssues: [],

  environment: null,
  profiles: [],
  workerExecutable: null,
  settings: null,

  options: { ...defaultScanOptions },
  report: null,
  reportPath: null,
  logPath: null,
  dirty: false,

  progress: { ...emptyProgress },
  activeRequestId: null,

  validation: null,
  plan: null,
  renameResult: null,
  undoResult: null,

  selectedPath: null,
  filter: "all",
  categoryFilter: "all",
  search: "",
  sortKey: "original_name",
  sortAsc: true,

  attachClient: (client) => set({ client }),

  setOptions: (patch) =>
    set((state) => ({ options: { ...state.options, ...patch } })),

  setDirectory: (directory) =>
    set((state) => ({
      options: { ...state.options, directory },
      uiState: directory ? "folder_selected" : "idle",
      report: null,
      reportPath: null,
      validation: null,
      plan: null,
      renameResult: null,
      dirty: false,
      selectedPath: null,
      progress: { ...emptyProgress },
    })),

  reset: () =>
    set({
      uiState: "idle",
      report: null,
      reportPath: null,
      validation: null,
      plan: null,
      renameResult: null,
      undoResult: null,
      dirty: false,
      selectedPath: null,
      progress: { ...emptyProgress },
      errorMessage: null,
      errorDetail: null,
    }),

  clearError: () =>
    set({ errorMessage: null, errorDetail: null, errorIssues: [] }),

  bootstrap: async () => {
    const { client } = get();
    if (!client) return;
    set({ uiState: "environment_check", errorMessage: null });
    try {
      const executable = await client.start();
      set({ workerExecutable: executable });

      const settings = await loadSettings();
      const environment = (await client.request(
        "get_environment",
        toolPayload(settings),
      )) as unknown as WorkerEnvironment;
      const profileData = (await client.request("get_profiles", {
        config: settings?.config_path ?? null,
      })) as { profiles: ProfileInfo[]; default_profile: string };

      set((state) => ({
        settings,
        environment,
        profiles: profileData.profiles ?? [],
        options: {
          ...state.options,
          profile: state.options.profile || profileData.default_profile,
          // Saved defaults apply until the user changes them for this run.
          recursive: settings?.default_recursive ?? state.options.recursive,
          includeVideos:
            settings?.default_include_videos ?? state.options.includeVideos,
          configPath: state.options.configPath ?? settings?.config_path ?? null,
          directory: state.options.directory || (settings?.last_directory ?? ""),
        },
        uiState:
          state.options.directory || settings?.last_directory
            ? "folder_selected"
            : "idle",
      }));
    } catch (error) {
      set({
        uiState: "error",
        errorMessage:
          error instanceof Error
            ? error.message
            : "Could not start the analysis worker.",
        errorDetail: error instanceof WorkerRequestError ? error.code : null,
      });
    }
  },

  refreshEnvironment: async () => {
    const { client } = get();
    if (!client) return;
    try {
      const settings = await loadSettings();
      const environment = (await client.request(
        "get_environment",
        toolPayload(settings),
      )) as unknown as WorkerEnvironment;
      set({ settings, environment });
    } catch {
      // a failed re-check must not disturb the current session
    }
  },

  startScan: async () => {
    const { client, options } = get();
    if (!client) return;
    if (isBusy(get().uiState)) return; // no concurrent scans
    if (!options.directory) {
      set({ uiState: "error", errorMessage: "Choose a folder first." });
      return;
    }

    set({
      uiState: "scanning",
      errorMessage: null,
      errorDetail: null,
      validation: null,
      plan: null,
      renameResult: null,
      progress: { ...emptyProgress, phase: "Preparing", startedAt: Date.now() },
    });

    const settings = get().settings;
    const payload: Record<string, unknown> = {
      directory: options.directory,
      recursive: options.recursive,
      include_images: options.includeImages,
      include_videos: options.includeVideos,
      profile: options.profile,
      max_files: options.maxFiles,
      video_frames: options.videoFrames,
      max_video_duration: options.maxVideoDuration,
      allow_long_videos: options.allowLongVideos,
      config: options.configPath ?? settings?.config_path ?? null,
      language: options.language,
      transliterate: options.transliterate,
      output: options.outputPath,
      // Without these a configured FFmpeg would be ignored and every
      // video would fail with FFMPEG_NOT_FOUND.
      ...toolPayload(settings),
    };

    const onEvent = (event: WorkerEvent) => {
      const data = event.data as Record<string, never>;
      switch (event.event) {
        case "started":
          set((state) => ({
            uiState: "analyzing",
            progress: {
              ...state.progress,
              total: Number(data.total_files ?? 0),
              phase: "Analyzing",
            },
          }));
          break;
        case "phase":
          set((state) => ({
            uiState:
              String(data.phase) === "Loading model"
                ? "loading_model"
                : state.uiState === "loading_model"
                  ? "analyzing"
                  : state.uiState,
            progress: { ...state.progress, phase: String(data.phase ?? "") },
          }));
          break;
        case "file_started":
          set((state) => ({
            // Files are being processed, so the model is clearly ready —
            // don't wait for a phase event to leave the loading state.
            uiState:
              state.uiState === "loading_model" || state.uiState === "scanning"
                ? "analyzing"
                : state.uiState,
            progress: {
              ...state.progress,
              currentFile: String(data.name ?? ""),
              currentThumbnail: (data.thumbnail as string | null) ?? null,
              currentMediaType:
                (data.media_type as MediaType | undefined) ?? "image",
              currentIndex: Number(data.index ?? 0),
              // a fresh file starts with no sub-step and no result yet
              stepLabel: null,
              stepCurrent: 0,
              stepTotal: 0,
              lastResult: null,
            },
          }));
          break;
        case "frame_progress":
          set((state) => ({
            progress: {
              ...state.progress,
              stepLabel: String(data.label ?? ""),
              stepCurrent: Number(data.current ?? 0),
              stepTotal: Number(data.total ?? 0),
            },
          }));
          break;
        case "file_completed": {
          const result: LiveResult = {
            name: String(data.name ?? ""),
            status: (data.status as EntryStatus) ?? "success",
            caption: (data.caption as string | null) ?? null,
            category: (data.category as string | null) ?? null,
            suggestedName: (data.suggested_name as string | null) ?? null,
            error:
              (data.error as { message?: string } | null)?.message ?? null,
          };
          set((state) => ({
            progress: {
              ...state.progress,
              succeeded:
                state.progress.succeeded + (data.status === "success" ? 1 : 0),
              failed:
                state.progress.failed + (data.status === "failed" ? 1 : 0),
              stepLabel: null,
              lastResult: result,
              recent: [result, ...state.progress.recent].slice(0, RECENT_LIMIT),
            },
          }));
          break;
        }
        case "progress":
          set((state) => ({
            progress: {
              ...state.progress,
              completed: Number(data.completed ?? 0),
              total: Number(data.total ?? state.progress.total),
              percent: Number(data.percent ?? 0),
            },
          }));
          break;
        default:
          break;
      }
    };

    const base = client as BaseWorkerClient;
    const { requestId, promise } = base.startOperation<{
      report?: unknown;
      report_path?: string;
      cancelled?: boolean;
    }>("scan", payload, onEvent);
    set({ activeRequestId: requestId });

    try {
      const result = await promise;
      const parsed = safeParse<ScanReport>(reportSchema, result.report);
      if (!parsed.ok) {
        set({
          uiState: "error",
          activeRequestId: null,
          errorMessage: "The analysis finished but its report could not be read.",
          errorDetail: parsed.error,
        });
        return;
      }
      set((state) => ({
        uiState: "report_ready",
        report: parsed.value,
        reportPath: result.report_path ?? state.reportPath,
        activeRequestId: null,
        dirty: false,
        progress: { ...state.progress, phase: result.cancelled ? "Cancelled" : "Completed" },
      }));
    } catch (error) {
      set({
        uiState: "error",
        activeRequestId: null,
        errorMessage:
          error instanceof Error ? error.message : "The analysis failed.",
        errorDetail: error instanceof WorkerRequestError ? error.code : null,
      });
    }
  },

  cancelScan: async () => {
    const { client, activeRequestId } = get();
    if (!client || !activeRequestId) return;
    set({ uiState: "cancelling" });
    try {
      await client.request("cancel", { target_request_id: activeRequestId });
    } catch {
      // the scan may have finished in the meantime; nothing to do
    }
  },

  loadReport: async (path) => {
    const { client } = get();
    if (!client) return;
    try {
      const data = (await client.request("load_report", { path })) as {
        report: unknown;
      };
      const parsed = safeParse<ScanReport>(reportSchema, data.report);
      if (!parsed.ok) {
        set({ uiState: "error", errorMessage: "That report could not be read.", errorDetail: parsed.error });
        return;
      }
      set({
        report: parsed.value,
        reportPath: path,
        uiState: "report_ready",
        dirty: false,
        validation: null,
        plan: null,
      });
    } catch (error) {
      set({
        uiState: "error",
        errorMessage: error instanceof Error ? error.message : "Could not load the report.",
      });
    }
  },

  saveReport: async () => {
    const { client, report, reportPath } = get();
    if (!client || !report) return null;
    const path = reportPath ?? `${get().options.directory}\\filesight-report.json`;
    try {
      const data = (await client.request("save_report", {
        path,
        report,
        backup: true,
      })) as { path: string };
      set({ dirty: false, reportPath: data.path ?? path });
      return data.path ?? path;
    } catch (error) {
      set({
        errorMessage: error instanceof Error ? error.message : "Could not save the report.",
      });
      return null;
    }
  },

  validateReport: async () => {
    const { client, report, reportPath } = get();
    if (!client || !report) return null;
    set({ uiState: "validating" });
    try {
      const result = (await client.request("validate_report", {
        report,
        path: reportPath,
      })) as unknown as ValidationResult;
      set({ validation: result, uiState: "report_ready" });
      return result;
    } catch (error) {
      set({
        uiState: "report_ready",
        errorMessage: error instanceof Error ? error.message : "Validation failed.",
      });
      return null;
    }
  },

  buildPlan: async () => {
    const { client, report, reportPath } = get();
    if (!client || !report) return null;
    try {
      const plan = (await client.request("build_rename_plan", {
        report,
        path: reportPath,
      })) as unknown as RenamePlan;
      set({ plan, uiState: "rename_preview" });
      return plan;
    } catch (error) {
      set({
        errorMessage: error instanceof Error ? error.message : "Could not build the plan.",
      });
      return null;
    }
  },

  applyRename: async () => {
    const { client, report, reportPath } = get();
    if (!client || !report) return null;
    if (isFileOperation(get().uiState)) return null;
    set({ uiState: "renaming", errorMessage: null });
    try {
      const result = (await client.request("apply_rename", {
        report,
        path: reportPath,
      })) as unknown as RenameResult;
      const succeeded = result.status === "completed";
      set((state) => ({
        uiState: succeeded ? "rename_completed" : "rename_failed",
        renameResult: result,
        logPath: result.log_path || state.logPath,
        // reflect the new names on disk
        report: succeeded && state.report ? applyRenamed(state.report, result) : state.report,
      }));
      return result;
    } catch (error) {
      set({
        uiState: "rename_failed",
        errorMessage: error instanceof Error ? error.message : "Rename failed.",
        errorDetail: error instanceof WorkerRequestError ? error.code : null,
        errorIssues:
          error instanceof WorkerRequestError ? error.details : [],
      });
      return null;
    }
  },

  undoLast: async (logPath, dryRun = false) => {
    const { client } = get();
    const path = logPath ?? get().logPath;
    if (!client || !path) return null;
    if (!dryRun) set({ uiState: "undoing" });
    try {
      const result = (await client.request("undo", {
        log_path: path,
        dry_run: dryRun,
      })) as unknown as UndoResult;
      if (!dryRun) {
        set({ uiState: "report_ready", undoResult: result });
      }
      return result;
    } catch (error) {
      set({
        uiState: "report_ready",
        errorMessage: error instanceof Error ? error.message : "Undo failed.",
      });
      return null;
    }
  },

  regenerateNames: async (profile) => {
    const { client, report } = get();
    if (!client || !report) return;
    try {
      const data = (await client.request("regenerate_names", {
        report,
        profile,
      })) as { report: unknown };
      const parsed = safeParse<ScanReport>(reportSchema, data.report);
      if (!parsed.ok) {
        set({ errorMessage: "Regenerated report could not be read.", errorDetail: parsed.error });
        return;
      }
      set({ report: parsed.value, dirty: true, validation: null, plan: null });
    } catch (error) {
      set({
        errorMessage: error instanceof Error ? error.message : "Could not regenerate names.",
      });
    }
  },

  setSuggestedName: (path, name) =>
    set((state) =>
      state.report
        ? {
            report: applyEdit(state.report, path, { suggested_name: name }),
            dirty: true,
          }
        : {},
    ),

  setRenameEnabled: (path, enabled) =>
    set((state) =>
      state.report
        ? {
            report: applyEdit(state.report, path, { rename_enabled: enabled }),
            dirty: true,
          }
        : {},
    ),

  setVisibleEnabled: (enabled) => {
    const visible = new Set(get().visibleEntries().map((e) => e.original_path));
    set((state) =>
      state.report
        ? {
            report: {
              ...state.report,
              files: state.report.files.map((file) =>
                visible.has(file.original_path) && file.status === "success"
                  ? { ...file, rename_enabled: enabled }
                  : file,
              ),
            },
            dirty: true,
          }
        : {},
    );
  },

  resetSuggestedNames: () =>
    set((state) =>
      state.report
        ? {
            report: {
              ...state.report,
              files: state.report.files.map((file) =>
                file.naming
                  ? { ...file, suggested_name: file.naming.suggested_name }
                  : file,
              ),
            },
            dirty: true,
          }
        : {},
    ),

  select: (path) => set({ selectedPath: path }),
  setFilter: (filter) => set({ filter }),
  setCategoryFilter: (categoryFilter) => set({ categoryFilter }),
  setSearch: (search) => set({ search }),
  setSort: (key) =>
    set((state) => ({
      sortKey: key,
      sortAsc: state.sortKey === key ? !state.sortAsc : true,
    })),

  visibleEntries: () => {
    const { report, filter, search, categoryFilter, sortKey, sortAsc } = get();
    if (!report) return [];
    const needle = search.trim().toLowerCase();

    let files = report.files.filter((file) => {
      switch (filter) {
        case "images":
          return file.media_type === "image";
        case "videos":
          return file.media_type === "video";
        case "success":
          return file.status === "success";
        case "failed":
          return file.status === "failed";
        case "skipped":
          return file.status === "skipped";
        case "enabled":
          return file.rename_enabled && file.status === "success";
        case "disabled":
          return !file.rename_enabled;
        default:
          return true;
      }
    });

    if (categoryFilter !== "all") {
      files = files.filter(
        (file) => (file.classification?.category ?? "other") === categoryFilter,
      );
    }

    if (needle) {
      files = files.filter((file) =>
        [
          file.original_name,
          file.suggested_name ?? "",
          file.caption ?? "",
          file.classification?.category ?? "",
        ]
          .join(" ")
          .toLowerCase()
          .includes(needle),
      );
    }

    const direction = sortAsc ? 1 : -1;
    return [...files].sort((a, b) => {
      const pick = (file: ScanFileEntry): string | number => {
        switch (sortKey) {
          case "suggested_name":
            return file.suggested_name ?? "";
          case "category":
            return file.classification?.category ?? "";
          case "status":
            return file.status;
          case "media_type":
            return file.media_type;
          case "processing_time_ms":
            return file.processing_time_ms;
          default:
            return file.original_name;
        }
      };
      const left = pick(a);
      const right = pick(b);
      if (typeof left === "number" && typeof right === "number") {
        return (left - right) * direction;
      }
      return String(left).localeCompare(String(right)) * direction;
    });
  },

  entryErrors: () => {
    const { report } = get();
    const errors = new Map<string, string>();
    if (!report) return errors;

    const targets = new Map<string, number>();
    for (const file of report.files) {
      if (file.status !== "success" || !file.rename_enabled) continue;
      const key = (file.suggested_name ?? "").toLowerCase();
      if (key) targets.set(key, (targets.get(key) ?? 0) + 1);
    }

    for (const file of report.files) {
      if (file.status !== "success") continue;
      const problem = validateFilename(
        file.suggested_name ?? "",
        file.original_name,
      );
      if (problem) {
        errors.set(file.original_path, problem);
        continue;
      }
      if (
        file.rename_enabled &&
        (targets.get((file.suggested_name ?? "").toLowerCase()) ?? 0) > 1
      ) {
        errors.set(
          file.original_path,
          "Another enabled file already targets this name.",
        );
      }
    }
    return errors;
  },
}));

/** Rewrite entries to the names they now have on disk. */
function applyRenamed(report: ScanReport, result: RenameResult): ScanReport {
  const byOriginal = new Map<string, string>();
  for (const operation of result.operations ?? []) {
    const op = operation as { original_path?: string; final_path?: string; status?: string };
    if (op.status === "completed" && op.original_path && op.final_path) {
      byOriginal.set(op.original_path, op.final_path);
    }
  }
  if (byOriginal.size === 0) return report;
  return {
    ...report,
    files: report.files.map((file) => {
      const finalPath = byOriginal.get(file.original_path);
      if (!finalPath) return file;
      const name = finalPath.split(/[\\/]/).pop() ?? file.original_name;
      return { ...file, original_path: finalPath, original_name: name };
    }),
  };
}
