"""Undoing a completed rename operation using its log.

Undo is the reverse move (final_path -> original_path) for every
completed operation, executed with the same two-phase algorithm, so
swaps, cycles and case-only renames undo correctly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from filesight.models import ValidationIssue
from filesight.operation_log import (
    RenameOperationItem,
    RenameOperationLog,
    utc_now,
    write_log,
)
from filesight.renamer import ExecutionResult, Move, execute_moves


@dataclass
class UndoPlan:
    ops: list[RenameOperationItem] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def build_undo_plan(log: RenameOperationLog) -> UndoPlan:
    """Check that the log can be undone; never touches any file."""
    plan = UndoPlan()
    eligible = [op for op in log.operations if op.status == "completed"]
    if not eligible:
        plan.issues.append(
            ValidationIssue(
                severity="error",
                code="NOTHING_TO_UNDO",
                message=(
                    f"Log status is '{log.status}' and it contains no "
                    "operations with status 'completed'."
                ),
            )
        )
        return plan

    final_keys = {_key(op.final_path) for op in eligible}
    for index, op in enumerate(eligible):
        if not os.path.lexists(op.final_path):
            plan.issues.append(
                ValidationIssue(
                    severity="error",
                    code="UNDO_FILE_MISSING",
                    message="Renamed file no longer exists.",
                    path=op.final_path,
                    entry_index=index,
                )
            )
            continue
        if op.size_bytes is not None:
            try:
                size = os.path.getsize(op.final_path)
            except OSError:
                size = None
            if size is not None and size != op.size_bytes:
                plan.issues.append(
                    ValidationIssue(
                        severity="error",
                        code="UNDO_FILE_CHANGED",
                        message=(
                            "File size differs from the one recorded during "
                            "rename; it is probably not the same file."
                        ),
                        path=op.final_path,
                        entry_index=index,
                    )
                )
                continue
        original_key = _key(op.original_path)
        if (
            os.path.lexists(op.original_path)
            and original_key not in final_keys
        ):
            plan.issues.append(
                ValidationIssue(
                    severity="error",
                    code="UNDO_TARGET_OCCUPIED",
                    message=(
                        "Original path is occupied by another file: "
                        f"{op.original_path}"
                    ),
                    path=op.original_path,
                    entry_index=index,
                )
            )
            continue
        plan.ops.append(op)
    return plan


def perform_undo(
    log: RenameOperationLog, plan: UndoPlan, log_path: Path
) -> ExecutionResult:
    """Execute the undo and persist progress into the same log file."""
    moves = [
        Move(source=op.final_path, target=op.original_path) for op in plan.ops
    ]
    previous_status = log.status
    log.status = "in_progress"

    def sync() -> None:
        for op, move in zip(plan.ops, moves):
            if move.location == "target":
                op.status = "failed" if move.error else "undone"
            elif move.location == "temp":
                op.status = "failed" if move.error else "in_progress"
            else:  # back at (or never left) its renamed position
                op.status = "failed" if move.error else "completed"
            if move.error:
                op.error = move.error
        log.refresh_summary()
        write_log(log, log_path)

    sync()
    result = execute_moves(moves, on_update=sync)

    undone = sum(1 for move in moves if move.location == "target")
    if result.error is None and undone == len(moves):
        log.status = "undone"
        log.undone_at = utc_now()
    elif undone == 0 and result.all_restored:
        # undo failed but everything is back in its renamed state
        log.status = previous_status
        log.error = result.error
    else:
        log.status = "partially_undone"
        log.undone_at = utc_now()
        log.error = result.error
    sync()
    return result
