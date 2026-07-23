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
from filesight.constants import (
    DEFAULT_MAX_VIDEO_DURATION,
    DEFAULT_VIDEO_FRAMES,
    MAX_VIDEO_FRAMES,
    MIN_VIDEO_FRAMES,
)
from filesight.models import (
    FileEntry,
    ModelInfo,
    NamingConfiguration,
    ValidationIssue,
)

app = typer.Typer(
    add_completion=False,
    help="FileSight: suggest and safely apply readable image file names.",
)
config_app = typer.Typer(add_completion=False, help="Work with filesight.toml.")
naming_app = typer.Typer(add_completion=False, help="Preview naming rules.")
category_app = typer.Typer(add_completion=False, help="Inspect categorization.")
report_app = typer.Typer(add_completion=False, help="Work with existing reports.")
app.add_typer(config_app, name="config")
app.add_typer(naming_app, name="naming")
app.add_typer(category_app, name="category")
app.add_typer(report_app, name="report")

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


def _clear_line() -> None:
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


def _frame_progress(label: str, current: int, total: int) -> None:
    if total:
        sys.stdout.write(f"\r      {label} {current}/{total}   ")
        sys.stdout.flush()


def _print_file_start(index: int, total: int, path: Path) -> None:
    typer.echo(f"[{index}/{total}] {path.name}")


def _print_media_result(index: int, total: int, entry: FileEntry) -> None:
    from filesight.models import MEDIA_VIDEO

    if entry.media_type == MEDIA_VIDEO:
        _clear_line()
    if entry.status == "skipped":
        reason = entry.error.message if entry.error else "skipped"
        typer.echo(f"      Skipped: {reason}")
        typer.echo("")
        return
    if entry.status == "failed":
        error_type = entry.error.type if entry.error else "Error"
        typer.echo(f"      FAILED ({error_type})")
        typer.echo("")
        return
    if entry.media_type == MEDIA_VIDEO and entry.video_metadata is not None:
        va = entry.video_analysis
        typer.echo(f"      Duration: {entry.video_metadata.duration_seconds:.1f} s")
        if va is not None:
            typer.echo(f"      Usable frames: {va.usable_frames}/{va.extracted_frames}")
    typer.echo(f"      Caption: {entry.caption}")
    if entry.classification is not None:
        typer.echo(
            f"      Category: {entry.classification.category} "
            f"({entry.classification.confidence:.2f})"
        )
    if entry.features is not None:
        parts = [
            entry.features.subject or "-",
            entry.features.action or "-",
            entry.features.location or "-",
        ]
        typer.echo(f"      Features: {' | '.join(parts)}")
    typer.echo(f"      Suggested: {entry.suggested_name}")
    if entry.media_type == MEDIA_VIDEO:
        typer.echo(f"      Time: {entry.processing_time_ms / 1000:.2f} s")
    typer.echo("")


