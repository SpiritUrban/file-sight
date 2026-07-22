"""JSON Lines worker process for the FileSight desktop app.

Protocol
--------
One JSON object per line, both directions.

Request  (stdin) : {"request_id": "...", "command": "scan", "payload": {...}}
Response (stdout): {"request_id": "...", "event": "progress", "data": {...}}

stdout carries **only** protocol JSON. All human/diagnostic output goes to
stderr, so the GUI never has to parse decorative text.

Threading model
---------------
stdin is read on a helper thread; every real command runs on the **main**
thread. That direction matters: importing C extensions (numpy, torch)
from a non-main thread deadlocks when the process was spawned with piped
stdio, which is exactly how the desktop app launches this worker.

`cancel` and `shutdown` are answered inline on the reader thread — they
only touch a threading.Event, so they stay responsive while a scan runs.

Run with:  python -m filesight.worker
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Optional

from filesight import __version__

# Commands that must never import torch / load the model.
LIGHT_COMMANDS = {
    "ping", "shutdown", "cancel", "get_profiles", "get_config",
    "get_environment", "load_report", "save_report", "validate_report",
    "build_rename_plan", "apply_rename", "undo", "regenerate_names",
    "make_thumbnail",
}


class WorkerError(Exception):
    """An error with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        recoverable: bool = True,
        details: Optional[list] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        # Concrete, per-file reasons the UI can list. A bare code tells the
        # user something failed but not what to fix.
        self.details = details or []


