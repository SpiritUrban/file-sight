/**
 * Types mirroring the Python core's JSON schema (report schema 1.3)
 * and the worker protocol. Kept in sync by hand; every value that
 * crosses the process boundary is additionally checked at runtime with
 * Zod (see lib/schemas.ts).
 */

export type MediaType = "image" | "video";
export type EntryStatus = "success" | "failed" | "skipped";

export interface FileError {
  type: string;
  message: string;
}

export interface SourceMetadata {
  size_bytes: number;
  modified_at_ns: number;
}

export interface MediaFeatures {
  subject: string | null;
  action: string | null;
  location: string | null;
  objects: string[];
  text: string | null;
}

export interface ClassificationResult {
  category: string;
  category_label: string;
  confidence: number;
  method: string;
  matched_rules: string[];
}

export interface NamingResult {
  profile: string;
  template: string;
  language: string;
  transliterated: boolean;
  base_name: string;
  suggested_name: string;
  warnings: string[];
}

export interface VideoMetadata {
  duration_seconds: number;
  width: number | null;
  height: number | null;
  frame_rate: number | null;
  video_codec: string | null;
  container: string | null;
  has_audio: boolean;
  rotation_degrees: number;
  creation_time?: string | null;
}

export interface VideoFrameResult {
  index: number;
  timestamp_seconds: number;
  status: string;
  caption: string | null;
  skip_reason: string | null;
  error: FileError | null;
}

export interface VideoAnalysis {
  requested_frames: number;
  extracted_frames: number;
  usable_frames: number;
  analyzed_frames: number;
  frames: VideoFrameResult[];
  warnings: string[];
}

export interface Timings {
  probe_ms: number;
  frame_extraction_ms: number;
  captioning_ms: number;
  aggregation_ms: number;
  total_ms: number;
}

export interface ScanFileEntry {
  original_path: string;
  original_name: string;
  extension: string;
  status: EntryStatus;
  caption: string | null;
  suggested_name: string | null;
  processing_time_ms: number;
  media_type: MediaType;
  error: FileError | null;
  source_metadata?: SourceMetadata | null;
  rename_enabled: boolean;
  video_metadata?: VideoMetadata | null;
  video_analysis?: VideoAnalysis | null;
  timings?: Timings | null;
  features?: MediaFeatures | null;
  classification?: ClassificationResult | null;
  naming?: NamingResult | null;
  captured_at?: string | null;
  date_source?: string | null;
}

export interface MediaCounts {
  discovered: number;
  processed: number;
  failed: number;
  skipped: number;
}

export interface ReportSummary {
  discovered: number;
  processed: number;
  failed: number;
  skipped: number;
  duration_seconds: number;
  images?: MediaCounts | null;
  videos?: MediaCounts | null;
}

export interface NamingConfiguration {
  source: string;
  profile: string;
  template: string;
  language: string;
  transliterate: boolean;
  config_version: string | null;
}

export interface InferenceInfo {
  requested_backend: string;
  actual_backend: string;
  runtime: string;
  runtime_version: string | null;
  execution_provider: string | null;
  device_name: string | null;
  model_id: string | null;
  model_version?: string | null;
  fallback_occurred: boolean;
  fallback_reason: string | null;
  directml_available: boolean;
  cuda_available?: boolean;
  /** Every candidate auto weighed, in priority order, with the reason. */
  considered?: BackendCandidate[];
}

export interface BackendCandidate {
  backend_id: string;
  available: boolean;
  can_caption: boolean;
  reason: string;
}

export interface ScanReport {
  schema_version: string;
  created_at: string;
  source_directory: string;
  recursive: boolean;
  model: { provider: string; name: string; device: string };
  summary: ReportSummary;
  files: ScanFileEntry[];
  naming_configuration?: NamingConfiguration | null;
  inference?: InferenceInfo | null;
}

export type BackendId =
  | "auto"
  | "onnx-cuda"
  | "onnx-directml"
  | "onnx-cpu"
  | "pytorch-cpu";

/** Order shown in Settings; mirrors BACKEND_PRIORITY in Python. */
export const BACKEND_OPTIONS: Array<{ id: BackendId; label: string }> = [
  { id: "auto", label: "Automatic (best available)" },
  { id: "onnx-cuda", label: "NVIDIA GPU (CUDA)" },
  { id: "onnx-directml", label: "AMD / Intel GPU (DirectML)" },
  { id: "onnx-cpu", label: "CPU (ONNX Runtime)" },
  { id: "pytorch-cpu", label: "CPU (PyTorch)" },
];

export interface BackendDiagnostics {
  backend_id: string;
  available: boolean;
  runtime: string;
  initialized: boolean;
  model_loaded: boolean;
  execution_provider: string | null;
  device_name: string | null;
  runtime_version: string | null;
  model_id: string | null;
  self_test_passed: boolean | null;
  inference_ms: number | null;
  error: string | null;
  notes: string[];
}

export interface BenchmarkResult {
  backend: string;
  available: boolean;
  execution_provider: string | null;
  device_name: string | null;
  runtime: string;
  runtime_version: string | null;
  runs: number;
  warmup_runs: number;
  cold_start_ms: number | null;
  per_run_ms: number[];
  average_ms: number | null;
  peak_ram_mb?: number | null;
  error: string | null;
}

