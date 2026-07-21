"""Worker protocol tests. None of these load the vision model."""

import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from filesight.worker import Emitter, Worker

from helpers import make_file


class Collector(Emitter):
    """Captures emitted events instead of writing to stdout."""

    def __init__(self) -> None:
        super().__init__(stream=io.StringIO())
        self.events: list[dict] = []

    def emit(self, request_id, event, data=None):  # type: ignore[override]
        self.events.append(
            {"request_id": request_id, "event": event, "data": data or {}}
        )

    def kinds(self) -> list[str]:
        return [e["event"] for e in self.events]

    def last(self) -> dict:
        return self.events[-1]

    def of(self, kind: str) -> list[dict]:
        return [e for e in self.events if e["event"] == kind]


def run(worker: Worker, command: str, payload: dict | None = None, rid: str = "r1"):
    """Send one request and run any queued work, exactly like run_forever."""
    worker.handle_line(
        json.dumps({"request_id": rid, "command": command, "payload": payload or {}})
    )
    worker.drain_pending()
    return worker


@pytest.fixture()
def worker() -> tuple[Worker, Collector]:
    collector = Collector()
    return Worker(emitter=collector), collector


# --- protocol basics ------------------------------------------------------


def test_valid_request_is_answered_with_its_request_id(worker) -> None:
    instance, events = worker
    run(instance, "ping", rid="abc-123")
    assert events.last()["request_id"] == "abc-123"
    assert events.last()["event"] == "completed"


def test_ping_reports_version_and_no_model(worker) -> None:
    instance, events = worker
    run(instance, "ping")
    data = events.last()["data"]
    assert data["pong"] is True
    assert data["model_loaded"] is False
    assert data["version"]


def test_invalid_json_yields_a_structured_error(worker) -> None:
    instance, events = worker
    instance.handle_line("{ this is not json")
    assert events.last()["event"] == "error"
    assert events.last()["data"]["code"] == "INVALID_JSON"
    assert events.last()["data"]["recoverable"] is True


def test_non_object_request_is_rejected(worker) -> None:
    instance, events = worker
    instance.handle_line("[1, 2, 3]")
    assert events.last()["data"]["code"] == "INVALID_REQUEST"


def test_unknown_command_yields_an_error(worker) -> None:
    instance, events = worker
    run(instance, "fly_to_the_moon")
    assert events.last()["event"] == "error"
    assert events.last()["data"]["code"] == "UNKNOWN_COMMAND"


def test_missing_command_is_rejected(worker) -> None:
    instance, events = worker
    instance.handle_line(json.dumps({"request_id": "x", "payload": {}}))
    assert events.last()["data"]["code"] == "MISSING_COMMAND"


def test_blank_lines_are_ignored(worker) -> None:
    instance, events = worker
    instance.handle_line("   \n")
    assert events.events == []


# --- cancellation ---------------------------------------------------------


def test_cancel_of_an_unknown_operation_reports_false(worker) -> None:
    instance, events = worker
    run(instance, "cancel", {"target_request_id": "nope"})
    assert events.last()["data"]["cancelled"] is False


def test_cancel_sets_the_token_of_a_known_operation(worker) -> None:
    instance, events = worker
    token = instance.cancel_token("scan-1")
    assert not token.is_set()
    run(instance, "cancel", {"target_request_id": "scan-1"}, rid="c1")
    assert events.last()["data"]["cancelled"] is True
    assert token.is_set()


def test_cancel_stops_an_in_flight_scan(tmp_path: Path) -> None:
    """A scan polls the cancel token and stops without touching files."""
    from filesight.pipeline import ScanCancelled, process_media_files

    files = [make_file(tmp_path / f"IMG_{i}.jpg") for i in range(5)]
    stop = threading.Event()

    class SlowCaptioner:
        model_name = "fake"
        device = "cpu"

        def caption(self, image):  # pragma: no cover - not reached
            return "a photo"

    processed: list[str] = []

    def should_cancel() -> bool:
        # cancel after the first file is dispatched
        if processed:
            stop.set()
        return stop.is_set()

    def on_start(index, total, path):
        processed.append(str(path))

    with pytest.raises(ScanCancelled):
        process_media_files(
            files, SlowCaptioner(), on_file_start=on_start,
            should_cancel=should_cancel,
        )
    assert len(processed) < len(files)


