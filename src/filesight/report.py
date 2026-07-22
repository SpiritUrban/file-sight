"""Building and writing the JSON report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from filesight.models import (
    MEDIA_VIDEO,
    InferenceInfo,
    NamingConfiguration,
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    FileEntry,
    MediaCounts,
    ModelInfo,
    Report,
    Summary,
)


class ReportLoadError(Exception):
    """The report file cannot be used at all (missing, broken, unsupported)."""


def load_report_dict(report_path: Path) -> dict:
    """Load and structurally check a scan report for validate/rename.

    Raises ReportLoadError with a user-readable message on fatal problems.
    """
    if not report_path.exists():
        raise ReportLoadError(f"Report file does not exist: {report_path}")
    if not report_path.is_file():
        raise ReportLoadError(f"Report path is not a file: {report_path}")
    try:
        # utf-8-sig: tolerate the BOM that Notepad/PowerShell add when
        # the user edits the report by hand
        raw = report_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ReportLoadError(f"Cannot read report {report_path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReportLoadError(f"Report is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReportLoadError("Report root must be a JSON object.")
    version = data.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise ReportLoadError(
            f"Unsupported schema_version {version!r} (supported: {supported}). "
            "Re-run 'filesight scan' to generate a fresh report."
        )
    files = data.get("files")
    if not isinstance(files, list):
        raise ReportLoadError("Report has no 'files' list.")
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            raise ReportLoadError(f"Entry {index} in 'files' is not an object.")
    return data


def _counts_for(entries: list[FileEntry]) -> MediaCounts:
    return MediaCounts(
        discovered=len(entries),
        processed=sum(1 for e in entries if e.status == "success"),
        failed=sum(1 for e in entries if e.status == "failed"),
        skipped=sum(1 for e in entries if e.status == "skipped"),
    )


def build_report(
    source_directory: Path,
    recursive: bool,
    model: ModelInfo,
    entries: list[FileEntry],
    discovered: int,
    duration_seconds: float,
    videos_enabled: bool = False,
    naming_configuration: Optional["NamingConfiguration"] = None,
    inference: Optional["InferenceInfo"] = None,
) -> Report:
    processed = sum(1 for e in entries if e.status == "success")
    failed = sum(1 for e in entries if e.status == "failed")
    skipped = sum(1 for e in entries if e.status == "skipped")

    images = videos = None
    if videos_enabled:
        image_entries = [e for e in entries if e.media_type != MEDIA_VIDEO]
        video_entries = [e for e in entries if e.media_type == MEDIA_VIDEO]
        images = _counts_for(image_entries)
        videos = _counts_for(video_entries)

    return Report(
        schema_version=SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source_directory=str(source_directory),
        recursive=recursive,
        model=model,
        summary=Summary(
            discovered=discovered,
            processed=processed,
            failed=failed,
            skipped=skipped,
            duration_seconds=round(duration_seconds, 2),
            images=images,
            videos=videos,
        ),
        files=entries,
        naming_configuration=naming_configuration,
        inference=inference,
    )


def write_report(report: Report, output_path: Path) -> None:
    """Write the report as readable UTF-8 JSON."""
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
