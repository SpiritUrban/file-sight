"""Building the rename plan from a validated report.

Combines per-entry validation, skip rules, --limit, conflict detection
and optional automatic conflict resolution into one deterministic plan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from filesight.models import ValidationIssue
from filesight.validation import (
    SKIP_DUPLICATE_SOURCE,
    SKIP_INVALID,
    SKIP_OVER_LIMIT,
    evaluate_entry,
)


@dataclass
class PlanItem:
    entry_index: int
    original_path: str
    original_name: str
    action: str  # "rename" | "skip"
    target_name: Optional[str] = None
    final_path: Optional[str] = None
    skip_reason: Optional[str] = None
    conflict_resolved: bool = False


@dataclass
class RenamePlan:
    report_path: str
    items: list[PlanItem] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    entries_total: int = 0
    missing_metadata_count: int = 0

    @property
    def renames(self) -> list[PlanItem]:
        return [item for item in self.items if item.action == "rename"]

    @property
    def skipped(self) -> list[PlanItem]:
        return [item for item in self.items if item.action == "skip"]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]


def _path_key(path: str | Path) -> str:
    """Case-insensitive absolute key for comparing Windows paths."""
    return os.path.normcase(os.path.abspath(str(path)))


def _numbered_name(target_name: str, number: int) -> str:
    stem, ext = os.path.splitext(target_name)
    return f"{stem}-{number:03d}{ext}"


def build_plan(
    report: dict,
    report_path: Path,
    resolve_conflicts: bool = False,
    limit: Optional[int] = None,
) -> RenamePlan:
    """Build a deterministic plan in report order. Read-only, never renames."""
    entries: list[dict] = report["files"]
    plan = RenamePlan(report_path=str(report_path), entries_total=len(entries))

    seen_sources: dict[str, int] = {}
    rename_count = 0
    for index, entry in enumerate(entries):
        evaluation = evaluate_entry(index, entry)
        plan.issues.extend(evaluation.issues)
        if evaluation.missing_metadata:
            plan.missing_metadata_count += 1

        item = PlanItem(
            entry_index=index,
            original_path=str(entry.get("original_path") or ""),
            original_name=evaluation.original_name or str(entry.get("original_name")),
            action="skip",
        )
        if evaluation.has_errors:
            item.skip_reason = SKIP_INVALID
        elif evaluation.skip_reason is not None:
            item.skip_reason = evaluation.skip_reason
        else:
            source_key = _path_key(evaluation.source)
            if source_key in seen_sources:
                plan.issues.append(
                    ValidationIssue(
                        severity="error",
                        code="DUPLICATE_SOURCE",
                        message=(
                            f"File appears in the report more than once "
                            f"(entries {seen_sources[source_key]} and {index})."
                        ),
                        path=str(evaluation.source),
                        entry_index=index,
                    )
                )
                item.skip_reason = SKIP_DUPLICATE_SOURCE
            elif limit is not None and rename_count >= limit:
                item.skip_reason = SKIP_OVER_LIMIT
            else:
                seen_sources[source_key] = index
                rename_count += 1
                item.action = "rename"
                item.target_name = evaluation.target_name
                item.final_path = str(
                    Path(evaluation.source).parent / evaluation.target_name
                )
        plan.items.append(item)

    _check_targets(plan, resolve_conflicts)

    if plan.missing_metadata_count:
        plan.issues.append(
            ValidationIssue(
                severity="warning",
                code="NO_METADATA",
                message=(
                    f"{plan.missing_metadata_count} entr(ies) have no "
                    "source_metadata (old report format); cannot verify the "
                    "files were not modified after the scan."
                ),
            )
        )
    return plan


def _check_targets(plan: RenamePlan, resolve_conflicts: bool) -> None:
    """Detect (or resolve) duplicate and occupied target paths."""
    renames = plan.renames
    source_keys = {_path_key(item.original_path) for item in renames}

    if resolve_conflicts:
        taken: set[str] = set()
        for item in renames:
            candidate = item.target_name
            number = 1
            while _is_conflicting(item, candidate, taken, source_keys):
                number += 1
                candidate = _numbered_name(item.target_name, number)
            if candidate != item.target_name:
                item.conflict_resolved = True
                item.target_name = candidate
                item.final_path = str(Path(item.original_path).parent / candidate)
            taken.add(_path_key(item.final_path))
        return

    seen_targets: dict[str, PlanItem] = {}
    for item in renames:
        target_key = _path_key(item.final_path)
        other = seen_targets.get(target_key)
        if other is not None:
            plan.issues.append(
                ValidationIssue(
                    severity="error",
                    code="DUPLICATE_TARGET",
                    message=(
                        f"{other.original_name} and {item.original_name} "
                        f"target the same name: {item.target_name}"
                    ),
                    path=item.final_path,
                    entry_index=item.entry_index,
                )
            )
        else:
            seen_targets[target_key] = item
        if os.path.lexists(item.final_path) and target_key not in source_keys:
            plan.issues.append(
                ValidationIssue(
                    severity="error",
                    code="TARGET_ALREADY_EXISTS",
                    message=(
                        "Target path is occupied by a file outside the "
                        f"rename plan: {item.final_path}"
                    ),
                    path=item.final_path,
                    entry_index=item.entry_index,
                )
            )


def _is_conflicting(
    item: PlanItem, candidate: str, taken: set[str], source_keys: set[str]
) -> bool:
    candidate_path = Path(item.original_path).parent / candidate
    key = _path_key(candidate_path)
    if key in taken:
        return True
    return os.path.lexists(candidate_path) and key not in source_keys