# --- lifecycle ------------------------------------------------------------


def test_shutdown_sets_the_stop_flag(worker) -> None:
    instance, events = worker
    run(instance, "shutdown")
    assert instance.should_stop.is_set()
    assert events.last()["data"]["stopping"] is True


def test_run_forever_exits_when_stdin_closes(worker) -> None:
    instance, events = worker
    stream = io.StringIO(
        json.dumps({"request_id": "a", "command": "ping", "payload": {}}) + "\n"
    )
    instance.run_forever(stream=stream)
    assert "completed" in events.kinds()


# --- light commands must not load the model -------------------------------


@pytest.mark.parametrize(
    "command,payload",
    [
        ("ping", {}),
        ("get_profiles", {}),
        ("get_config", {}),
        ("get_environment", {}),
    ],
)
def test_light_commands_do_not_load_the_model(worker, command, payload) -> None:
    instance, events = worker
    run(instance, command, payload)
    assert instance.model_loaded is False
    assert events.last()["event"] == "completed"


def test_get_profiles_lists_built_ins(worker) -> None:
    instance, events = worker
    run(instance, "get_profiles")
    names = [p["name"] for p in events.last()["data"]["profiles"]]
    assert {"default", "photos", "compact", "archive"} <= set(names)


def test_get_profiles_survives_a_broken_config(worker, tmp_path: Path) -> None:
    bad = tmp_path / "broken.toml"
    bad.write_text('config_version = "99.0"\n', encoding="utf-8")
    instance, events = worker
    run(instance, "get_profiles", {"config": str(bad)})
    data = events.last()["data"]
    assert events.last()["event"] == "completed"  # falls back, does not fail
    assert data["warning"]
    assert any(p["name"] == "default" for p in data["profiles"])


def test_get_environment_reports_python_and_tools(worker) -> None:
    instance, events = worker
    run(instance, "get_environment")
    data = events.last()["data"]
    assert data["python"]["ok"] is True
    assert data["filesight"]["ok"] is True
    assert "available" in data["ffmpeg"]
    assert data["model"]["loaded"] is False


def test_each_ffmpeg_tool_is_probed_independently(worker, tmp_path: Path) -> None:
    """A missing ffprobe must not report a present ffmpeg as unavailable."""
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_bytes(b"stub")

    instance, events = worker
    run(instance, "get_environment", {"ffmpeg_path": str(fake_ffmpeg),
                                      "ffprobe_path": str(tmp_path / "absent.exe")})
    data = events.last()["data"]
    assert data["ffmpeg"]["available"] is True
    assert data["ffmpeg"]["path"] == str(fake_ffmpeg)
    assert data["ffprobe"]["available"] is False


# --- report commands ------------------------------------------------------


def report_dict_for(path: Path) -> dict:
    return {
        "schema_version": "1.3",
        "created_at": "2026-07-21T00:00:00Z",
        "source_directory": str(path.parent),
        "recursive": False,
        "model": {"provider": "huggingface", "name": "fake", "device": "cpu"},
        "summary": {
            "discovered": 1, "processed": 1, "failed": 0,
            "skipped": 0, "duration_seconds": 1.0,
        },
        "files": [
            {
                "original_path": str(path),
                "original_name": path.name,
                "extension": path.suffix,
                "status": "success",
                "media_type": "image",
                "caption": "a black dog running",
                "suggested_name": "black-dog-running.jpg",
                "processing_time_ms": 5,
                "error": None,
                "rename_enabled": True,
            }
        ],
    }


def test_validate_report_returns_counts(worker, tmp_path: Path) -> None:
    image = make_file(tmp_path / "IMG_1.jpg")
    instance, events = worker
    run(instance, "validate_report", {"report": report_dict_for(image),
                                      "path": str(tmp_path / "r.json")})
    data = events.last()["data"]
    assert data["valid"] is True
    assert data["ready"] == 1
    assert instance.model_loaded is False


def test_build_rename_plan_lists_operations(worker, tmp_path: Path) -> None:
    image = make_file(tmp_path / "IMG_1.jpg")
    instance, events = worker
    run(instance, "build_rename_plan", {"report": report_dict_for(image),
                                        "path": str(tmp_path / "r.json")})
    data = events.last()["data"]
    assert data["rename_count"] == 1
    assert data["items"][0]["target_name"] == "black-dog-running.jpg"
    assert data["log_path"].endswith(".json")