class Emitter:
    """Thread-safe JSON Lines writer for stdout."""

    def __init__(self, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._lock = threading.Lock()

    def emit(self, request_id: str, event: str, data: Optional[dict] = None) -> None:
        line = json.dumps(
            {"request_id": request_id, "event": event, "data": data or {}},
            ensure_ascii=False,
            default=str,
        )
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()


def log(message: str) -> None:
    """Diagnostics go to stderr so stdout stays pure protocol."""
    print(f"[filesight.worker] {message}", file=sys.stderr, flush=True)


class Worker:
    """Dispatches commands and owns the shared, lazily-loaded captioner."""

    def __init__(self, emitter: Optional[Emitter] = None) -> None:
        self.emitter = emitter or Emitter()
        self._captioner = None
        self._model_loaded = False
        self._onnx_warmed = False
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._pending: "queue.Queue" = queue.Queue()
        self.should_stop = threading.Event()

    # -- model ------------------------------------------------------------

    @property
    def model_loaded(self) -> bool:
        return self._model_loaded

    def preload(self) -> None:
        """Warm heavy native runtimes *before* the reader thread starts.

        On Windows, loading torch/transformers OR the onnxruntime + DirectML
        (D3D12) native DLLs *after* the worker has begun serving a piped
        session deadlocks inside the Windows loader lock (the reader thread
        is blocked in a stdin read). Doing it up front avoids that, which is
        why the desktop app launches the worker with --preload.
        """
        self.get_captioner(None)
        self.warm_onnx_runtime()
        # Any DLL loaded on demand while the reader thread is blocked on
        # stdin can deadlock the Windows loader, so touch the ones the
        # benchmark command needs (psapi for peak RAM) up front too.
        try:
            from filesight.inference.registry import _peak_ram_mb

            _peak_ram_mb()
        except Exception:  # pragma: no cover - defensive
            pass

    def warm_onnx_runtime(self) -> None:
        """Load the ONNX Runtime + DirectML native DLLs, discarding the session.

        Best effort: a machine without DirectML (or without onnxruntime)
        simply skips it. Failure here never blocks startup.
        """
        if self._onnx_warmed:
            return
        self._onnx_warmed = True
        try:
            from filesight.inference.registry import _directml_available, make_backend

            if _directml_available():
                backend = make_backend("onnx-directml")
            else:
                backend = make_backend("onnx-cpu")
            backend.self_test()  # creates + runs a real session, then...
            backend.close()
        except Exception as exc:  # pragma: no cover - defensive
            log(f"onnx warm-up skipped: {exc}")

    def get_captioner(self, request_id: Optional[str]):
        """Load the vision model once per process."""
        if self._captioner is None:
            if request_id is not None:
                self.emitter.emit(request_id, "phase", {"phase": "Loading model"})
            from filesight.captioner import DEFAULT_MODEL, BlipCaptioner

            captioner = BlipCaptioner(DEFAULT_MODEL)
            try:
                captioner.load()
            except Exception as exc:
                raise WorkerError(
                    "MODEL_LOAD_FAILED",
                    f"Unable to load the local image model: {exc}",
                    recoverable=False,
                ) from exc
            self._captioner = captioner
            self._model_loaded = True
        return self._captioner

    # -- cancellation -----------------------------------------------------

    def cancel_token(self, request_id: str) -> threading.Event:
        with self._lock:
            token = self._cancel_flags.setdefault(request_id, threading.Event())
        return token

    def cancel(self, target_id: str) -> bool:
        """Signal a running operation. Returns False if it is unknown."""
        with self._lock:
            token = self._cancel_flags.get(target_id)
        if token is None:
            return False
        token.set()
        return True

    def release(self, request_id: str) -> None:
        with self._lock:
            self._cancel_flags.pop(request_id, None)

    # -- dispatch ---------------------------------------------------------

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            self.emitter.emit(
                "", "error",
                {"code": "INVALID_JSON", "message": f"Invalid JSON: {exc}",
                 "recoverable": True},
            )
            return
        if not isinstance(message, dict):
            self.emitter.emit(
                "", "error",
                {"code": "INVALID_REQUEST", "message": "Request must be an object.",
                 "recoverable": True},
            )
            return

        request_id = str(message.get("request_id") or "")
        command = message.get("command")
        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        if not command:
            self.emitter.emit(
                request_id, "error",
                {"code": "MISSING_COMMAND", "message": "No command given.",
                 "recoverable": True},
            )
            return

        handler = HANDLERS.get(command)
        if handler is None:
            self.emitter.emit(
                request_id, "error",
                {"code": "UNKNOWN_COMMAND",
                 "message": f"Unknown command: {command}", "recoverable": True},
            )
            return

        # Instant commands answer right here (they import nothing heavy).
        # Everything else is queued for the main thread — see the module
        # docstring for why C-extension imports must not happen off it.
        if command in INLINE_COMMANDS:
            self._run(handler, request_id, payload, command)
        else:
            self._pending.put((handler, request_id, payload, command))

    def _run(self, handler: Callable, request_id: str, payload: dict, command: str) -> None:
        try:
            handler(self, request_id, payload)
        except WorkerError as exc:
            self.emitter.emit(
                request_id, "error",
                {"code": exc.code, "message": str(exc),
                 "recoverable": exc.recoverable, "details": exc.details},
            )
        except Exception as exc:  # never let a bug kill the worker
            log(f"unhandled error in {command}: {traceback.format_exc()}")
            self.emitter.emit(
                request_id, "error",
                {"code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}",
                 "recoverable": True},
            )
        finally:
            self.release(request_id)

    def drain_pending(self, block: bool = False, timeout: Optional[float] = None) -> int:
        """Run queued commands on the *calling* thread. Returns how many ran."""
        count = 0
        while True:
            try:
                item = self._pending.get(block=block, timeout=timeout)
            except queue.Empty:
                return count
            if item is None:
                return count
            self._run(*item)
            count += 1
            block = False  # only the first get may wait

    def _read_loop(self, stream) -> None:
        """Consume stdin on a helper thread and queue work for the main one."""
        try:
            for line in stream:
                self.handle_line(line)
                if self.should_stop.is_set():
                    break
        except Exception as exc:  # pragma: no cover - defensive
            log(f"reader stopped: {exc}")
        finally:
            self._pending.put(None)  # release the main loop

    def run_forever(self, stream=None) -> None:
        stream = stream if stream is not None else sys.stdin
        log(f"worker {__version__} ready (pid {os.getpid()})")
        reader = threading.Thread(target=self._read_loop, args=(stream,), daemon=True)
        reader.start()
        while True:
            item = self._pending.get()
            if item is None:
                break
            self._run(*item)
            if self.should_stop.is_set():
                break
        log("worker stopped")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


def _load_naming(payload: dict):
    """Resolve config + profile the same way the CLI does."""
    from filesight.config import ConfigError, find_config_file, load_config

    config_path = payload.get("config")
    try:
        config = load_config(
            find_config_file(Path(config_path) if config_path else None)
        )
    except ConfigError as exc:
        raise WorkerError("CONFIG_INVALID", str(exc)) from exc
    try:
        profile = config.resolve_profile(payload.get("profile"))
    except ConfigError as exc:
        raise WorkerError("PROFILE_NOT_FOUND", str(exc)) from exc

    template = payload.get("template")
    if template:
        from filesight.templates import unknown_variables

        unknown = unknown_variables(template)
        if unknown:
            raise WorkerError(
                "TEMPLATE_INVALID",
                "Unknown template variable(s): " + ", ".join(sorted(set(unknown))),
            )
        profile.template = template
    if payload.get("language"):
        profile.language = payload["language"]
    if payload.get("transliterate") is not None:
        profile.transliterate = bool(payload["transliterate"])
    return config, profile


def cmd_ping(worker: Worker, request_id: str, payload: dict) -> None:
    worker.emitter.emit(
        request_id, "completed",
        {"pong": True, "version": __version__, "pid": os.getpid(),
         "model_loaded": worker.model_loaded},
    )


def cmd_shutdown(worker: Worker, request_id: str, payload: dict) -> None:
    worker.emitter.emit(request_id, "completed", {"stopping": True})
    worker.should_stop.set()


def cmd_cancel(worker: Worker, request_id: str, payload: dict) -> None:
    target = str(payload.get("target_request_id") or "")
    found = worker.cancel(target)
    worker.emitter.emit(
        request_id, "completed", {"cancelled": found, "target_request_id": target}
    )


def cmd_get_profiles(worker: Worker, request_id: str, payload: dict) -> None:
    from filesight.config import ConfigError, find_config_file, load_config
    from filesight.profiles import BUILT_IN_PROFILES

    config_path = payload.get("config")
    warning = None
    try:
        config = load_config(
            find_config_file(Path(config_path) if config_path else None)
        )
    except ConfigError as exc:
        # A broken config must not break the UI: fall back to built-ins.
        from filesight.config import default_config

        config = default_config()
        warning = str(exc)

    names = config.profile_names()
    profiles = []
    for name in names:
        try:
            profile = config.resolve_profile(name)
        except ConfigError:
            continue
        profiles.append(
            {
                "name": name,
                "template": profile.template,
                "language": profile.language,
                "max_filename_length": profile.max_filename_length,
                "built_in": name in BUILT_IN_PROFILES,
            }
        )
    worker.emitter.emit(
        request_id, "completed",
        {"profiles": profiles, "default_profile": config.default_profile,
         "source": config.source, "warning": warning},
    )


def cmd_get_config(worker: Worker, request_id: str, payload: dict) -> None:
    from filesight.config import ConfigError, find_config_file, load_config

    config_path = payload.get("config")
    try:
        config = load_config(
            find_config_file(Path(config_path) if config_path else None)
        )
    except ConfigError as exc:
        raise WorkerError("CONFIG_INVALID", str(exc)) from exc
    worker.emitter.emit(
        request_id, "completed",
        {
            "source": config.source,
            "config_version": config.config_version,
            "default_profile": config.default_profile,
            "categories": [r.name for r in config.category_rules if r.enabled],
            "warnings": [i.message for i in config.warnings],
        },
    )


def _probe_tool(path: Optional[str], name: str) -> dict:
    """Check exactly one tool: a missing ffprobe must not hide a good ffmpeg."""
    from filesight.video_probe import FFmpegNotFound, _resolve_one

    try:
        resolved = _resolve_one(name, path)
    except FFmpegNotFound as exc:
        return {"available": False, "path": None, "message": str(exc)}
    version = None
    try:
        completed = subprocess.run(
            [resolved, "-version"], capture_output=True, timeout=15, check=False
        )
        first = completed.stdout.decode("utf-8", "replace").splitlines()
        version = first[0] if first else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"available": True, "path": resolved, "version": version}