@app.command()
def scan(
    path: Path = typer.Argument(..., help="Folder with media to analyze."),
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
    include_videos: bool = typer.Option(
        False, "--include-videos", help="Analyze videos in addition to images."
    ),
    images_only: bool = typer.Option(
        False, "--images-only", help="Only images (default behavior, explicit)."
    ),
    videos_only: bool = typer.Option(
        False, "--videos-only", help="Only videos."
    ),
    video_frames: int = typer.Option(
        DEFAULT_VIDEO_FRAMES,
        "--video-frames",
        help=f"Frames sampled per video ({MIN_VIDEO_FRAMES}-{MAX_VIDEO_FRAMES}).",
    ),
    max_video_duration: int = typer.Option(
        DEFAULT_MAX_VIDEO_DURATION,
        "--max-video-duration",
        help="Skip videos longer than this many seconds.",
    ),
    allow_long_videos: bool = typer.Option(
        False, "--allow-long-videos", help="Analyze videos beyond the duration limit."
    ),
    ffmpeg_path: Optional[str] = typer.Option(
        None, "--ffmpeg-path", help="Explicit path to the ffmpeg executable."
    ),
    ffprobe_path: Optional[str] = typer.Option(
        None, "--ffprobe-path", help="Explicit path to the ffprobe executable."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", help="Print extra diagnostics."
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", help="Path to filesight.toml (default: ./filesight.toml)."
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Naming profile to use."
    ),
    template: Optional[str] = typer.Option(
        None, "--template", help="Template override, e.g. \"{date}-{subject}\"."
    ),
    transliterate: Optional[bool] = typer.Option(
        None, "--transliterate/--no-transliterate", help="Latinize Ukrainian output."
    ),
    backend: str = typer.Option(
        "auto",
        "--backend",
        help=(
            "Inference backend: auto, onnx-cuda, onnx-directml, "
            "onnx-cpu, or pytorch-cpu."
        ),
    ),
    allow_fallback: bool = typer.Option(
        True,
        "--allow-fallback/--no-allow-fallback",
        help="If the chosen backend cannot caption, fall back to the next one.",
    ),
) -> None:
    """Scan a folder, caption every supported image (and optionally video).

    Original files are never renamed or modified by this command.
    """
    if language not in ("en", "uk"):
        _fail(f"Unsupported language '{language}'. Use 'en' or 'uk'.", EXIT_USAGE)
    if images_only and videos_only:
        _fail("--images-only and --videos-only cannot be combined.", EXIT_USAGE)
    if images_only and include_videos:
        _fail("--images-only and --include-videos cannot be combined.", EXIT_USAGE)
    if not (MIN_VIDEO_FRAMES <= video_frames <= MAX_VIDEO_FRAMES):
        _fail(
            f"--video-frames must be between {MIN_VIDEO_FRAMES} and "
            f"{MAX_VIDEO_FRAMES}.",
            EXIT_USAGE,
        )
    if not path.exists():
        _fail(f"Folder does not exist: {path}", EXIT_USAGE)
    if not path.is_dir():
        _fail(f"Not a folder: {path}", EXIT_USAGE)
    path = path.resolve()  # store absolute paths so rename works from anywhere

    want_images = not videos_only
    want_videos = include_videos or videos_only

    report_path = output if output is not None else path / DEFAULT_REPORT_NAME
    if report_path.exists() and not overwrite_report:
        _fail(
            f"Report already exists: {report_path}. "
            "Use --overwrite-report to replace it."
        )

    # Resolve the naming configuration before doing any expensive work.
    loaded_config = _load_config_or_fail(config)
    active_profile = _resolve_profile_or_fail(loaded_config, profile)
    active_profile = _apply_cli_overrides(
        active_profile,
        template=template,
        # --language only overrides when the user actually passed it
        language=language if language != "en" else None,
        transliterate=transliterate,
    )
    if active_profile.language == "uk":
        typer.echo(
            "Note: Ukrainian naming uses a built-in dictionary; unknown words "
            "stay in English.\n"
        )

    from filesight.scanner import find_media

    try:
        files = find_media(
            path,
            recursive=recursive,
            include_images=want_images,
            include_videos=want_videos,
        )
    except OSError as exc:
        _fail(f"Cannot read folder {path}: {exc}")

    if max_files is not None:
        files = files[:max_files]

    from filesight.scanner import is_video

    image_count = sum(1 for f in files if not is_video(f))
    video_count = sum(1 for f in files if is_video(f))

    typer.echo(f"FileSight {__version__}")
    typer.echo(f"Folder: {path}")
    typer.echo(f"Images: {'enabled' if want_images else 'disabled'}")
    typer.echo(f"Videos: {'enabled' if want_videos else 'disabled'}")
    if want_videos:
        typer.echo(f"Maximum video duration: {max_video_duration} seconds")
        typer.echo(f"Frames per video: {video_frames}")
    typer.echo(f"Images found: {image_count}")
    if want_videos:
        typer.echo(f"Videos found: {video_count}")
    typer.echo(f"Profile: {active_profile.name} ({loaded_config.source})")
    typer.echo(f"Template: {active_profile.template}")
    typer.echo(f"Language: {active_profile.language}")

    # Resolve FFmpeg only when videos are actually in play.
    video_context = None
    workspace = None
    if want_videos and video_count > 0:
        from filesight.video_probe import FFmpegNotFound, resolve_tools

        try:
            tools = resolve_tools(ffmpeg_path, ffprobe_path)
        except FFmpegNotFound as exc:
            _fail(str(exc), EXIT_USAGE)
        if verbose:
            typer.echo(f"ffmpeg: {tools.ffmpeg}")
            typer.echo(f"ffprobe: {tools.ffprobe}")

    from filesight.inference import resolve_backend
    from filesight.inference.base import BackendError
    from filesight.inference.captioner_adapter import BackendCaptioner
    from filesight.models import InferenceInfo

    try:
        selection = resolve_backend(
            requested=backend, allow_fallback=allow_fallback
        )
    except BackendError as exc:
        _fail(str(exc), EXIT_USAGE)

    captioner = BackendCaptioner(selection)
    typer.echo(f"Backend: {selection.actual_backend}")
    if selection.fallback_occurred:
        typer.echo(f"Fallback: {selection.fallback_reason}")
    typer.echo(f"Model: {captioner.model_name}")
    typer.echo(f"Device: {captioner.device}")
    if selection.device_name:
        typer.echo(f"Adapter: {selection.device_name}")
    typer.echo("")

    started = time.perf_counter()
    entries: list[FileEntry] = []
    interrupted = False

    if files:
        try:
            typer.echo("Loading model (first run may download or open ONNX weights)...")
            captioner.load()
            typer.echo("")
        except KeyboardInterrupt:
            _fail("Interrupted while loading the model.", EXIT_INTERRUPTED)
        except Exception as exc:
            _fail(f"Could not load backend '{selection.actual_backend}': {exc}")

        from filesight.pipeline import VideoContext, process_media_files
        from filesight.temp_files import FrameWorkspace

        if want_videos and video_count > 0:
            workspace = FrameWorkspace()
            video_context = VideoContext(
                ffmpeg=tools.ffmpeg,
                ffprobe=tools.ffprobe,
                workspace=workspace,
                max_duration=max_video_duration,
                allow_long=allow_long_videos,
                num_frames=video_frames,
            )
        from filesight.naming_preview import NamingSession

        naming_session = NamingSession(
            active_profile,
            category_rules=loaded_config.category_rules,
            template=template,
        )
        try:
            entries = process_media_files(
                files,
                captioner,
                video_context=video_context,
                on_file_progress=_print_media_result,
                on_frame_progress=_frame_progress,
                on_file_start=_print_file_start,
                naming_session=naming_session,
            )
        except KeyboardInterrupt:
            interrupted = True
            _clear_line()
            typer.echo("\nInterrupted by user; cleaning up and writing partial report...")
        finally:
            if workspace is not None:
                workspace.cleanup()

    duration = time.perf_counter() - started

    from filesight.report import build_report, write_report

    inference = InferenceInfo(
        requested_backend=selection.requested_backend,
        actual_backend=selection.actual_backend,
        runtime=selection.runtime,
        runtime_version=selection.runtime_version,
        execution_provider=selection.execution_provider,
        device_name=selection.device_name,
        model_id=selection.model_id,
        fallback_occurred=selection.fallback_occurred,
        fallback_reason=selection.fallback_reason,
        directml_available=selection.directml_available,
        cuda_available=selection.cuda_available,
    )
    report = build_report(
        source_directory=path,
        recursive=recursive,
        model=ModelInfo(
            provider=selection.runtime,
            name=captioner.model_name,
            device=captioner.device,
        ),
        entries=entries,
        discovered=len(files),
        duration_seconds=duration,
        videos_enabled=want_videos,
        naming_configuration=NamingConfiguration(
            source=loaded_config.source,
            profile=active_profile.name,
            template=template or active_profile.template,
            language=active_profile.language,
            transliterate=active_profile.transliterate,
            config_version=loaded_config.config_version,
        ),
        inference=inference,
    )
    try:
        write_report(report, report_path)
    except OSError as exc:
        _fail(f"Cannot write report to {report_path}: {exc}")

    typer.echo("Completed" if not interrupted else "Stopped (partial results)")
    typer.echo("")
    if want_videos and report.summary.videos is not None:
        typer.echo(f"Images processed: {report.summary.images.processed}")
        typer.echo(f"Videos processed: {report.summary.videos.processed}")
        typer.echo(f"Videos skipped: {report.summary.videos.skipped}")
    else:
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
        typer.echo("ROLLBACK INCOMPLETE вЂ” some files need manual attention:", err=True)
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
    typer.echo("UNDO INCOMPLETE вЂ” some files need manual attention:", err=True)
    for op in log_obj.operations:
        if op.status == "failed":
            typer.echo(f"  {op.final_path}: {op.error}", err=True)
    typer.echo(f"Log: {log}")
    if result.interrupted:
        raise typer.Exit(code=EXIT_INTERRUPTED)
    raise typer.Exit(code=EXIT_PARTIAL)