def test_apply_rename_and_undo_round_trip(worker, tmp_path: Path) -> None:
    image = make_file(tmp_path / "IMG_1.jpg", b"unique-bytes")
    report_path = tmp_path / "report.json"
    instance, events = worker

    run(instance, "apply_rename",
        {"report": report_dict_for(image), "path": str(report_path)}, rid="ren")
    result = events.last()["data"]
    assert result["status"] == "completed"
    assert result["renamed"] == 1
    assert (tmp_path / "black-dog-running.jpg").read_bytes() == b"unique-bytes"
    assert not image.exists()

    events.events.clear()
    run(instance, "undo", {"log_path": result["log_path"]}, rid="undo")
    undo = events.last()["data"]
    assert undo["status"] == "undone"
    assert undo["restored"] == 1
    assert image.read_bytes() == b"unique-bytes"
    assert instance.model_loaded is False


def test_apply_rename_error_names_the_actual_problems(
    worker, tmp_path: Path
) -> None:
    """A bare VALIDATION_FAILED code leaves the user with nothing to act on."""
    image = make_file(tmp_path / "IMG_1.jpg")
    make_file(tmp_path / "black-dog-running.jpg")  # target already taken

    instance, events = worker
    run(instance, "apply_rename",
        {"report": report_dict_for(image), "path": str(tmp_path / "r.json")})

    event = events.last()
    assert event["event"] == "error"
    assert event["data"]["code"] == "VALIDATION_FAILED"
    # the message says what is wrong, not just that something is
    assert "black-dog-running.jpg" in event["data"]["message"]
    details = event["data"]["details"]
    assert details and details[0]["code"] == "TARGET_ALREADY_EXISTS"
    assert details[0]["path"].endswith("black-dog-running.jpg")
    # and nothing was renamed
    assert image.exists()


