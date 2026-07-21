/**
 * Runtime validation for everything crossing the worker boundary.
 *
 * A malformed event must never take the UI down, so parsers return a
 * discriminated result instead of throwing.
 */
import { z } from "zod";

export const workerEventSchema = z.object({
  request_id: z.string(),
  event: z.string(),
  data: z.unknown().transform((value) =>
    value && typeof value === "object" ? (value as Record<string, unknown>) : {},
  ),
});

export const fileErrorSchema = z.object({
  type: z.string(),
  message: z.string(),
});

export const featuresSchema = z.object({
  subject: z.string().nullable().default(null),
  action: z.string().nullable().default(null),
  location: z.string().nullable().default(null),
  objects: z.array(z.string()).default([]),
  text: z.string().nullable().default(null),
});

export const classificationSchema = z.object({
  category: z.string(),
  category_label: z.string(),
  confidence: z.number(),
  method: z.string(),
  matched_rules: z.array(z.string()).default([]),
});

export const namingSchema = z.object({
  profile: z.string(),
  template: z.string(),
  language: z.string(),
  transliterated: z.boolean(),
  base_name: z.string(),
  suggested_name: z.string(),
  warnings: z.array(z.string()).default([]),
});

export const videoMetadataSchema = z.object({
  duration_seconds: z.number(),
  width: z.number().nullable(),
  height: z.number().nullable(),
  frame_rate: z.number().nullable(),
  video_codec: z.string().nullable(),
  container: z.string().nullable(),
  has_audio: z.boolean(),
  rotation_degrees: z.number(),
  creation_time: z.string().nullable().optional(),
});

export const videoAnalysisSchema = z.object({
  requested_frames: z.number(),
  extracted_frames: z.number(),
  usable_frames: z.number(),
  analyzed_frames: z.number(),
  frames: z
    .array(
      z.object({
        index: z.number(),
        timestamp_seconds: z.number(),
        status: z.string(),
        caption: z.string().nullable().default(null),
        skip_reason: z.string().nullable().default(null),
        error: fileErrorSchema.nullable().default(null),
      }),
    )
    .default([]),
  warnings: z.array(z.string()).default([]),
});

export const fileEntrySchema = z.object({
  original_path: z.string(),
  original_name: z.string(),
  extension: z.string(),
  status: z.enum(["success", "failed", "skipped"]),
  caption: z.string().nullable(),
  suggested_name: z.string().nullable(),
  processing_time_ms: z.number(),
  media_type: z.enum(["image", "video"]).default("image"),
  error: fileErrorSchema.nullable().default(null),
  source_metadata: z
    .object({ size_bytes: z.number(), modified_at_ns: z.number() })
    .nullable()
    .optional(),
  rename_enabled: z.boolean().default(true),
  video_metadata: videoMetadataSchema.nullable().optional(),
  video_analysis: videoAnalysisSchema.nullable().optional(),
  timings: z
    .object({
      probe_ms: z.number(),
      frame_extraction_ms: z.number(),
      captioning_ms: z.number(),
      aggregation_ms: z.number(),
      total_ms: z.number(),
    })
    .nullable()
    .optional(),
  features: featuresSchema.nullable().optional(),
  classification: classificationSchema.nullable().optional(),
  naming: namingSchema.nullable().optional(),
  captured_at: z.string().nullable().optional(),
  date_source: z.string().nullable().optional(),
});

export const reportSchema = z.object({
  schema_version: z.string(),
  created_at: z.string(),
  source_directory: z.string(),
  recursive: z.boolean(),
  model: z.object({
    provider: z.string(),
    name: z.string(),
    device: z.string(),
  }),
  summary: z.object({
    discovered: z.number(),
    processed: z.number(),
    failed: z.number(),
    skipped: z.number().default(0),
    duration_seconds: z.number(),
    images: z.unknown().optional(),
    videos: z.unknown().optional(),
  }),
  files: z.array(fileEntrySchema),
  naming_configuration: z.unknown().optional(),
});