# --------------------------------------------------------------------------
# Configuration / naming commands. None of these import PyTorch or FFmpeg.
# --------------------------------------------------------------------------


def _load_config_or_fail(config_path: Optional[Path], strict: bool = False):
    from filesight.config import ConfigError, find_config_file, load_config

    try:
        return load_config(find_config_file(config_path), strict=strict)
    except ConfigError as exc:
        _fail(str(exc), EXIT_VALIDATION)


def _resolve_profile_or_fail(config, profile_name: Optional[str]):
    from filesight.config import ConfigError

    try:
        return config.resolve_profile(profile_name)
    except ConfigError as exc:
        _fail(str(exc), EXIT_USAGE)


def _apply_cli_overrides(
    profile,
    template: Optional[str] = None,
    language: Optional[str] = None,
    transliterate: Optional[bool] = None,
):
    """CLI flags beat config values; config beats built-in defaults."""
    from filesight.localization import SUPPORTED_LANGUAGES
    from filesight.templates import unknown_variables

    if template is not None:
        unknown = unknown_variables(template)
        if unknown:
            _fail(
                "Unknown template variable(s): " + ", ".join(sorted(set(unknown))),
                EXIT_USAGE,
            )
        profile.template = template
    if language is not None:
        if language not in SUPPORTED_LANGUAGES:
            _fail(
                f"Unsupported language '{language}'. Use "
                + " or ".join(SUPPORTED_LANGUAGES),
                EXIT_USAGE,
            )
        profile.language = language
    if transliterate is not None:
        profile.transliterate = transliterate
    return profile


