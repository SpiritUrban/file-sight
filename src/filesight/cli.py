"""FileSight command-line interface."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

import typer

from filesight import __version__
from filesight.models import FileEntry, ModelInfo

app = typer.Typer(
    add_completion=False,
    help="FileSight: suggest readable file names for images using a local model.",
)

DEFAULT_REPORT_NAME = "filesight-report.json"


@app.callback()
def _root() -> None:
    """FileSight never renames or modifies your files; it only writes a report."""


def _fail(message: str, exit_code: int = 1) -> None:
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

    Original files are never renamed or modified.
    """
    if language not in ("en", "uk"):
        _fail(f"Unsupported language '{language}'. Use 'en' or 'uk'.", exit_code=2)
    if not path.exists():
        _fail(f"Folder does not exist: {path}", exit_code=2)
    if not path.is_dir():
        _fail(f"Not a folder: {path}", exit_code=2)

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
            _fail("Interrupted while loading the model.", exit_code=130)
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
        raise typer.Exit(code=130)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        typer.echo("\nInterrupted.", err=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