export const validationIssueSchema = z.object({
  severity: z.enum(["error", "warning"]),
  code: z.string(),
  message: z.string(),
  path: z.string().nullable().default(null),
  entry_index: z.number().nullable().default(null),
});

export const validationResultSchema = z.object({
  valid: z.boolean(),
  entries: z.number(),
  ready: z.number(),
  skipped: z.number(),
  conflicts: z.number(),
  missing: z.number(),
  errors: z.array(validationIssueSchema).default([]),
  warnings: z.array(validationIssueSchema).default([]),
});

export const renamePlanSchema = z.object({
  items: z.array(
    z.object({
      entry_index: z.number(),
      original_path: z.string(),
      original_name: z.string(),
      action: z.enum(["rename", "skip"]),
      target_name: z.string().nullable(),
      final_path: z.string().nullable(),
      skip_reason: z.string().nullable(),
      conflict_resolved: z.boolean(),
    }),
  ),
  rename_count: z.number(),
  skip_count: z.number(),
  errors: z.array(validationIssueSchema).default([]),
  warnings: z.array(validationIssueSchema).default([]),
  valid: z.boolean(),
  log_path: z.string(),
});

export const renameResultSchema = z.object({
  status: z.string(),
  renamed: z.number().default(0),
  failed: z.number().default(0),
  rolled_back: z.number().default(0),
  skipped: z.number().default(0),
  log_path: z.string().default(""),
  error: z.string().nullable().default(null),
  all_restored: z.boolean().default(true),
  operations: z.array(z.unknown()).default([]),
});

export const undoResultSchema = z.object({
  status: z.string(),
  restored: z.number().default(0),
  failed: z.number().optional(),
  error: z.string().nullable().optional(),
  log_path: z.string().optional(),
  errors: z.array(validationIssueSchema).optional(),
  operations: z.array(z.unknown()).optional(),
});

export const profilesSchema = z.object({
  profiles: z.array(
    z.object({
      name: z.string(),
      template: z.string(),
      language: z.string(),
      max_filename_length: z.number(),
      built_in: z.boolean(),
    }),
  ),
  default_profile: z.string(),
  source: z.string(),
  warning: z.string().nullable().optional(),
});

export const workerEnvironmentSchema = z.object({
  python: z.object({
    executable: z.string(),
    version: z.string(),
    ok: z.boolean(),
  }),
  filesight: z.object({ version: z.string(), ok: z.boolean() }),
  model: z.object({
    loaded: z.boolean(),
    name: z.string().nullable(),
    cache: z.string().nullable(),
    cached: z.boolean().optional(),
  }),
  ffmpeg: z.object({
    available: z.boolean(),
    path: z.string().nullable().optional(),
    version: z.string().nullable().optional(),
    message: z.string().optional(),
  }),
  ffprobe: z.object({
    available: z.boolean(),
    path: z.string().nullable().optional(),
    version: z.string().nullable().optional(),
    message: z.string().optional(),
  }),
  config: z.object({
    ok: z.boolean(),
    source: z.string().optional(),
    default_profile: z.string().optional(),
    message: z.string().optional(),
  }),
});

export type ParseOutcome<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

/** Validate without throwing, so one bad payload cannot break the UI. */
export function safeParse<T>(
  schema: { safeParse: (input: unknown) => { success: boolean; data?: unknown; error?: unknown } },
  input: unknown,
): ParseOutcome<T> {
  const result = schema.safeParse(input);
  if (result.success) {
    return { ok: true, value: result.data as T };
  }
  const issue = result.error as { issues?: Array<{ path: unknown[]; message: string }> };
  const first = issue?.issues?.[0];
  const where = first ? `${first.path.join(".") || "(root)"}: ${first.message}` : "unknown";
  return { ok: false, error: where };
}