def test_apply_rename_error_counts_extra_problems(worker, tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg")
    b = make_file(tmp_path / "IMG_2.jpg")
    report = report_dict_for(a)
    second = dict(report["files"][0])
    second.update({"original_path": str(b), "original_name": b.name})
    report["files"].append(second)  # both target black-dog-running.jpg

    instance, events = worker
    run(instance, "apply_rename", {"report": report, "path": str(tmp_path / "r.json")})
    data = events.last()["data"]
    assert data["code"] == "VALIDATION_FAILED"
    assert [d["code"] for d in data["details"]] == ["DUPLICATE_TARGET"]


def test_undo_dry_run_changes_nothing(worker, tmp_path: Path) -> None:
    image = make_file(tmp_path / "IMG_1.jpg", b"bytes")
    instance, events = worker
    run(instance, "apply_rename",
        {"report": report_dict_for(image), "path": str(tmp_path / "r.json")})
    log_path = events.last()["data"]["log_path"]

    events.events.clear()
    run(instance, "undo", {"log_path": log_path, "dry_run": True})
    data = events.last()["data"]
    assert data["status"] == "dry_run"
    assert data["restored"] == 0
    assert (tmp_path / "black-dog-running.jpg").exists()  # still renamed


def test_save_report_creates_a_backup(worker, tmp_path: Path) -> None:
    image = make_file(tmp_path / "IMG_1.jpg")
    target = tmp_path / "report.json"
    target.write_text('{"old": true}', encoding="utf-8")

    instance, events = worker
    run(instance, "save_report",
        {"path": str(target), "report": report_dict_for(image)})
    data = events.last()["data"]
    assert data["backup_path"]
    assert Path(data["backup_path"]).exists()
    assert json.loads(target.read_text(encoding="utf-8"))["schema_version"] == "1.3"


def test_load_report_rejects_a_broken_file(worker, tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    instance, events = worker
    run(instance, "load_report", {"path": str(broken)})
    assert events.last()["event"] == "error"
    assert events.last()["data"]["code"] == "REPORT_INVALID"


def test_regenerate_names_uses_captions_not_the_model(worker, tmp_path: Path) -> None:
    image = make_file(tmp_path / "IMG_1.jpg")
    instance, events = worker
    # "photos" prepends the category, so the name genuinely changes
    run(instance, "regenerate_names",
        {"report": report_dict_for(image), "profile": "photos"})
    data = events.last()["data"]
    assert data["changed"] == 1
    assert data["report"]["files"][0]["suggested_name"] == "animals-black-dog.jpg"
    assert data["report"]["files"][0]["caption"] == "a black dog running"
    assert instance.model_loaded is False


def test_regenerate_names_reports_no_change_when_the_name_is_stable(
    worker, tmp_path: Path
) -> None:
    image = make_file(tmp_path / "IMG_1.jpg")
    instance, events = worker
    # "compact" reproduces the name already in the report
    run(instance, "regenerate_names",
        {"report": report_dict_for(image), "profile": "compact"})
    data = events.last()["data"]
    assert data["report"]["files"][0]["suggested_name"] == "black-dog-running.jpg"
    assert data["changed"] == 0


def test_scan_of_an_empty_folder_completes_without_the_model(
    worker, tmp_path: Path
) -> None:
    instance, events = worker
    run(instance, "scan", {"directory": str(tmp_path)})
    assert events.last()["event"] == "completed"
    assert events.last()["data"]["total"] == 0
    assert instance.model_loaded is False


def test_scan_of_a_missing_directory_reports_an_error(worker, tmp_path: Path) -> None:
    instance, events = worker
    run(instance, "scan", {"directory": str(tmp_path / "nope")})
    assert events.last()["event"] == "error"
    assert events.last()["data"]["code"] == "DIRECTORY_NOT_FOUND"


def test_scan_requires_at_least_one_media_type(worker, tmp_path: Path) -> None:
    instance, events = worker
    run(instance, "scan", {"directory": str(tmp_path),
                           "include_images": False, "include_videos": False})
    assert events.last()["data"]["code"] == "NO_MEDIA_SELECTED"


def test_make_thumbnail_for_an_image(worker, tmp_path: Path) -> None:
    from PIL import Image

    source = tmp_path / "pic.png"
    Image.new("RGB", (64, 48), (10, 120, 200)).save(source)
    cache = tmp_path / "cache"

    instance, events = worker
    run(instance, "make_thumbnail",
        {"path": str(source), "cache_dir": str(cache), "size": 32})
    thumb = events.last()["data"]["thumbnail"]
    assert thumb and Path(thumb).is_file()
    with Image.open(thumb) as img:
        assert max(img.size) <= 32


def test_make_thumbnail_of_a_missing_file_errors(worker, tmp_path: Path) -> None:
    instance, events = worker
    run(instance, "make_thumbnail", {"path": str(tmp_path / "ghost.png")})
    assert events.last()["event"] == "error"
    assert events.last()["data"]["code"] == "FILE_NOT_FOUND"


# --- stdout purity (end-to-end over a real pipe) --------------------------


def test_stdout_carries_only_json_and_stderr_stays_separate() -> None:
    """The GUI parses stdout; diagnostics must never contaminate it."""
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "filesight.worker"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    try:
        requests = "".join(
            json.dumps({"request_id": f"r{i}", "command": command, "payload": {}}) + "\n"
            for i, command in enumerate(["ping", "get_profiles", "shutdown"])
        )
        stdout, stderr = process.communicate(requests, timeout=120)
    finally:
        if process.poll() is None:
            process.kill()

    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, "worker produced no output"
    for line in lines:
        payload = json.loads(line)  # every line must be valid JSON
        assert "request_id" in payload and "event" in payload
    assert process.returncode == 0
    # stderr is where human-readable logging goes
    assert "filesight.worker" in stderr


def test_preload_flag_is_accepted_and_light_commands_still_work() -> None:
    """--preload must not change the protocol, only when the model loads.

    Uses a stub captioner so the test stays fast and model-free.
    """
    code = (
        "import filesight.worker as w;"
        "w.Worker.preload = lambda self: None;"
        "w.main(['--preload'])"
    )
    process = subprocess.run(
        [sys.executable, "-u", "-c", code],
        input=json.dumps({"request_id": "p", "command": "ping", "payload": {}}) + "\n"
        + json.dumps({"request_id": "s", "command": "shutdown", "payload": {}}) + "\n",
        capture_output=True, text=True, timeout=120,
    )
    assert process.returncode == 0
    lines = [json.loads(l) for l in process.stdout.splitlines() if l.strip()]
    assert any(e["request_id"] == "p" and e["event"] == "completed" for e in lines)


def test_worker_without_preload_does_not_load_the_model(worker) -> None:
    """A plain worker stays model-free until a scan actually needs one."""
    instance, _ = worker
    run(instance, "ping")
    run(instance, "get_profiles")
    assert instance.model_loaded is False


def test_worker_module_is_runnable_and_exits_cleanly() -> None:
    process = subprocess.run(
        [sys.executable, "-u", "-m", "filesight.worker"],
        input=json.dumps({"request_id": "x", "command": "shutdown", "payload": {}}) + "\n",
        capture_output=True, text=True, timeout=120,
    )
    assert process.returncode == 0
    assert '"event": "completed"' in process.stdout


def test_two_sequential_scans_do_not_conflict(worker, tmp_path: Path) -> None:
    """Repeated scan requests are serialized per request id, not merged."""
    instance, events = worker
    run(instance, "scan", {"directory": str(tmp_path)}, rid="s1")
    run(instance, "scan", {"directory": str(tmp_path)}, rid="s2")
    completed = events.of("completed")
    assert len(completed) == 2
    assert {e["request_id"] for e in completed} == {"s1", "s2"}
    # each operation released its cancel token
    assert instance._cancel_flags == {}  # noqa: SLF001 - test hook


def test_long_commands_are_queued_not_run_on_the_reader_thread(worker) -> None:
    """Heavy work must never execute on the stdin reader thread.

    Importing C extensions off the main thread deadlocks under piped
    stdio, so handle_line only enqueues; the main loop does the work.
    """
    instance, events = worker
    instance.handle_line(
        json.dumps({"request_id": "q1", "command": "get_profiles", "payload": {}})
    )
    assert events.events == []  # nothing ran yet
    assert instance.drain_pending() == 1
    assert events.last()["event"] == "completed"


def test_inline_commands_answer_without_draining(worker) -> None:
    instance, events = worker
    for command in ("ping", "cancel", "shutdown"):
        events.events.clear()
        instance.handle_line(
            json.dumps({"request_id": command, "command": command, "payload": {}})
        )
        assert events.last()["event"] == "completed", command


def test_run_forever_processes_work_on_the_calling_thread(worker) -> None:
    """The main loop must run commands itself, not hand them to a thread."""
    instance, events = worker
    seen: list[int] = []

    def record(_worker, rid, _payload):
        seen.append(threading.get_ident())
        _worker.emitter.emit(rid, "completed", {})

    from filesight import worker as worker_module

    worker_module.HANDLERS["record_thread_for_test"] = record
    try:
        stream = io.StringIO(
            json.dumps({"request_id": "a", "command": "record_thread_for_test",
                        "payload": {}}) + "\n"
        )
        instance.run_forever(stream=stream)
    finally:
        worker_module.HANDLERS.pop("record_thread_for_test", None)

    assert seen == [threading.get_ident()]


def test_internal_errors_are_reported_not_fatal(worker) -> None:
    instance, events = worker

    def explode(_worker, _rid, _payload):
        raise RuntimeError("boom")

    from filesight import worker as worker_module

    worker_module.HANDLERS["explode_for_test"] = explode
    try:
        run(instance, "explode_for_test")
        assert events.last()["event"] == "error"
        assert events.last()["data"]["code"] == "INTERNAL_ERROR"
        # the worker is still usable afterwards
        events.events.clear()
        run(instance, "ping", rid="after")
        assert events.last()["event"] == "completed"
    finally:
        worker_module.HANDLERS.pop("explode_for_test", None)


def test_emitter_is_thread_safe() -> None:
    """Concurrent emits must not interleave into a corrupt line."""
    stream = io.StringIO()
    emitter = Emitter(stream=stream)

    def emit_many(index: int) -> None:
        for step in range(50):
            emitter.emit(f"r{index}", "progress", {"step": step, "pad": "x" * 200})

    threads = [threading.Thread(target=emit_many, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 8 * 50
    for line in lines:
        json.loads(line)  # never a torn line
