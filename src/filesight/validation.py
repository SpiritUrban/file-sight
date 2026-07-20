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
        mtime_ok = mtime is None or stat.st_mtime_ns == mtime
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