def cmd_get_environment(worker: Worker, request_id: str, payload: dict) -> None:
    """Report what the app needs, without loading the model."""
    from filesight.config import ConfigError, find_config_file, load_config

    data: dict[str, Any] = {
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "ok": sys.version_info >= (3, 11),
        },
        "filesight": {"version": __version__, "ok": True},
        "model": {"loaded": worker.model_loaded, "name": None, "cache": None},
    }
    try:
        from filesight.captioner import DEFAULT_MODEL

        data["model"]["name"] = DEFAULT_MODEL
        cache = os.environ.get("HF_HOME") or str(
            Path.home() / ".cache" / "huggingface"
        )
        data["model"]["cache"] = cache
        data["model"]["cached"] = Path(cache).exists()
    except Exception as exc:  # pragma: no cover - defensive
        data["model"]["error"] = str(exc)

    data["ffmpeg"] = _probe_tool(payload.get("ffmpeg_path"), "ffmpeg")
    data["ffprobe"] = _probe_tool(payload.get("ffprobe_path"), "ffprobe")

    # Inference backends (cheap availability, no model load, no self-test).
    try:
        from filesight.inference.base import detect_gpu_name, detect_gpu_names
        from filesight.inference.registry import (
            available_backends,
            select_auto_backend,
        )

        backends = available_backends()
        flag = {b["backend_id"]: b["available"] for b in backends}
        dml_ok = bool(flag.get("onnx-directml"))
        cuda_ok = bool(flag.get("onnx-cuda"))
        auto_choice, considered = select_auto_backend()
        data["inference"] = {
            "backends": backends,
            "directml_available": dml_ok,
            "cuda_available": cuda_ok,
            "gpu_name": detect_gpu_name() if dml_ok else None,
            "cuda_device_name": detect_gpu_name("nvidia") if cuda_ok else None,
            "adapters": detect_gpu_names(),
            # What "auto" would pick right now, and why.
            "auto_backend": auto_choice,
            "auto_considered": considered,
        }
    except Exception as exc:  # pragma: no cover - defensive
        data["inference"] = {"error": str(exc)}

    config_path = payload.get("config")
    try:
        config = load_config(
            find_config_file(Path(config_path) if config_path else None)
        )
        data["config"] = {"ok": True, "source": config.source,
                          "default_profile": config.default_profile}
    except ConfigError as exc:
        data["config"] = {"ok": False, "message": str(exc)}

    worker.emitter.emit(request_id, "completed", data)


