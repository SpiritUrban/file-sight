"""Shared helpers for iteration-2 tests. No neural network involved."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional


def make_file(path: Path, content: bytes = b"image-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entry_for(
    path: Path,
    suggested: Optional[str],
    status: str = "success",
    with_metadata: bool = True,
    **overrides: Any,
) -> dict:
    entry: dict[str, Any] = {
        "original_path": str(path),
        "original_name": path.name,
        "extension": path.suffix,
        "status": status,
        "caption": "a test caption",
        "suggested_name": suggested,
        "processing_time_ms": 1,
        "error": None,
    }
    if with_metadata and path.exists():
        stat = path.stat()
        entry["source_metadata"] = {
            "size_bytes": stat.st_size,
            "modified_at_ns": stat.st_mtime_ns,
        }
    entry.update(overrides)
    return entry


def report_dict(entries: list[dict], schema_version: str = "1.1") -> dict:
    return {
        "schema_version": schema_version,
        "created_at": "2026-07-21T00:00:00Z",
        "source_directory": "irrelevant",
        "recursive": False,
        "model": {"provider": "huggingface", "name": "fake", "device": "cpu"},
        "summary": {
            "discovered": len(entries),
            "processed": len(entries),
            "failed": 0,
            "duration_seconds": 0.1,
        },
        "files": entries,
    }


def error_codes(plan_or_issues) -> list[str]:
    issues = getattr(plan_or_issues, "issues", plan_or_issues)
    return [issue.code for issue in issues if issue.severity == "error"]
