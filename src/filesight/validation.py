"""Per-entry safety checks for report entries before renaming.

Pure logic over the raw report dict; never loads the neural network.
Cross-entry checks (duplicate targets, occupied targets) live in
rename_plan.py because they depend on the final plan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from filesight.models import ValidationIssue

FORBIDDEN_CHARS = '<>:"/\\|?*'
RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
MAX_FULL_PATH = 259  # classic Windows MAX_PATH minus the terminator

# Reports travel through JSON, and in the desktop UI that means JavaScript,
# where every number is an IEEE double. A nanosecond timestamp (~1.8e18)
# is far past the 2^53 exact-integer range, so it comes back rounded by up
# to a few hundred nanoseconds — enough to look like a modified file.
# Compare with a tolerance that is orders of magnitude below any real edit;
# size is still compared exactly.
MTIME_TOLERANCE_NS = 10_000  # 10 microseconds

SKIP_NOT_SUCCESS = "report status is {status}"
SKIP_DISABLED = "rename_enabled is false in report"
SKIP_UNCHANGED = "name unchanged"
SKIP_OVER_LIMIT = "beyond --limit"
SKIP_INVALID = "entry failed validation"
SKIP_DUPLICATE_SOURCE = "duplicate entry for the same file"


@dataclass
class EntryEvaluation:
    """Outcome of validating a single report entry."""

    entry_index: int
    original_name: str = ""
    source: Optional[Path] = None
    target_name: Optional[str] = None
    skip_reason: Optional[str] = None
    issues: list[ValidationIssue] = field(default_factory=list)
    missing_metadata: bool = False

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


def _mtime_matches(actual_ns: int, recorded: object) -> bool:
    """Compare modification times, tolerating JSON double rounding.

    See MTIME_TOLERANCE_NS: a report that passed through a JavaScript UI
    carries a slightly rounded timestamp even though the file is untouched.
    """
    try:
        recorded_ns = int(recorded)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return abs(actual_ns - recorded_ns) <= MTIME_TOLERANCE_NS


def _error(code: str, message: str, path: Optional[str], index: int) -> ValidationIssue:
    return ValidationIssue(
        severity="error", code=code, message=message, path=path, entry_index=index
    )


def check_suggested_name(name: str) -> list[tuple[str, str]]:
    """Return (code, message) problems for a suggested file name."""
    problems: list[tuple[str, str]] = []
    if "/" in name or "\\" in name or name in (".", ".."):
        problems.append(
            (
                "NAME_IS_PATH",
                "Suggested name must be a plain file name, not a path "
                f"(got: {name!r}). Moving between folders is not supported.",
            )
        )
        return problems
    forbidden = sorted({c for c in name if c in FORBIDDEN_CHARS})
    if forbidden:
        chars = " ".join(forbidden)
        problems.append(
            (
                "INVALID_NAME",
                f"Suggested name contains forbidden characters ({chars}): {name}",
            )
        )
    if not name.strip(" ."):
        problems.append(
            ("INVALID_NAME", "Suggested name consists only of spaces/dots.")
        )
    elif name != name.rstrip(" ."):
        problems.append(
            ("INVALID_NAME", f"Suggested name ends with a space or dot: {name!r}")
        )
    base = name.split(".")[0].strip().upper()
    if base in RESERVED_NAMES:
        problems.append(
            ("RESERVED_NAME", f"Suggested name is a reserved Windows name: {name}")
        )
    return problems


def _check_naming_sections(entry: dict) -> list[tuple[str, str]]:
    """Structural checks for the optional features/classification/naming.

    Missing sections are fine (older reports); malformed ones are not.
    """
    problems: list[tuple[str, str]] = []

    features = entry.get("features")
    if features is not None:
        if not isinstance(features, dict):
            problems.append(("INVALID_FEATURES", "'features' must be an object."))
        else:
            for key in ("subject", "action", "location", "text"):
                value = features.get(key)
                if value is not None and not isinstance(value, str):
                    problems.append(
                        ("INVALID_FEATURES", f"features.{key} must be a string or null.")
                    )
            objects = features.get("objects")
            if objects is not None and (
                not isinstance(objects, list)
                or not all(isinstance(o, str) for o in objects)
            ):
                problems.append(
                    ("INVALID_FEATURES", "features.objects must be a list of strings.")
                )

    classification = entry.get("classification")
    if classification is not None:
        if not isinstance(classification, dict):
            problems.append(
                ("INVALID_CLASSIFICATION", "'classification' must be an object.")
            )
        else:
            category = classification.get("category")
            if not isinstance(category, str) or not category.strip():
                problems.append(
                    ("INVALID_CLASSIFICATION", "classification.category must be a name.")
                )
            confidence = classification.get("confidence")
            if confidence is not None and (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0.0 <= float(confidence) <= 1.0
            ):
                problems.append(
                    (
                        "INVALID_CLASSIFICATION",
                        "classification.confidence must be a number in 0..1.",
                    )
                )

    naming = entry.get("naming")
    if naming is not None:
        if not isinstance(naming, dict):
            problems.append(("INVALID_NAMING", "'naming' must be an object."))
        else:
            base = naming.get("base_name")
            if base is not None and not isinstance(base, str):
                problems.append(("INVALID_NAMING", "naming.base_name must be a string."))
            elif isinstance(base, str) and ("/" in base or "\\" in base):
                problems.append(
                    ("INVALID_NAMING", f"naming.base_name must not contain a path: {base}")
                )
            inner = naming.get("suggested_name")
            outer = entry.get("suggested_name")
    return problems


def _naming_warnings(entry: dict) -> list[tuple[str, str]]:
    """Non-fatal observations about the naming section."""
    naming = entry.get("naming")
    if not isinstance(naming, dict):
        return []
    inner = naming.get("suggested_name")
    outer = entry.get("suggested_name")
    if isinstance(inner, str) and isinstance(outer, str) and inner != outer:
        # Editing the top-level name by hand is a supported workflow, so
        # this is informational only: rename always uses the top-level one.
        return [
            (
                "NAMING_EDITED",
                "Top-level suggested_name differs from naming.suggested_name "
                f"({outer!r} vs {inner!r}); rename will use the top-level value.",
            )
        ]
    return []


def evaluate_entry(index: int, entry: dict) -> EntryEvaluation:
    """Validate one report entry and compute its effective target name.

    The target keeps the *actual* original extension (original case), even
    if the user typed the extension in a different case in suggested_name.
    """
    result = EntryEvaluation(entry_index=index)

    original_path = entry.get("original_path")
    original_name = entry.get("original_name")
    for field_name, value in (
        ("original_path", original_path),
        ("original_name", original_name),
    ):
        if not isinstance(value, str) or not value.strip():
            result.issues.append(
                _error(
                    "MISSING_FIELD",
                    f"Entry has empty or missing '{field_name}'.",
                    None,
                    index,
                )
            )
    if result.has_errors:
        return result
    result.original_name = original_name

    # media_type is optional; missing means image (backward compatible).
    media_type = entry.get("media_type", "image")
    if media_type not in ("image", "video"):
        result.issues.append(
            _error(
                "UNSUPPORTED_MEDIA_TYPE",
                f"Unsupported media_type: {media_type!r}.",
                original_path,
                index,
            )
        )
        return result

    # Iteration-4 sections are optional; when present they must be sane.
    # Their absence never invalidates an older report.
    for code, message in _check_naming_sections(entry):
        result.issues.append(_error(code, message, original_path, index))
    for code, message in _naming_warnings(entry):
        result.issues.append(
            ValidationIssue("warning", code, message, original_path, index)
        )
    if result.has_errors:
        return result

    status = entry.get("status")
    if status != "success":
        result.skip_reason = SKIP_NOT_SUCCESS.format(status=status)
        return result

    if entry.get("rename_enabled", True) is False:
        result.skip_reason = SKIP_DISABLED
        return result

    suggested = entry.get("suggested_name")
    if not isinstance(suggested, str) or not suggested.strip():
        result.issues.append(
            _error(
                "MISSING_SUGGESTED_NAME",
                "Entry with status 'success' has no suggested_name.",
                original_path,
                index,
            )
        )
        return result

    for code, message in check_suggested_name(suggested):
        result.issues.append(_error(code, message, original_path, index))
    if result.has_errors:
        return result

    original_ext = os.path.splitext(original_name)[1]
    suggested_stem, suggested_ext = os.path.splitext(suggested)
    if suggested_ext.lower() != original_ext.lower():
        result.issues.append(
            _error(
                "EXTENSION_CHANGED",
                f"Changing the extension is not allowed: {original_name} -> "
                f"{suggested} ({original_ext or 'no extension'} vs "
                f"{suggested_ext or 'no extension'}).",
                original_path,
                index,
            )
        )
        return result
    target_name = suggested_stem + original_ext

    if target_name == original_name:
        result.skip_reason = SKIP_UNCHANGED
        return result

    source = Path(original_path)
    result.source = source
    if not source.exists():
        result.issues.append(
            _error("SOURCE_MISSING", "Source file does not exist.", str(source), index)
        )
        return result
    if not source.is_file():
        result.issues.append(
            _error(
                "SOURCE_NOT_A_FILE",
                "Source path exists but is not a regular file.",
                str(source),
                index,
            )
        )
        return result

    metadata = entry.get("source_metadata")
    if isinstance(metadata, dict) and "size_bytes" in metadata:
        stat = source.stat()
        size_ok = stat.st_size == metadata.get("size_bytes")
        mtime = metadata.get("modified_at_ns")
        mtime_ok = mtime is None or _mtime_matches(stat.st_mtime_ns, mtime)
        if not (size_ok and mtime_ok):
            result.issues.append(
                _error(
                    "SOURCE_MODIFIED",
                    "File was modified or replaced after the scan "
                    "(size or mtime differs). Re-run 'filesight scan'.",
                    str(source),
                    index,
                )
            )
            return result
    else:
        result.missing_metadata = True

    final_path = source.parent / target_name
    if len(str(final_path)) > MAX_FULL_PATH:
        result.issues.append(
            _error(
                "PATH_TOO_LONG",
                f"Target path exceeds {MAX_FULL_PATH} characters: {final_path}",
                str(final_path),
                index,
            )
        )
        return result

    result.target_name = target_name
    return result
