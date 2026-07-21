"""Re-apply naming rules to an existing report, without any vision model.

Reads the captions already stored in a report and regenerates features,
classification and suggested names under a (possibly different) profile.
Media files are never touched.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from filesight.config import FileSightConfig
from filesight.models import SCHEMA_VERSION, NamingConfiguration
from filesight.naming_preview import NamingSession
from filesight.profiles import NamingProfile


@dataclass
class SuggestionChange:
    original_name: str
    old_name: Optional[str]
    new_name: Optional[str]
    skipped_reason: Optional[str] = None

    @property
    def changed(self) -> bool:
        return self.skipped_reason is None and self.old_name != self.new_name


def _captured_at_of(entry: dict) -> Optional[str]:
    """Reuse a stored capture date, else fall back to source metadata mtime."""
    existing = entry.get("captured_at")
    if isinstance(existing, str) and existing:
        return existing
    metadata = entry.get("source_metadata")
    if isinstance(metadata, dict):
        mtime_ns = metadata.get("modified_at_ns")
        if isinstance(mtime_ns, int) and mtime_ns > 0:
            try:
                return datetime.fromtimestamp(mtime_ns / 1_000_000_000).isoformat(
                    timespec="seconds"
                )
            except (OverflowError, OSError, ValueError):
                return None
    return None


def regenerate_suggestions(
    report: dict,
    profile: NamingProfile,
    config: Optional[FileSightConfig] = None,
    template: Optional[str] = None,
) -> tuple[dict, list[SuggestionChange]]:
    """Return (new report dict, per-entry changes). Input dict is not mutated."""
    updated = json.loads(json.dumps(report))  # deep copy, JSON-safe by construction
    session = NamingSession(
        profile,
        category_rules=config.category_rules if config else None,
        template=template,
    )
    changes: list[SuggestionChange] = []

    for entry in updated.get("files", []):
        original_name = entry.get("original_name") or ""
        old_name = entry.get("suggested_name")
        caption = entry.get("caption")
        status = entry.get("status")

        # Entries without usable data keep whatever they had.
        if status != "success" or not caption:
            changes.append(
                SuggestionChange(
                    original_name=original_name,
                    old_name=old_name,
                    new_name=old_name,
                    skipped_reason=(
                        f"status is {status}" if status != "success" else "no caption"
                    ),
                )
            )
            continue

        outcome = session.name_for(
            entry.get("original_path") or original_name,
            original_name,
            caption,
            media_type=entry.get("media_type", "image"),
            captured_at=_captured_at_of(entry),
            text=(entry.get("features") or {}).get("text"),
        )
        entry["features"] = _features_dict(outcome.features)
        entry["classification"] = asdict(outcome.classification)
        entry["naming"] = asdict(outcome.naming)
        entry["suggested_name"] = outcome.naming.suggested_name
        changes.append(
            SuggestionChange(
                original_name=original_name,
                old_name=old_name,
                new_name=outcome.naming.suggested_name,
            )
        )

    updated["schema_version"] = SCHEMA_VERSION
    updated["naming_configuration"] = asdict(
        NamingConfiguration(
            source=config.source if config else "built-in",
            profile=profile.name,
            template=template or profile.template,
            language=profile.language,
            transliterate=profile.transliterate,
            config_version=config.config_version if config else None,
        )
    )
    return updated, changes


def _features_dict(features: Any) -> dict:
    data = asdict(features)
    for redundant in ("media_type", "original_stem", "caption"):
        data.pop(redundant, None)
    return data


def write_report_dict(data: dict, path: Path) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
