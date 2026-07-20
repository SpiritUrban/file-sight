"""Building and writing the JSON report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from filesight.models import (
    SCHEMA_VERSION,
    FileEntry,
    ModelInfo,
    Report,
    Summary,
)


def build_report(
    source_directory: Path,
    recursive: bool,
    model: ModelInfo,
    entries: list[FileEntry],
    discovered: int,
    duration_seconds: float,
) -> Report:
    processed = sum(1 for e in entries if e.status == "success")
    failed = sum(1 for e in entries if e.status == "failed")
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
            duration_seconds=round(duration_seconds, 2),
        ),
        files=entries,
    )


def write_report(report: Report, output_path: Path) -> None:
    """Write the report as readable UTF-8 JSON."""
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