@config_app.command("init")
def config_init(
    output: Optional[Path] = typer.Option(
        None, "--output", help="Where to write the file (default: ./filesight.toml)."
    ),
    profile: str = typer.Option(
        "photos", "--profile", help="Profile to make the default in the new file."
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing file."
    ),
) -> None:
    """Write a commented example configuration."""
    from filesight.config import CONFIG_FILE_NAME
    from filesight.config_template import render_example_config
    from filesight.profiles import BUILT_IN_PROFILES

    if profile not in BUILT_IN_PROFILES:
        _fail(
            f"Unknown profile '{profile}'. Built-ins: "
            + ", ".join(sorted(BUILT_IN_PROFILES)),
            EXIT_USAGE,
        )
    target = output if output is not None else Path.cwd() / CONFIG_FILE_NAME
    if target.exists() and not force:
        _fail(
            f"File already exists: {target}. Use --force to overwrite.", EXIT_GENERAL
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_example_config(profile), encoding="utf-8")
    except OSError as exc:
        _fail(f"Cannot write {target}: {exc}")
    typer.echo(f"Created {target}")
    typer.echo(f"Default profile: {profile}")
    typer.echo(f"Validate it with: filesight config validate \"{target}\"")


@config_app.command("validate")
def config_validate(
    config: Path = typer.Argument(..., help="Path to a filesight.toml."),
    strict: bool = typer.Option(
        False, "--strict", help="Treat warnings as errors."
    ),
) -> None:
    """Check a configuration file for errors and unknown keys."""
    from filesight.config import ConfigError, load_config

    try:
        loaded = load_config(config, strict=strict)
    except ConfigError as exc:
        typer.echo("Configuration is invalid", err=True)
        typer.echo("")
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=EXIT_VALIDATION)

    typer.echo("Configuration is valid")
    typer.echo("")
    typer.echo(f"Source: {loaded.source}")
    typer.echo(f"Config version: {loaded.config_version}")
    typer.echo(f"Default profile: {loaded.default_profile}")
    typer.echo(f"Profiles: {', '.join(loaded.profile_names())}")
    typer.echo(f"Categories: {sum(1 for r in loaded.category_rules if r.enabled)} enabled")
    for issue in loaded.warnings:
        typer.echo(f"[warning] {issue.message}")


