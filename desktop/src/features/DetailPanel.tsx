import { useState } from "react";

import { Thumbnail } from "@/components/Thumbnail";
import { useTranslation } from "@/lib/i18n";
import { useAppStore } from "@/stores/appStore";
import type { ScanFileEntry } from "@/types";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2 py-0.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="break-words">{value}</dd>
    </div>
  );
}

function VideoDetails({ entry }: { entry: ScanFileEntry }) {
  const { t } = useTranslation();
  const meta = entry.video_metadata;
  const analysis = entry.video_analysis;
  if (!meta) return null;
  return (
    <>
      <Row label={t("Duration")} value={`${meta.duration_seconds.toFixed(1)} s`} />
      <Row
        label={t("Resolution")}
        value={meta.width && meta.height ? `${meta.width} × ${meta.height}` : null}
      />
      <Row label={t("Codec")} value={meta.video_codec} />
      <Row label={t("Audio")} value={meta.has_audio ? t("yes") : t("no")} />
      {analysis ? (
        <>
          <Row
            label={t("Frames")}
            value={`${analysis.usable_frames} usable of ${analysis.extracted_frames} extracted`}
          />
          {analysis.frames.length > 0 ? (
            <div className="py-1">
              <p className="text-slate-500">Frame captions</p>
              <ul className="mt-1 space-y-0.5">
                {analysis.frames.map((frame) => (
                  <li key={frame.index} className="text-xs">
                    <span className="text-slate-400">
                      {frame.timestamp_seconds.toFixed(1)}s
                    </span>{" "}
                    {frame.status === "success"
                      ? frame.caption
                      : `(${frame.skip_reason ?? frame.status})`}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
    </>
  );
}

export function DetailPanel() {
  const { t } = useTranslation();
  const report = useAppStore((s) => s.report);
  const selectedPath = useAppStore((s) => s.selectedPath);
  const [showTechnical, setShowTechnical] = useState(false);

  const entry = report?.files.find((f) => f.original_path === selectedPath);

  if (!entry) {
    return (
      <aside className="panel w-80 shrink-0 p-4 text-sm text-slate-500">
        Select a file to see its details.
      </aside>
    );
  }

  return (
    <aside
      className="panel flex w-80 shrink-0 flex-col overflow-auto p-4 text-sm"
      aria-label={t("File details")}
    >
      <div className="mb-3 flex justify-center">
        <Thumbnail entry={entry} size={220} className="rounded-md" />
      </div>

      <h3 className="mb-2 break-words font-semibold">{entry.original_name}</h3>

      <dl className="space-y-0.5">
        <Row label={t("Suggested name")} value={entry.suggested_name} />
        <Row label={t("Caption")} value={entry.caption} />
        <Row label={t("Media type")} value={entry.media_type} />
        <Row label={t("Category")} value={entry.classification?.category} />
        <Row
          label={t("Confidence")}
          value={
            entry.classification
              ? `${entry.classification.confidence.toFixed(2)} (rule-based)`
              : null
          }
        />
        <Row label={t("Subject")} value={entry.features?.subject} />
        <Row label={t("Action")} value={entry.features?.action} />
        <Row label={t("Location")} value={entry.features?.location} />
        <Row
          label={t("Objects")}
          value={entry.features?.objects?.length ? entry.features.objects.join(", ") : null}
        />
        <Row label={t("Captured")} value={entry.captured_at} />
        <Row label={t("Date source")} value={entry.date_source} />
        <VideoDetails entry={entry} />
        <Row
          label={t("Warnings")}
          value={entry.naming?.warnings?.length ? entry.naming.warnings.join(", ") : null}
        />
        {entry.error ? (
          <div className="mt-2 rounded border border-red-200 bg-red-50 p-2">
            <p className="font-medium text-red-800">{entry.error.type}</p>
            <p className="text-red-700">{entry.error.message}</p>
          </div>
        ) : null}
      </dl>

      <button
        type="button"
        className="mt-3 self-start text-xs text-blue-700 hover:underline"
        onClick={() => setShowTechnical((value) => !value)}
        aria-expanded={showTechnical}
      >
        {showTechnical ? t("Hide technical details") : t("Technical details")}
      </button>
      {showTechnical ? (
        <dl className="mt-2 space-y-0.5 text-xs">
          <Row label={t("Original path")} value={entry.original_path} />
          <Row label={t("Template")} value={entry.naming?.template} />
          <Row label={t("Profile")} value={entry.naming?.profile} />
          <Row
            label="Matched rules"
            value={entry.classification?.matched_rules?.join(", ")}
          />
          <Row label="Processing time" value={`${entry.processing_time_ms} ms`} />
          <Row label="Timings" value={entry.timings ? `${entry.timings.total_ms} ms total` : null} />
        </dl>
      ) : null}
    </aside>
  );
}