def cmd_scan(worker: Worker, request_id: str, payload: dict) -> None:
    """The only command that loads the vision model."""
    from filesight.models import ModelInfo, NamingConfiguration
    from filesight.pipeline import ScanCancelled, VideoContext, process_media_files
    from filesight.report import build_report, write_report
    from filesight.scanner import find_media, is_video

    emit = worker.emitter.emit
    token = worker.cancel_token(request_id)

    directory = Path(payload.get("directory") or "")
    if not directory.exists():
        raise WorkerError("DIRECTORY_NOT_FOUND", f"Folder does not exist: {directory}")
    if not directory.is_dir():
        raise WorkerError("NOT_A_DIRECTORY", f"Not a folder: {directory}")
    directory = directory.resolve()

    recursive = bool(payload.get("recursive", False))
    include_videos = bool(payload.get("include_videos", False))
    include_images = bool(payload.get("include_images", True))
    if not include_images and not include_videos:
        raise WorkerError("NO_MEDIA_SELECTED", "Enable images, videos, or both.")

    emit(request_id, "phase", {"phase": "Scanning folder"})
    files = find_media(
        directory, recursive=recursive,
        include_images=include_images, include_videos=include_videos,
    )
    max_files = payload.get("max_files")
    if isinstance(max_files, int) and max_files > 0:
        files = files[:max_files]

    config, profile = _load_naming(payload)
    video_count = sum(1 for f in files if is_video(f))
    emit(
        request_id, "started",
        {"total_files": len(files), "images": len(files) - video_count,
         "videos": video_count, "directory": str(directory),
         "profile": profile.name, "template": profile.template},
    )
    if not files:
        emit(request_id, "completed",
             {"report_path": None, "processed": 0, "failed": 0, "skipped": 0,
              "total": 0, "cancelled": False})
        return

    # Resolve FFmpeg only when videos are actually involved.
    video_context = None
    workspace = None
    tools = None
    if include_videos and video_count:
        from filesight.video_probe import FFmpegNotFound, resolve_tools

        try:
            tools = resolve_tools(
                payload.get("ffmpeg_path"), payload.get("ffprobe_path")
            )
        except FFmpegNotFound as exc:
            raise WorkerError("FFMPEG_NOT_FOUND", str(exc)) from exc

    # Resolve which inference backend will caption this scan (metadata +
    # honest reporting). Captioning currently runs on PyTorch CPU; the
    # selection records whether DirectML is available and any fallback.
    from filesight.inference import resolve_backend
    from filesight.inference.base import BackendError

    emit(request_id, "backend_detection_started", {})
    try:
        selection = resolve_backend(
            requested=payload.get("backend", "auto"),
            allow_fallback=payload.get("allow_fallback", True),
        )
    except BackendError as exc:
        raise WorkerError(exc.code, str(exc)) from exc
    emit(request_id, "backend_detected", selection.report_dict())

    captioner = worker.get_captioner(request_id)
    emit(request_id, "phase", {"phase": "Analyzing"})

    started_at = time.perf_counter()
    completed_count = 0
    total = len(files)

    def on_start(index: int, total_files: int, path: Path) -> None:
        # A preview is generated up front so the UI can show the file it is
        # working on. It costs milliseconds next to captioning, and a
        # failure here must never abort the scan.
        thumbnail = None
        try:
            from filesight.thumbnails import make_thumbnail

            created = make_thumbnail(
                path, size=320, ffmpeg=tools.ffmpeg if tools else None
            )
            thumbnail = str(created) if created else None
        except Exception:
            thumbnail = None
        emit(request_id, "file_started",
             {"index": index, "total": total_files, "path": str(path),
              "name": path.name, "thumbnail": thumbnail,
              "media_type": "video" if is_video(path) else "image"})

    def on_done(index: int, total_files: int, entry) -> None:
        nonlocal completed_count
        completed_count = index
        emit(request_id, "file_completed",
             {"path": entry.original_path, "name": entry.original_name,
              "status": entry.status, "caption": entry.caption,
              "media_type": entry.media_type,
              "category": entry.classification.category if entry.classification else None,
              "suggested_name": entry.suggested_name,
              "error": asdict(entry.error) if entry.error else None})
        emit(request_id, "progress",
             {"completed": index, "total": total_files,
              "percent": round(index * 100 / total_files, 2)})

    def on_frame(label: str, current: int, total_frames: int) -> None:
        emit(request_id, "frame_progress",
             {"label": label, "current": current, "total": total_frames})

    from filesight.naming_preview import NamingSession
    from filesight.temp_files import FrameWorkspace

    naming_session = NamingSession(
        profile, category_rules=config.category_rules,
        template=payload.get("template"),
    )
    entries = []
    cancelled = False
    try:
        if tools is not None:
            workspace = FrameWorkspace()
            video_context = VideoContext(
                ffmpeg=tools.ffmpeg, ffprobe=tools.ffprobe, workspace=workspace,
                max_duration=int(payload.get("max_video_duration") or 120),
                allow_long=bool(payload.get("allow_long_videos", False)),
                num_frames=int(payload.get("video_frames") or 6),
            )
        entries = process_media_files(
            files, captioner, video_context=video_context,
            on_file_progress=on_done, on_frame_progress=on_frame,
            on_file_start=on_start, naming_session=naming_session,
            should_cancel=token.is_set,
        )
    except ScanCancelled as exc:
        cancelled = True
        entries = exc.args[0] if exc.args else []
        emit(request_id, "phase", {"phase": "Cancelled"})
    finally:
        if workspace is not None:
            workspace.cleanup()

    emit(request_id, "phase", {"phase": "Writing report"})
    duration = time.perf_counter() - started_at
    from filesight.models import InferenceInfo

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
        source_directory=directory, recursive=recursive,
        model=ModelInfo(provider="huggingface", name=captioner.model_name,
                        device=captioner.device),
        entries=entries, discovered=len(files), duration_seconds=duration,
        videos_enabled=include_videos,
        naming_configuration=NamingConfiguration(
            source=config.source, profile=profile.name,
            template=payload.get("template") or profile.template,
            language=profile.language, transliterate=profile.transliterate,
            config_version=config.config_version,
        ),
        inference=inference,
    )
    output = payload.get("output")
    report_path = Path(output) if output else directory / "filesight-report.json"
    try:
        write_report(report, report_path)
    except OSError as exc:
        raise WorkerError("REPORT_WRITE_FAILED",
                          f"Cannot write report to {report_path}: {exc}") from exc

    emit(request_id, "completed",
         {"report_path": str(report_path), "processed": report.summary.processed,
          "failed": report.summary.failed, "skipped": report.summary.skipped,
          "total": len(files), "cancelled": cancelled,
          "duration_seconds": round(duration, 2),
          "report": report.to_dict()})


