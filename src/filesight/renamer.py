"""Two-phase rename execution with controlled rollback.

Phase 1 moves every file to a unique temporary name in the same folder;
phase 2 moves temporaries to final names. This supports swaps, cycles
and case-only renames on Windows. os.rename (never os.replace onto an
occupied target) is used, so a foreign file can never be overwritten.

On any error the executor tries to return every touched file to its
original name, again in two phases so rollback itself cannot deadlock
on cycles. Files it could not restore are reported honestly.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from filesight.operation_log import (
    LOG_SCHEMA_VERSION,
    LogSummary,
    RenameOperationItem,
    RenameOperationLog,
    default_log_path,
    utc_now,
    write_log,
)
from filesight.rename_plan import RenamePlan


@dataclass
class Move:
    """One file movement tracked by its current physical location."""

    source: str
    target: str
    temp: Optional[str] = None
    location: str = "source"  # "source" | "temp" | "target"
    moved: bool = False  # ever left its source position
    error: Optional[str] = None


@dataclass
class ExecutionResult:
    error: Optional[str]
    interrupted: bool
    all_restored: bool  # meaningful only when error is not None


def _make_temp_path(near: str) -> str:
    directory = os.path.dirname(near) or "."
    ext = os.path.splitext(near)[1]
    while True:
        candidate = os.path.join(
            directory, f".filesight-tmp-{uuid.uuid4().hex}{ext}"
        )
        if not os.path.lexists(candidate):
            return candidate


def execute_moves(
    moves: list[Move], on_update: Optional[Callable[[], None]] = None
) -> ExecutionResult:
    """Run all moves in two phases; roll back everything on any error."""

    def update() -> None:
        if on_update is not None:
            on_update()

    error: Optional[str] = None
    interrupted = False
    current: Optional[Move] = None
    try:
        for move in moves:  # phase 1: source -> temp
            current = move
            move.temp = _make_temp_path(move.source)
            os.rename(move.source, move.temp)
            move.location = "temp"
            move.moved = True
            update()
        for move in moves:  # phase 2: temp -> final
            current = move
            os.rename(move.temp, move.target)
            move.location = "target"
            update()
        return ExecutionResult(error=None, interrupted=False, all_restored=True)
    except KeyboardInterrupt:
        interrupted = True
        error = "Interrupted by user (Ctrl+C)"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    if current is not None and current.location != "target":
        current.error = error
    update()
    try:
        _rollback(moves, update)
    except BaseException as exc:  # never abandon without recording state
        for move in moves:
            if move.location != "source" and move.error is None:
                move.error = f"rollback aborted ({exc}); see current location"
    update()
    all_restored = all(m.location == "source" or not m.moved for m in moves)
    return ExecutionResult(error=error, interrupted=interrupted, all_restored=all_restored)


def _rollback(moves: list[Move], update: Callable[[], None]) -> None:
    """Return touched files to their sources using the same two phases."""
    for move in moves:  # phase A: free all final positions first
        if move.location == "target":
            try:
                temp = _make_temp_path(move.target)
                os.rename(move.target, temp)
                move.temp = temp
                move.location = "temp"
            except Exception as exc:
                move.error = (
                    f"rollback failed: file remains at {move.target} ({exc})"
                )
            update()
    for move in moves:  # phase B: temp -> original source
        if move.location == "temp":
            try:
                os.rename(move.temp, move.source)
                move.location = "source"
            except Exception as exc:
                move.error = (
                    f"rollback failed: file remains at {move.temp} ({exc})"
                )
            update()


def _op_status(move: Move) -> str:
    if move.location == "target":
        return "failed" if move.error else "completed"
    if move.location == "temp":
        return "failed" if move.error else "in_progress"
    # location == "source"
    if move.moved:
        return "rolled_back"
    return "failed" if move.error else "planned"


def prepare_log(plan: RenamePlan, log_path: Optional[Path]) -> tuple[
    RenameOperationLog, Path, list[Move]
]:
    """Build the log and moves for a plan without touching any file."""
    operations = []
    moves = []
    for item in plan.renames:
        size: Optional[int] = None
        try:
            size = os.path.getsize(item.original_path)
        except OSError:
            pass
        operations.append(
            RenameOperationItem(
                original_path=item.original_path,
                final_path=item.final_path,
                size_bytes=size,
            )
        )
        moves.append(Move(source=item.original_path, target=item.final_path))
    log = RenameOperationLog(
        schema_version=LOG_SCHEMA_VERSION,
        operation_id=str(uuid.uuid4()),
        created_at=utc_now(),
        report_path=plan.report_path,
        status="in_progress",
        summary=LogSummary(planned=len(operations)),
        operations=operations,
    )
    resolved_path = log_path or default_log_path(Path(plan.report_path))
    return log, resolved_path, moves


def perform_rename(
    plan: RenamePlan, log_path: Optional[Path] = None
) -> tuple[RenameOperationLog, Path, ExecutionResult]:
    """Execute the plan. The log is written before, during and after."""
    log, resolved_log_path, moves = prepare_log(plan, log_path)

    def sync() -> None:
        for op, move in zip(log.operations, moves):
            op.temporary_path = move.temp
            op.status = _op_status(move)
            op.error = move.error
        log.refresh_summary()
        write_log(log, resolved_log_path)

    write_log(log, resolved_log_path)  # the log exists before any change
    result = execute_moves(moves, on_update=sync)

    if result.error is None:
        log.status = "completed"
    elif result.all_restored:
        log.status = "rolled_back"
    else:
        log.status = "partially_rolled_back"
    log.error = result.error
    log.completed_at = utc_now()
    sync()
    return log, resolved_log_path, result