@config_app.command("show")
def config_show(
    config: Optional[Path] = typer.Argument(
        None, help="Path to a filesight.toml (default: ./filesight.toml)."
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile to show."),
) -> None:
    """Show the effective profile after defaults, config and profile merge."""
    from dataclasses import asdict

    loaded = _load_config_or_fail(config)
    active = _resolve_profile_or_fail(loaded, profile)

    typer.echo(f"Source: {loaded.source}")
    typer.echo(f"Config version: {loaded.config_version or '(built-in)'}")
    typer.echo(f"Available profiles: {', '.join(loaded.profile_names())}")
    typer.echo("")
    typer.echo(f"Effective profile: {active.name}")
    for key, value in asdict(active).items():
        if key == "name":
            continue
        typer.echo(f"  {key} = {value!r}")
    typer.echo("")
    enabled = [r for r in loaded.category_rules if r.enabled]
    typer.echo(f"Enabled categories ({len(enabled)}):")
    typer.echo("  " + ", ".join(r.name for r in enabled))


@naming_app.command("preview")
def naming_preview_command(
    caption: str = typer.Option(..., "--caption", help="Caption text to name from."),
    config: Optional[Path] = typer.Option(None, "--config", help="Config file."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name."),
    template: Optional[str] = typer.Option(None, "--template", help="Template override."),
    language: Optional[str] = typer.Option(None, "--language", help="en or uk."),
    transliterate: Optional[bool] = typer.Option(
        None, "--transliterate/--no-transliterate", help="Latinize Ukrainian output."
    ),
    extension: str = typer.Option(".jpg", "--extension", help="File extension."),
    media_type: str = typer.Option("image", "--media-type", help="image or video."),
    original_name: Optional[str] = typer.Option(
        None, "--original-name", help="Original file name (affects rules and stem)."
    ),
    date: Optional[str] = typer.Option(
        None, "--date", help="Capture date, e.g. 2026-01-14 or an ISO timestamp."
    ),
    index: int = typer.Option(1, "--index", help="Value for {index}."),
) -> None:
    """Show how a caption becomes a file name. Never loads the vision model."""
    from filesight.naming_preview import build_naming

    if media_type not in ("image", "video"):
        _fail("--media-type must be 'image' or 'video'.", EXIT_USAGE)
    loaded = _load_config_or_fail(config)
    active = _resolve_profile_or_fail(loaded, profile)
    active = _apply_cli_overrides(active, template, language, transliterate)

    ext = extension if extension.startswith(".") else f".{extension}"
    name = original_name or f"example{ext}"
    captured_at = None
    if date:
        captured_at = date if "T" in date else f"{date}T12:00:00"

    outcome = build_naming(
        caption,
        name,
        active,
        media_type=media_type,
        extension=ext,
        captured_at=captured_at,
        index=index,
        category_rules=loaded.category_rules,
    )
    features = outcome.features
    typer.echo(f"Caption: {caption}")
    typer.echo(f"Category: {outcome.classification.category}")
    if active.language != "en":
        typer.echo(f"Category label: {outcome.classification.category_label}")
    typer.echo(f"Subject: {features.subject or '(none)'}")
    typer.echo(f"Action: {features.action or '(none)'}")
    typer.echo(f"Location: {features.location or '(none)'}")
    typer.echo(f"Objects: {', '.join(features.objects) or '(none)'}")
    typer.echo(f"Profile: {active.name}")
    typer.echo(f"Template: {outcome.naming.template}")
    typer.echo("")
    typer.echo("Result:")
    typer.echo(outcome.naming.suggested_name)
    for warning in outcome.naming.warnings:
        typer.echo(f"[warning] {warning}")


@category_app.command("explain")
def category_explain(
    caption: str = typer.Option(..., "--caption", help="Caption text to classify."),
    config: Optional[Path] = typer.Option(None, "--config", help="Config file."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name."),
    original_name: str = typer.Option(
        "", "--original-name", help="Original file name (filename rules)."
    ),
    media_type: str = typer.Option("image", "--media-type", help="image or video."),
) -> None:
    """Show which category rules matched and why one won. No model loaded."""
    from filesight.categories import MediaCategorizer

    if media_type not in ("image", "video"):
        _fail("--media-type must be 'image' or 'video'.", EXIT_USAGE)
    loaded = _load_config_or_fail(config)
    active = _resolve_profile_or_fail(loaded, profile)

    categorizer = MediaCategorizer(loaded.category_rules)
    matches = categorizer.evaluate(
        caption, original_name=original_name, media_type=media_type
    )
    result = categorizer.classify(
        caption,
        original_name=original_name,
        media_type=media_type,
        language=active.language,
    )

    typer.echo(f"Selected category: {result.category}")
    typer.echo(f"Confidence score: {result.confidence:.2f} (rule-based)")
    typer.echo("")
    if not matches:
        typer.echo("Matched: nothing — falling back to 'other'.")
        return

    typer.echo("Matched:")
    for match in sorted(
        matches, key=lambda m: (-m.score, -m.rule.priority, m.rule.order)
    ):
        typer.echo(f"  {match.rule.name} (priority {match.rule.priority}):")
        for item in match.matched:
            typer.echo(f"    {item}")
    typer.echo("")
    typer.echo(f"Winner:\n  {result.category}")
    typer.echo("")
    typer.echo("Reason:")
    best = max(matches, key=lambda m: (m.score, m.rule.priority, -m.rule.order))
    rivals = [m for m in matches if m.score == best.score and m is not best]
    if rivals:
        typer.echo(
            f"  {len(rivals) + 1} categories matched {best.score} rule(s); "
            f"'{best.rule.name}' has the highest priority "
            f"({best.rule.priority})."
        )
    else:
        typer.echo(
            f"  '{best.rule.name}' matched the most rules ({best.score})."
        )


@report_app.command("rename-suggestions")
def report_rename_suggestions(
    report: Path = typer.Argument(..., help="Existing scan report JSON."),
    config: Optional[Path] = typer.Option(None, "--config", help="Config file."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name."),
    template: Optional[str] = typer.Option(None, "--template", help="Template override."),
    language: Optional[str] = typer.Option(None, "--language", help="en or uk."),
    transliterate: Optional[bool] = typer.Option(
        None, "--transliterate/--no-transliterate", help="Latinize Ukrainian output."
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", help="Where to write the new report."
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Allow overwriting the output report."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Only show what would change."
    ),
) -> None:
    """Regenerate suggested names from a report's captions. No model loaded."""
    from filesight.report import ReportLoadError, load_report_dict
    from filesight.report_transform import regenerate_suggestions, write_report_dict

    try:
        data = load_report_dict(report)
    except ReportLoadError as exc:
        _fail(str(exc), EXIT_VALIDATION)

    loaded = _load_config_or_fail(config)
    active = _resolve_profile_or_fail(loaded, profile)
    active = _apply_cli_overrides(active, template, language, transliterate)

    updated, changes = regenerate_suggestions(
        data, active, config=loaded, template=template
    )

    changed = [c for c in changes if c.changed]
    for change in changes:
        if change.skipped_reason:
            continue
        typer.echo(change.original_name)
        typer.echo(f"OLD: {change.old_name}")
        typer.echo(f"NEW: {change.new_name}")
        typer.echo("")

    typer.echo(f"Entries: {len(changes)}")
    typer.echo(f"Changed: {len(changed)}")
    typer.echo(f"Skipped: {sum(1 for c in changes if c.skipped_reason)}")

    if dry_run:
        typer.echo("")
        typer.echo("Dry run: no report was written.")
        return

    target = output if output is not None else report
    if target.exists() and not overwrite:
        if target == report:
            _fail(
                "Refusing to overwrite the source report. Pass --output PATH "
                "or --overwrite.",
                EXIT_GENERAL,
            )
        _fail(f"Output already exists: {target}. Use --overwrite.", EXIT_GENERAL)
    try:
        write_report_dict(updated, target)
    except OSError as exc:
        _fail(f"Cannot write {target}: {exc}")
    typer.echo("")
    typer.echo(f"Report written: {target}")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        typer.echo("\nInterrupted.", err=True)
        sys.exit(EXIT_INTERRUPTED)


if __name__ == "__main__":
    main()