def cmd_load_report(worker: Worker, request_id: str, payload: dict) -> None:
    from filesight.report import ReportLoadError, load_report_dict

    path = Path(payload.get("path") or "")
    try:
        data = load_report_dict(path)
    except ReportLoadError as exc:
        raise WorkerError("REPORT_INVALID", str(exc)) from exc
    worker.emitter.emit(request_id, "completed",
                        {"report": data, "path": str(path)})


def cmd_save_report(worker: Worker, request_id: str, payload: dict) -> None:
    """Persist an edited report, keeping a timestamped backup."""
    import shutil
    from datetime import datetime

    from filesight.report_transform import write_report_dict

    path = Path(payload.get("path") or "")
    report = payload.get("report")
    if not isinstance(report, dict):
        raise WorkerError("INVALID_REPORT", "payload.report must be an object.")
    if not path.name:
        raise WorkerError("INVALID_PATH", "payload.path is required.")

    backup_path = None
    if path.exists() and payload.get("backup", True):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.stem}.backup-{stamp}.json")
        try:
            shutil.copy2(path, backup_path)
        except OSError as exc:
            raise WorkerError("BACKUP_FAILED",
                              f"Cannot create backup {backup_path}: {exc}") from exc
    try:
        write_report_dict(report, path)
    except OSError as exc:
        raise WorkerError("REPORT_WRITE_FAILED",
                          f"Cannot write {path}: {exc}") from exc
    worker.emitter.emit(request_id, "completed",
                        {"path": str(path),
                         "backup_path": str(backup_path) if backup_path else None})


