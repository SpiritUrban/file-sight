"""Data structures for the FileSight JSON report."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

SCHEMA_VERSION = "1.3"
SUPPORTED_SCHEMA_VERSIONS = {"1.0", "1.1", "1.2", "1.3"}

MEDIA_IMAGE = "image"
MEDIA_VIDEO = "video"


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
class VideoMetadata:
    duration_seconds: float
    width: Optional[int]
    height: Optional[int]
    frame_rate: Optional[float]
    video_codec: Optional[str]
    container: Optional[str]
    has_audio: bool
    rotation_degrees: int
    creation_time: Optional[str] = None


@dataclass
class VideoFrameResult:
    index: int
    timestamp_seconds: float
    status: str  # "success" | "skipped" | "failed"
    caption: Optional[str] = None
    skip_reason: Optional[str] = None
    error: Optional[FileError] = None


@dataclass
class VideoAnalysis:
    requested_frames: int
    extracted_frames: int
    usable_frames: int
    analyzed_frames: int
    frames: list[VideoFrameResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Timings:
    probe_ms: int = 0
    frame_extraction_ms: int = 0
    captioning_ms: int = 0
    aggregation_ms: int = 0
    total_ms: int = 0


@dataclass
class MediaFeatures:
    """Structured facts pulled out of a caption and file metadata."""

    subject: Optional[str] = None
    action: Optional[str] = None
    location: Optional[str] = None
    objects: list[str] = field(default_factory=list)
    text: Optional[str] = None
    media_type: str = MEDIA_IMAGE
    original_stem: str = ""
    caption: Optional[str] = None


@dataclass
class ClassificationResult:
    category: str
    category_label: str
    confidence: float
    method: str
    matched_rules: list[str] = field(default_factory=list)


@dataclass
class NamingResult:
    profile: str
    template: str
    language: str
    transliterated: bool
    base_name: str
    suggested_name: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class MediaDateResult:
    captured_at: Optional[str]
    date_source: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class NamingConfiguration:
    """What produced the names in this report (for reproducibility)."""

    source: str
    profile: str
    template: str
    language: str
    transliterate: bool
    config_version: Optional[str] = None


@dataclass
class FileEntry:
    original_path: str
    original_name: str
    extension: str
    status: str  # "success" | "failed" | "skipped"
    caption: Optional[str]
    suggested_name: Optional[str]
    processing_time_ms: int
    media_type: str = MEDIA_IMAGE
    error: Optional[FileError] = None
    source_metadata: Optional[SourceMetadata] = None
    rename_enabled: bool = True
    video_metadata: Optional[VideoMetadata] = None
    video_analysis: Optional[VideoAnalysis] = None
    timings: Optional[Timings] = None
    features: Optional[MediaFeatures] = None
    classification: Optional[ClassificationResult] = None
    naming: Optional[NamingResult] = None
    captured_at: Optional[str] = None
    date_source: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Keep entries clean: drop optional sections when unused.
        for key, value in (
            ("video_metadata", self.video_metadata),
            ("video_analysis", self.video_analysis),
            ("timings", self.timings),
            ("features", self.features),
            ("classification", self.classification),
            ("naming", self.naming),
        ):
            if value is None:
                data.pop(key, None)
        if self.features is not None:
            # media_type/original_stem/caption duplicate the entry fields
            for redundant in ("media_type", "original_stem", "caption"):
                data["features"].pop(redundant, None)
        return data


@dataclass
class ModelInfo:
    provider: str
    name: str
    device: str


@dataclass
class MediaCounts:
    discovered: int = 0
    processed: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class Summary:
    discovered: int
    processed: int
    failed: int
    duration_seconds: float
    skipped: int = 0
    images: Optional[MediaCounts] = None
    videos: Optional[MediaCounts] = None


@dataclass
class Report:
    schema_version: str
    created_at: str
    source_directory: str
    recursive: bool
    model: ModelInfo
    summary: Summary
    files: list[FileEntry] = field(default_factory=list)
    naming_configuration: Optional[NamingConfiguration] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["files"] = [entry.to_dict() for entry in self.files]
        if self.summary.images is None:
            data["summary"].pop("images", None)
        if self.summary.videos is None:
            data["summary"].pop("videos", None)
        if self.naming_configuration is None:
            data.pop("naming_configuration", None)
        return data


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    path: Optional[str] = None
    entry_index: Optional[int] = None
