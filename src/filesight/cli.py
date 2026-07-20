"""FileSight command-line interface.

Exit codes (documented in README):
  0   success
  1   general error (e.g. report already exists, model failed to load)
  2   invalid CLI arguments / path problems
  3   report validation failed
  4   rename failed, all changes rolled back
  5   partially completed operation or incomplete rollback
  6   undo error
  130 interrupted by user (Ctrl+C)

validate / rename / undo never import PyTorch or load the model.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import typer

from filesight import __version__
from filesight.models import FileEntry, ModelInfo, ValidationIssue

app = typer.Typer(
    add_completion=False,
    help="FileSight: suggest and safely apply readable image file names.",
)

DEFAULT_REPORT_NAME = "filesight-report.json"

EXIT_GENERAL = 1
EXIT_USAGE = 2
EXIT_VALIDATION = 3
EXIT_RENAME_FAILED = 4
EXIT_PARTIAL = 5
EXIT_UNDO = 6
EXIT_INTERRUPTED = 130


@app.callback()
def _root() -> None:
    """FileSight renames files only with explicit --apply and keeps a rollback log."""


def _fail(message: str, exit_code: int = EXIT_GENERAL) -> None:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=exit_code)


def _format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def _print_progress(index: int, total: int, entry: FileEntry) -> None:
    typer.echo(f"[{index}/{total}] {entry.original_name}")
    if entry.status == "success":
        typer.echo(f"       {entry.suggested_name}")
    else:
        error_type = entry.error.type if entry.error else "Error"
        typer.echo(f"       FAILED ({error_type})")
    typer.echo("")


@app.command()
def scan(
    path: Path = typer.Argument(..., help="Folder with images to analyze."),
    recursive: bool = typer.Option(
        False, "--recursive", help="Also scan nested folders."
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        help=f"Path of the JSON report (default: {DEFAULT_REPORT_NAME} inside PATH).",
    ),
    max_files: Optional[int] = typer.Option(
        None, "--max-files", min=1, help="Process at most this many files."
    ),
    language: str = typer.Option(
        "en", "--language", help="Language of suggested names: en or uk."
    ),
    overwrite_report: bool = typer.Option(
        False, "--overwrite-report", help="Allow overwriting an existing report."
    ),
) -> None:
    """Scan a folder, caption every supported image and write a JSON report.

    Original files are never renamed or modified by this command.
    """
    if language not in ("en", "uk"):
        _fail(f"Unsupported language '{language}'. Use 'en' or 'uk'.", EXIT_USAGE)
    if not path.exists():
        _fail(f"Folder does not exist: {path}", EXIT_USAGE)
    if not path.is_dir():
        _fail(f"Not a folder: {path}", EXIT_USAGE)
    path = path.resolve()  # store absolute paths so rename works from anywhere

    report_path = output if output is not None else path / DEFAULT_REPORT_NAME
    if report_path.exists() and not overwrite_report:
        _fail(
            f"Report already exists: {report_path}. "
            "Use --overwrite-report to replace it."
        )

    if language == "uk":
        typer.echo(
            "Note: Ukrainian names are experimental and not implemented yet. "
            "Falling back to English.\n"
        )

    from filesight.scanner import find_images

    try:
        files = find_images(path, recursive=recursive)
    except OSError as exc:
        _fail(f"Cannot read folder {path}: {exc}")

    if max_files is not None:
        files = files[:max_files]

    typer.echo(f"FileSight {__version__}")
    typer.echo(f"Folder: {path}")
    typer.echo(f"Images found: {len(files)}")

    if not files:
        typer.echo("No supported images found (.jpg, .jpeg, .png, .webp).")

    from filesight.captioner import DEFAULT_MODEL, BlipCaptioner

    captioner = BlipCaptioner(DEFAULT_MODEL)
    typer.echo(f"Model: {captioner.model_name}")
    typer.echo(f"Device: {captioner.device.upper()}")
    typer.echo("")

    started = time.perf_counter()
    entries: list[FileEntry] = []
    interrupted = False

    if files:
        try:
            typer.echo("Loading model (first run downloads it, please wait)...")
            captioner.load()
            typer.echo("")
        except KeyboardInterrupt:
            _fail("Interrupted while loading the model.", EXIT_INTERRUPTED)
        except Exception as exc:
            _fail(f"Could not load model '{captioner.model_name}': {exc}")

        from filesight.pipeline import process_files

        try:
            entries = process_files(files, captioner, on_progress=_print_progress)
        except KeyboardInterrupt:
            interrupted = True
            typer.echo("\nInterrupted by user; writing partial report...")

    duration = time.perf_counter() - started

    from filesight.report import build_report, write_report

    report = build_report(
        source_directory=path,
        recursive=recursive,
        model=ModelInfo(
            provider="huggingface", name=captioner.model_name, device=captioner.device
        ),
        entries=entries,
        discovered=len(files),
        duration_seconds=duration,
    )
    try:
        write_report(report, report_path)
    except OSError as exc:
        _fail(f"Cannot write report to {report_path}: {exc}")

    typer.echo("Completed" if not interrupted else "Stopped (partial results)")
    typer.echo("")
    typer.echo(f"Processed: {report.summary.processed}")
    typer.echo(f"Failed: {report.summary.failed}")
    typer.echo(f"Duration: {_format_duration(duration)}")
    typer.echo(f"Report: {report_path}")

    if interrupted:
        raise typer.Exit(code=EXIT_INTERRUPTED)


def _load_plan(
    report_path: Path,
    resolve_conflicts: bool = False,
    limit: Optional[int] = None,
):
    from filesight.rename_plan import build_plan
    from filesight.report import ReportLoadError, load_report_dict

    try:
        report = load_report_dict(report_path)
    except ReportLoadError as exc:
        _fail(str(exc), EXIT_VALIDATION)
    return build_plan(
        report, report_path, resolve_conflicts=resolve_conflicts, limit=limit
    )


def _print_issues(issues: list[ValidationIssue]) -> None:
    for issue in issues:
        label = issue.code
        where = f" (entry {issue.entry_index})" if issue.entry_index is not None else ""
        typer.echo(f"[{label}]{where} {issue.message}")
        if issue.path:
            typer.echo(f"{' ' * (len(label) + 2)} {issue.path}")


@app.command()
def validate(
    report: Path = typer.Argument(..., help="Path to the scan report JSON."),
    strict: bool = typer.Option(
        False, "--strict", help="Treat warnings as errors."
    ),
) -> None:
    """Check that a report can be safely used for renaming. Changes nothing."""
    plan = _load_plan(report)
    errors = plan.errors
    warnings = plan.warnings
    failed = bool(errors) or (strict and bool(warnings))

    if failed:
        typer.echo("Validation failed")
        typer.echo("")
        _print_issues(errors)
        if warnings:
            typer.echo("")
    if warnings:
        for issue in warnings:
            typer.echo(f"[warning] {issue.message}")
        typer.echo("")
    if not failed:
        typer.echo("Report is valid")
        typer.echo("")

    conflict_codes = {"DUPLICATE_TARGET", "TARGET_ALREADY_EXISTS"}
    typer.echo(f"Entries: {plan.entries_total}")
    typer.echo(f"Ready to rename: {len(plan.renames)}")
    typer.echo(f"Skipped: {len(plan.skipped)}")
    typer.echo(f"Conflicts: {sum(1 for e in errors if e.code in conflict_codes)}")
    typer.echo(f"Missing files: {sum(1 for e in errors if e.code == 'SOURCE_MISSING')}")

    if failed:
        raise typer.Exit(code=EXIT_VALIDATION)


def _print_plan(plan) -> None:
    typer.echo("Rename plan")
    typer.echo("")
    total = len(plan.items)
    for position, item in enumerate(plan.items, start=1):
        if item.action == "rename":
            typer.echo(f"[{position}/{total}]")
            typer.echo(f"FROM: {item.original_path}")
            marker = "  (conflict resolved)" if item.conflict_resolved else ""
            typer.echo(f"TO:   {item.final_path}{marker}")
        else:
            typer.echo(f"[{position}/{total}] SKIPPED")
            typer.echo(f"FILE: {item.original_path}")
            typer.echo(f"REASON: {item.skip_reason}")
        typer.echo("")


def _confirm_or_abort(yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        _fail(
            "Confirmation required but input is not interactive. "
            "Pass --yes to confirm automatically.",
            EXIT_USAGE,
        )
    try:
        confirmed = typer.confirm("Continue?", default=False)
    except (typer.Abort, EOFError):
        confirmed = False
    if not confirmed:
        typer.echo("Aborted. No files were changed.")
        raise typer.Exit(code=EXIT_GENERAL)


def _check_dry_apply(dry_run: bool, apply: bool) -> bool:
    """Returns True when this run must actually change files."""
    if dry_run and apply:
        _fail("--dry-run and --apply cannot be used together.", EXIT_USAGE)
    return apply


@app.command()
def rename(
    report: Path = typer.Argument(..., help="Path to the scan report JSON."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview only (this is also the default)."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Actually rename files."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip the interactive confirmation (for scripts)."
    ),
    log: Optional[Path] = typer.Option(
        None, "--log", help="Path of the rollback log (default: next to the report)."
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", min=1, help="Rename at most N eligible files (stable order)."
    ),
    resolve_conflicts: bool = typer.Option(
        False,
        "--resolve-conflicts",
        help="Auto-number conflicting target names instead of failing.",
    ),
) -> None:
    """Rename files according to a report. Dry-run by default; needs --apply."""
    applying = _check_dry_apply(dry_run, apply)
    plan = _load_plan(report, resolve_conflicts=resolve_conflicts, limit=limit)

    if plan.errors:
        typer.echo("Validation failed")
        typer.echo("")
        _print_issues(plan.errors)
        typer.echo("")
        typer.echo("No files were changed.")
        raise typer.Exit(code=EXIT_VALIDATION)
    for issue in plan.warnings:
        typer.echo(f"[warning] {issue.message}")

    _print_plan(plan)
    if not plan.renames:
        typer.echo("Nothing to rename.")
        return

    if not applying:
        typer.echo("No files were changed.")
        typer.echo("Run again with --apply to perform the operation.")
        return

    from filesight.renamer import perform_rename

    typer.echo(f"{len(plan.renames)} file(s) will be renamed.")
    typer.echo("A rollback log will be created.")
    typer.echo("")
    _confirm_or_abort(yes)

    log_obj, log_path, result = perform_rename(plan, log)

    typer.echo("")
    if result.error is None:
        typer.echo("Completed")
        typer.echo(f"Renamed: {log_obj.summary.completed}")
        typer.echo(f"Log: {log_path}")
        typer.echo(f"Undo with: filesight undo \"{log_path}\" --apply")
        return

    typer.echo(f"Operation failed: {result.error}", err=True)
    if result.all_restored:
        typer.echo("All changes were rolled back; files are in their original state.")
    else:
        typer.echo("ROLLBACK INCOMPLETE — some files need manual attention:", err=True)
        for op in log_obj.operations:
            if op.status == "failed":
                typer.echo(f"  {op.original_path}: {op.error}", err=True)
    typer.echo(f"Log: {log_path}")
    if result.interrupted:
        raise typer.Exit(code=EXIT_INTERRUPTED)
    raise typer.Exit(
        code=EXIT_RENAME_FAILED if result.all_restored else EXIT_PARTIAL
    )


@app.command()
def undo(
    log: Path = typer.Argument(..., help="Path to a filesight rename log JSON."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview only (this is also the default)."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Actually restore original names."
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip the interactive confirmation (for scripts)."
    ),
) -> None:
    """Undo a completed rename operation using its log. Dry-run by default."""
    applying = _check_dry_apply(dry_run, apply)

    from filesight.operation_log import LogLoadError, load_log
    from filesight.undo import build_undo_plan, perform_undo

    try:
        log_obj = load_log(log)
    except LogLoadError as exc:
        _fail(str(exc), EXIT_UNDO)

    if log_obj.status == "undone":
        typer.echo("This log was already undone. Nothing to do.")
        return

    plan = build_undo_plan(log_obj)
    if plan.errors:
        typer.echo("Undo is not possible:")
        typer.echo("")
        _print_issues(plan.errors)
        typer.echo("")
        typer.echo("No files were changed.")
        raise typer.Exit(code=EXIT_UNDO)

    typer.echo("Undo plan")
    typer.echo("")
    total = len(plan.ops)
    for position, op in enumerate(plan.ops, start=1):
        typer.echo(f"[{position}/{total}]")
        typer.echo(f"FROM: {op.final_path}")
        typer.echo(f"TO:   {op.original_path}")
        typer.echo("")

    if not applying:
        typer.echo("No files were changed.")
        typer.echo("Run again with --apply to perform the undo.")
        return

    typer.echo(f"{total} file(s) will be restored to their original names.")
    typer.echo("")
    _confirm_or_abort(yes)

    result = perform_undo(log_obj, plan, log)

    typer.echo("")
    if result.error is None:
        typer.echo("Undo completed")
        typer.echo(f"Restored: {log_obj.summary.undone}")
        typer.echo(f"Log updated: {log}")
        return

    typer.echo(f"Undo failed: {result.error}", err=True)
    if result.all_restored and log_obj.status != "partially_undone":
        typer.echo("No lasting changes: files remain under their renamed names.")
        typer.echo(f"Log: {log}")
        raise typer.Exit(
            code=EXIT_INTERRUPTED if result.interrupted else EXIT_UNDO
        )
    typer.echo("UNDO INCOMPLETE — some files need manual attention:", err=True)
    for op in log_obj.operations:
        if op.status == "failed":
            typer.echo(f"  {op.final_path}: {op.error}", err=True)
    typer.echo(f"Log: {log}")
    if result.interrupted:
        raise typer.Exit(code=EXIT_INTERRUPTED)
    raise typer.Exit(code=EXIT_PARTIAL)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        typer.echo("\nInterrupted.", err=True)
        sys.exit(EXIT_INTERRUPTED)


if __name__ == "__main__":
    main()