def _issue_dicts(issues) -> list[dict]:
    return [asdict(issue) for issue in issues]


def cmd_validate_report(worker: Worker, request_id: str, payload: dict) -> None:
    from filesight.rename_plan import build_plan

    report, report_path = _report_from_payload(payload)
    plan = build_plan(report, report_path)
    conflict_codes = {"DUPLICATE_TARGET", "TARGET_ALREADY_EXISTS"}
    worker.emitter.emit(
        request_id, "completed",
        {
            "valid": not plan.errors,
            "entries": plan.entries_total,
            "ready": len(plan.renames),
            "skipped": len(plan.skipped),
            "conflicts": sum(1 for e in plan.errors if e.code in conflict_codes),
            "missing": sum(1 for e in plan.errors if e.code == "SOURCE_MISSING"),
            "errors": _issue_dicts(plan.errors),
            "warnings": _issue_dicts(plan.warnings),
        },
    )


def _report_from_payload(payload: dict) -> tuple[dict, Path]:
    """Accept either an inline report object or a path to one."""
    from filesight.report import ReportLoadError, load_report_dict

    report = payload.get("report")
    path = Path(payload.get("path") or "report.json")
    if isinstance(report, dict):
        return report, path
    try:
        return load_report_dict(path), path
    except ReportLoadError as exc:
        raise WorkerError("REPORT_INVALID", str(exc)) from exc


