"""Data structures for the FileSight JSON report."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1"}


@dataclass
class FileError:
    type: str
    message: str


@dataclass
class SourceMetadata:
    """Fingerprint of the source file taken during scan.

    Used before renaming to detect that the file was replaced or
    modified after the report was generated.
    """

    size_bytes: int
    modified_at_ns: int


@dataclass
class FileEntry:
    original_path: str
    original_name: str
    extension: str
    status: str  # "success" | "failed"
    caption: Optional[str]
    suggested_name: Optional[str]
    processing_time_ms: int
    error: Optional[FileError] = None
    source_metadata: Optional[SourceMetadata] = None
    rename_enabled: bool = True


@dataclass
class ModelInfo:
    provider: str
    name: str
    device: str


@dataclass
class Summary:
    discovered: int
    processed: int
    failed: int
    duration_seconds: float


@dataclass
class Report:
    schema_version: str
    created_at: str
    source_directory: str
    recursive: bool
    model: ModelInfo
    summary: Summary
    files: list[FileEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    path: Optional[str] = None
    entry_index: Optional[int] = None
