import os
from pathlib import Path

from filesight.operation_log import load_log
from filesight.rename_plan import build_plan
from filesight.renamer import perform_rename
from filesight.undo import build_undo_plan, perform_undo

from helpers import entry_for, make_file, report_dict, sha256


def rename_files(tmp_path: Path, entries: list[dict]):
    plan = build_plan(report_dict(entries), tmp_path / "report.json")
    assert not plan.errors, [i.message for i in plan.errors]
    log_path = tmp_path / "rename-log.json"
    log, _, result = perform_rename(plan, log_path)
    assert result.error is None
    return log, log_path


def test_undo_restores_original_names_and_content(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"unique-A")
    b = make_file(tmp_path / "IMG_2.jpg", b"unique-B")
    digests = {"IMG_1.jpg": sha256(a), "IMG_2.jpg": sha256(b)}
    log, log_path = rename_files(
        tmp_path, [entry_for(a, "dog.jpg"), entry_for(b, "cat.jpg")]
    )

    plan = build_undo_plan(log)
    assert not plan.errors
    result = perform_undo(log, plan, log_path)
    assert result.error is None
    assert sha256(tmp_path / "IMG_1.jpg") == digests["IMG_1.jpg"]
    assert sha256(tmp_path / "IMG_2.jpg") == digests["IMG_2.jpg"]
    assert not (tmp_path / "dog.jpg").exists()

    saved = load_log(log_path)
    assert saved.status == "undone"
    assert saved.undone_at is not None
    assert all(op.status == "undone" for op in saved.operations)


def test_undo_dry_run_changes_nothing(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"AAA")
    log, log_path = rename_files(tmp_path, [entry_for(a, "dog.jpg")])
    plan = build_undo_plan(log)  # building the plan is the dry-run
    assert not plan.errors
    assert (tmp_path / "dog.jpg").exists()
    assert not (tmp_path / "IMG_1.jpg").exists()
    assert load_log(log_path).status == "completed"


def test_repeated_undo_is_a_safe_no_op(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"AAA")
    log, log_path = rename_files(tmp_path, [entry_for(a, "dog.jpg")])
    perform_undo(log, build_undo_plan(log), log_path)

    reloaded = load_log(log_path)
    assert reloaded.status == "undone"  # CLI stops here with a clear message
    plan = build_undo_plan(reloaded)  # even if forced, nothing is eligible
    assert [i.code for i in plan.errors] == ["NOTHING_TO_UNDO"]
    assert (tmp_path / "IMG_1.jpg").read_bytes() == b"AAA"


def test_undo_blocked_when_original_path_occupied(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"AAA")
    log, log_path = rename_files(tmp_path, [entry_for(a, "dog.jpg")])
    make_file(tmp_path / "IMG_1.jpg", b"INTRUDER")  # foreign file took the spot
    plan = build_undo_plan(log)
    assert [i.code for i in plan.errors] == ["UNDO_TARGET_OCCUPIED"]


def test_undo_blocked_when_final_file_missing(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"AAA")
    log, log_path = rename_files(tmp_path, [entry_for(a, "dog.jpg")])
    (tmp_path / "dog.jpg").unlink()
    plan = build_undo_plan(log)
    assert [i.code for i in plan.errors] == ["UNDO_FILE_MISSING"]


def test_undo_blocked_when_file_replaced(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"AAA")
    log, log_path = rename_files(tmp_path, [entry_for(a, "dog.jpg")])
    (tmp_path / "dog.jpg").write_bytes(b"a completely different file!")
    plan = build_undo_plan(log)
    assert [i.code for i in plan.errors] == ["UNDO_FILE_CHANGED"]


def test_undo_of_swap_cycle(tmp_path: Path) -> None:
    a = make_file(tmp_path / "a.jpg", b"AAA")
    b = make_file(tmp_path / "b.jpg", b"BBB")
    log, log_path = rename_files(tmp_path, [entry_for(a, "b.jpg"), entry_for(b, "a.jpg")])
    assert (tmp_path / "a.jpg").read_bytes() == b"BBB"

    plan = build_undo_plan(log)
    assert not plan.errors, [i.message for i in plan.errors]
    result = perform_undo(log, plan, log_path)
    assert result.error is None
    assert (tmp_path / "a.jpg").read_bytes() == b"AAA"
    assert (tmp_path / "b.jpg").read_bytes() == b"BBB"


def test_partial_undo_failure_is_recorded(tmp_path: Path, monkeypatch) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"AAA")
    b = make_file(tmp_path / "IMG_2.jpg", b"BBB")
    log, log_path = rename_files(
        tmp_path, [entry_for(a, "dog.jpg"), entry_for(b, "cat.jpg")]
    )

    real = os.rename
    stuck: set = set()

    def tracking(src, dst) -> None:
        if str(src) in stuck:
            raise OSError("injected persistent failure")
        if str(src).endswith("cat.jpg") and ".filesight-tmp-" in str(dst):
            stuck.add(str(dst))
        real(src, dst)

    monkeypatch.setattr(os, "rename", tracking)
    plan = build_undo_plan(log)
    result = perform_undo(log, plan, log_path)

    assert result.error is not None
    assert not result.all_restored
    saved = load_log(log_path)
    assert saved.status == "partially_undone"
    statuses = sorted(op.status for op in saved.operations)
    # the failed op is recorded; the other one was safely rolled back to
    # its renamed state (status stays "completed")
    assert "failed" in statuses
    assert "completed" in statuses
    failed_op = next(op for op in saved.operations if op.status == "failed")
    assert failed_op.error
    # no data lost: both contents still exist somewhere in the folder
    contents = {p.read_bytes() for p in tmp_path.iterdir() if p.suffix == ".jpg"}
    assert {b"AAA", b"BBB"} <= contents
