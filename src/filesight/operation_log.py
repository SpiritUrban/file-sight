"""The rename operation log: the source of truth for undo and recovery.

The log is written atomically (temp file + flush + os.replace) and is
updated during the operation, not only at the end.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LOG_SCHEMA_VERSION = "1.0"

# Operation/log statuses used across rename and undo:
# planned, in_progress, completed, failed, rolled_back,
# partially_rolled_back, undone, partially_undone


@dataclass
class RenameOperationItem:
    original_path: str
    final_path: str
    temporary_path: Optional[str] = None
    size_bytes: Optional[int] = None
    status: str = "planned"
    error: Optional[str] = None


@dataclass
class LogSummary:
    planned: int = 0
    completed: int = 0
    failed: int = 0
    rolled_back: int = 0
    undone: int = 0


@dataclass
class RenameOperationLog:
    schema_version: str
    operation_id: str
    created_at: str
    report_path: str
    status: str
    summary: LogSummary = field(default_factory=LogSummary)
    operations: list[RenameOperationItem] = field(default_factory=list)
    completed_at: Optional[str] = None
    undone_at: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def refresh_summary(self) -> None:
        counts = {"completed": 0, "failed": 0, "rolled_back": 0, "undone": 0}
        for op in self.operations:
            if op.status in counts:
                counts[op.status] += 1
        self.summary = LogSummary(planned=len(self.operations), **counts)


class LogLoadError(Exception):
    """The operation log cannot be used (missing, broken, unsupported)."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_log_path(report_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return report_path.parent / f"filesight-rename-log-{stamp}.json"


def write_log(log: RenameOperationLog, path: Path) -> None:
    """Atomically replace the log file: temp write, flush+fsync, replace."""
    temp_path = path.with_name(path.name + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(log.to_dict(), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def load_log(path: Path) -> RenameOperationLog:
    if not path.exists():
        raise LogLoadError(f"Log file does not exist: {path}")
    if not path.is_file():
        raise LogLoadError(f"Log path is not a file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LogLoadError(f"Cannot read log {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise LogLoadError("Log root must be a JSON object.")
    if data.get("schema_version") != LOG_SCHEMA_VERSION:
        raise LogLoadError(
            f"Unsupported log schema_version: {data.get('schema_version')!r}"
        )
    raw_ops = data.get("operations")
    if not isinstance(raw_ops, list):
        raise LogLoadError("Log has no 'operations' list.")
    operations = []
    for index, raw in enumerate(raw_ops):
        if not isinstance(raw, dict) or not raw.get("original_path") or not raw.get(
            "final_path"
        ):
            raise LogLoadError(f"Log operation {index} is malformed.")
        operations.append(
            RenameOperationItem(
                original_path=raw["original_path"],
                final_path=raw["final_path"],
                temporary_path=raw.get("temporary_path"),
                size_bytes=raw.get("size_bytes"),
                status=raw.get("status", "planned"),
                error=raw.get("error"),
            )
        )
    summary_raw = data.get("summary") or {}
    log = RenameOperationLog(
        schema_version=data["schema_version"],
        operation_id=str(data.get("operation_id", "")),
        created_at=str(data.get("created_at", "")),
        report_path=str(data.get("report_path", "")),
        status=str(data.get("status", "")),
        summary=LogSummary(
            planned=summary_raw.get("planned", len(operations)),
            completed=summary_raw.get("completed", 0),
            failed=summary_raw.get("failed", 0),
            rolled_back=summary_raw.get("rolled_back", 0),
            undone=summary_raw.get("undone", 0),
        ),
        operations=operations,
        completed_at=data.get("completed_at"),
        undone_at=data.get("undone_at"),
        error=data.get("error"),
    )
    return log