def cmd_build_rename_plan(worker: Worker, request_id: str, payload: dict) -> None:
    from filesight.operation_log import default_log_path
    from filesight.rename_plan import build_plan

    report, report_path = _report_from_payload(payload)
    plan = build_plan(
        report, report_path,
        resolve_conflicts=bool(payload.get("resolve_conflicts", False)),
        limit=payload.get("limit"),
    )
    items = [
        {"entry_index": item.entry_index, "original_path": item.original_path,
         "original_name": item.original_name, "action": item.action,
         "target_name": item.target_name, "final_path": item.final_path,
         "skip_reason": item.skip_reason,
         "conflict_resolved": item.conflict_resolved}
        for item in plan.items
    ]
    worker.emitter.emit(
        request_id, "completed",
        {"items": items, "rename_count": len(plan.renames),
         "skip_count": len(plan.skipped),
         "errors": _issue_dicts(plan.errors),
         "warnings": _issue_dicts(plan.warnings),
         "valid": not plan.errors,
         "log_path": str(default_log_path(report_path))},
    )


def cmd_apply_rename(worker: Worker, request_id: str, payload: dict) -> None:
    from filesight.rename_plan import build_plan
    from filesight.renamer import perform_rename

    report, report_path = _report_from_payload(payload)
    plan = build_plan(
        report, report_path,
        resolve_conflicts=bool(payload.get("resolve_conflicts", False)),
        limit=payload.get("limit"),
    )
    if plan.errors:
        first = plan.errors[0]
        extra = (
            f" (and {len(plan.errors) - 1} more)" if len(plan.errors) > 1 else ""
        )
        raise WorkerError(
            "VALIDATION_FAILED",
            f"{first.message}{extra} Nothing was changed.",
            details=_issue_dicts(plan.errors),
        )
    if not plan.renames:
        worker.emitter.emit(request_id, "completed",
                            {"status": "nothing_to_do", "renamed": 0})
        return

    worker.emitter.emit(request_id, "started",
                        {"total_files": len(plan.renames)})
    log_override = payload.get("log_path")
    log_obj, log_path, result = perform_rename(
        plan, Path(log_override) if log_override else None
    )
    worker.emitter.emit(
        request_id, "completed",
        {
            "status": log_obj.status,
            "renamed": log_obj.summary.completed,
            "failed": log_obj.summary.failed,
            "rolled_back": log_obj.summary.rolled_back,
            "skipped": len(plan.skipped),
            "log_path": str(log_path),
            "error": result.error,
            "all_restored": result.all_restored,
            "operations": [asdict(op) for op in log_obj.operations],
        },
    )


def cmd_undo(worker: Worker, request_id: str, payload: dict) -> None:
    from filesight.operation_log import LogLoadError, load_log
    from filesight.undo import build_undo_plan, perform_undo

    path = Path(payload.get("log_path") or "")
    try:
        log_obj = load_log(path)
    except LogLoadError as exc:
        raise WorkerError("LOG_INVALID", str(exc)) from exc

    if log_obj.status == "undone":
        worker.emitter.emit(request_id, "completed",
                            {"status": "already_undone", "restored": 0})
        return

    plan = build_undo_plan(log_obj)
    if plan.errors:
        worker.emitter.emit(
            request_id, "completed",
            {"status": "blocked", "restored": 0,
             "errors": _issue_dicts(plan.errors)},
        )
        return

    if payload.get("dry_run", False):
        worker.emitter.emit(
            request_id, "completed",
            {"status": "dry_run", "restored": 0,
             "operations": [{"from": op.final_path, "to": op.original_path}
                            for op in plan.ops]},
        )
        return

    result = perform_undo(log_obj, plan, path)
    worker.emitter.emit(
        request_id, "completed",
        {"status": log_obj.status, "restored": log_obj.summary.undone,
         "failed": log_obj.summary.failed, "error": result.error,
         "log_path": str(path),
         "operations": [asdict(op) for op in log_obj.operations]},
    )


def cmd_regenerate_names(worker: Worker, request_id: str, payload: dict) -> None:
    """Re-apply naming rules to an existing report. No model involved."""
    from filesight.report_transform import regenerate_suggestions

    report, _ = _report_from_payload(payload)
    config, profile = _load_naming(payload)
    updated, changes = regenerate_suggestions(
        report, profile, config=config, template=payload.get("template")
    )
    worker.emitter.emit(
        request_id, "completed",
        {"report": updated,
         "changed": sum(1 for c in changes if c.changed),
         "skipped": sum(1 for c in changes if c.skipped_reason),
         "changes": [{"original_name": c.original_name, "old_name": c.old_name,
                      "new_name": c.new_name, "skipped_reason": c.skipped_reason}
                     for c in changes]},
    )