export interface InferenceEnvironment {
  backends: Array<{
    backend_id: string;
    label?: string;
    available: boolean;
    can_caption?: boolean;
    error?: string | null;
  }>;
  directml_available: boolean;
  cuda_available?: boolean;
  gpu_name: string | null;
  cuda_device_name?: string | null;
  adapters?: string[];
  /** What "auto" would choose right now, and why each was ranked so. */
  auto_backend?: string | null;
  auto_considered?: BackendCandidate[];
  error?: string;
}

/* ------------------------------------------------------------------ */
/* Worker protocol                                                     */
/* ------------------------------------------------------------------ */

export type WorkerCommand =
  | "ping"
  | "shutdown"
  | "cancel"
  | "scan"
  | "load_report"
  | "save_report"
  | "validate_report"
  | "build_rename_plan"
  | "apply_rename"
  | "undo"
  | "regenerate_names"
  | "get_profiles"
  | "get_config"
  | "get_environment"
  | "make_thumbnail"
  | "test_backend"
  | "benchmark_backend"
  | "list_backends";

export interface WorkerRequest {
  request_id: string;
  command: WorkerCommand;
  payload?: Record<string, unknown>;
}

export type WorkerEventName =
  | "started"
  | "phase"
  | "file_started"
  | "file_completed"
  | "frame_progress"
  | "progress"
  | "completed"
  | "error";

export interface WorkerEvent {
  request_id: string;
  event: WorkerEventName | string;
  data: Record<string, unknown>;
}

export interface WorkerErrorData {
  code: string;
  message: string;
  recoverable: boolean;
}

/* ------------------------------------------------------------------ */
/* Validation / plans / results                                        */
/* ------------------------------------------------------------------ */

export interface ValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  path: string | null;
  entry_index: number | null;
}

export interface ValidationResult {
  valid: boolean;
  entries: number;
  ready: number;
  skipped: number;
  conflicts: number;
  missing: number;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface RenamePlanItem {
  entry_index: number;
  original_path: string;
  original_name: string;
  action: "rename" | "skip";
  target_name: string | null;
  final_path: string | null;
  skip_reason: string | null;
  conflict_resolved: boolean;
}

export interface RenamePlan {
  items: RenamePlanItem[];
  rename_count: number;
  skip_count: number;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  valid: boolean;
  log_path: string;
}

export interface RenameOperation {
  original_path: string;
  final_path: string;
  temporary_path: string | null;
  size_bytes: number | null;
  status: string;
  error: string | null;
}

export interface RenameResult {
  status: string;
  renamed: number;
  failed: number;
  rolled_back: number;
  skipped: number;
  log_path: string;
  error: string | null;
  all_restored: boolean;
  operations: RenameOperation[];
}

export interface UndoResult {
  status: string;
  restored: number;
  failed?: number;
  error?: string | null;
  log_path?: string;
  errors?: ValidationIssue[];
  operations?: Array<RenameOperation | { from: string; to: string }>;
}

export interface ProfileInfo {
  name: string;
  template: string;
  language: string;
  max_filename_length: number;
  built_in: boolean;
}

export interface EnvironmentStatus {
  python: {
    executable: string | null;
    source: string;
    version: string | null;
    ok: boolean;
    message: string | null;
  };
  worker_running: boolean;
  repo_root: string | null;
}

export interface WorkerEnvironment {
  python: { executable: string; version: string; ok: boolean };
  filesight: { version: string; ok: boolean };
  model: {
    loaded: boolean;
    name: string | null;
    cache: string | null;
    cached?: boolean;
  };
  ffmpeg: { available: boolean; path?: string | null; version?: string | null; message?: string };
  ffprobe: { available: boolean; path?: string | null; version?: string | null; message?: string };
  config: { ok: boolean; source?: string; default_profile?: string; message?: string };
  inference?: InferenceEnvironment;
}

export interface AppSettings {
  python_path: string | null;
  ffmpeg_path: string | null;
  ffprobe_path: string | null;
  config_path: string | null;
  default_profile: string;
  default_recursive: boolean;
  default_include_videos: boolean;
  report_filename: string;
  last_directory: string | null;
  last_report_path: string | null;
  last_log_path: string | null;
  onboarding_seen: boolean;
  backend: string;
  allow_fallback: boolean;
}

/* ------------------------------------------------------------------ */
/* UI state machine                                                    */
/* ------------------------------------------------------------------ */

export type UiState =
  | "idle"
  | "environment_check"
  | "folder_selected"
  | "scanning"
  | "loading_model"
  | "analyzing"
  | "cancelling"
  | "report_ready"
  | "validating"
  | "rename_preview"
  | "renaming"
  | "rename_completed"
  | "rename_failed"
  | "undoing"
  | "error";

export interface ScanOptions {
  directory: string;
  recursive: boolean;
  includeImages: boolean;
  includeVideos: boolean;
  profile: string;
  maxFiles: number | null;
  videoFrames: number;
  maxVideoDuration: number;
  allowLongVideos: boolean;
  configPath: string | null;
  language: string | null;
  transliterate: boolean | null;
  outputPath: string | null;
}