def cmd_test_backend(worker: Worker, request_id: str, payload: dict) -> None:
    """Run a backend self-test and return its diagnostics."""
    from filesight.inference import test_backend

    backend_id = str(payload.get("backend") or "auto")
    if backend_id == "auto":
        # "auto" is a selection policy, not a testable backend; test the
        # best accelerator that is actually present, else the CPU path.
        from filesight.inference.base import BACKEND_PRIORITY
        from filesight.inference.registry import _provider_available

        backend_id = next(
            (b for b in BACKEND_PRIORITY if _provider_available(b)),
            "onnx-cpu",
        )
    diag = test_backend(backend_id)
    worker.emitter.emit(request_id, "completed", diag.to_dict())


def cmd_benchmark_backend(worker: Worker, request_id: str, payload: dict) -> None:
    """Benchmark a backend. Never renames anything."""
    from filesight.inference import benchmark_backend

    worker.emitter.emit(request_id, "benchmark_started",
                        {"backend": payload.get("backend")})
    result = benchmark_backend(
        str(payload.get("backend") or "onnx-cpu"),
        runs=int(payload.get("runs") or 5),
        warmup_runs=int(payload.get("warmup_runs") or 1),
    )
    worker.emitter.emit(request_id, "benchmark_completed", result)


def cmd_list_backends(worker: Worker, request_id: str, payload: dict) -> None:
    from filesight.inference.registry import available_backends

    worker.emitter.emit(request_id, "completed",
                        {"backends": available_backends()})


def cmd_make_thumbnail(worker: Worker, request_id: str, payload: dict) -> None:
    """Create (or reuse) a cached thumbnail. Images use Pillow, videos FFmpeg."""
    from filesight.thumbnails import make_thumbnail

    path = Path(payload.get("path") or "")
    try:
        thumb = make_thumbnail(
            path,
            cache_dir=Path(payload["cache_dir"]) if payload.get("cache_dir") else None,
            size=int(payload.get("size") or 256),
            ffmpeg=payload.get("ffmpeg_path"),
        )
    except FileNotFoundError as exc:
        raise WorkerError("FILE_NOT_FOUND", str(exc)) from exc
    except Exception as exc:
        raise WorkerError("THUMBNAIL_FAILED", str(exc)) from exc
    worker.emitter.emit(request_id, "completed",
                        {"path": str(path),
                         "thumbnail": str(thumb) if thumb else None})


HANDLERS: dict[str, Callable[[Worker, str, dict], None]] = {
    "ping": cmd_ping,
    "shutdown": cmd_shutdown,
    "cancel": cmd_cancel,
    "get_profiles": cmd_get_profiles,
    "get_config": cmd_get_config,
    "get_environment": cmd_get_environment,
    "scan": cmd_scan,
    "load_report": cmd_load_report,
    "save_report": cmd_save_report,
    "validate_report": cmd_validate_report,
    "build_rename_plan": cmd_build_rename_plan,
    "apply_rename": cmd_apply_rename,
    "undo": cmd_undo,
    "regenerate_names": cmd_regenerate_names,
    "make_thumbnail": cmd_make_thumbnail,
    "test_backend": cmd_test_backend,
    "benchmark_backend": cmd_benchmark_backend,
    "list_backends": cmd_list_backends,
}

# Commands answered synchronously on the reader thread (they are fast and
# must not be queued behind a running scan).
INLINE_COMMANDS = {"ping", "cancel", "shutdown"}


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # Force UTF-8 so Cyrillic paths survive the pipe on Windows.
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

    worker = Worker()
    if "--preload" in args:
        log("preloading the vision model before serving requests")
        started = time.perf_counter()
        try:
            worker.preload()
            log(f"model ready in {time.perf_counter() - started:.1f}s")
        except Exception as exc:
            # Not fatal: light commands still work and scan will report it.
            log(f"preload failed: {exc}")
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
