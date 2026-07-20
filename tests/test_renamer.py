import os
from pathlib import Path

from filesight.operation_log import load_log
from filesight.rename_plan import build_plan
from filesight.renamer import perform_rename

from helpers import entry_for, make_file, report_dict, sha256


def run_rename(tmp_path: Path, entries: list[dict], **plan_kwargs):
    plan = build_plan(report_dict(entries), tmp_path / "report.json", **plan_kwargs)
    assert not plan.errors, [i.message for i in plan.errors]
    log_path = tmp_path / "rename-log.json"
    log, resolved_path, result = perform_rename(plan, log_path)
    return log, resolved_path, result


def test_single_file_rename_preserves_content(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"unique-content-1")
    digest = sha256(a)
    log, log_path, result = run_rename(tmp_path, [entry_for(a, "dog.jpg")])
    assert result.error is None
    assert not a.exists()
    assert sha256(tmp_path / "dog.jpg") == digest
    assert log.status == "completed"
    assert log.operations[0].status == "completed"


def test_multiple_files(tmp_path: Path) -> None:
    files = {
        make_file(tmp_path / f"img_{i}.jpg", f"content-{i}".encode()): f"name-{i}.jpg"
        for i in range(4)
    }
    entries = [entry_for(f, name) for f, name in files.items()]
    log, _, result = run_rename(tmp_path, entries)
    assert result.error is None
    for i in range(4):
        assert (tmp_path / f"name-{i}.jpg").read_bytes() == f"content-{i}".encode()
    assert log.summary.completed == 4


def test_swap_two_files(tmp_path: Path) -> None:
    a = make_file(tmp_path / "a.jpg", b"AAA")
    b = make_file(tmp_path / "b.jpg", b"BBB")
    entries = [entry_for(a, "b.jpg"), entry_for(b, "a.jpg")]
    _, _, result = run_rename(tmp_path, entries)
    assert result.error is None
    assert (tmp_path / "a.jpg").read_bytes() == b"BBB"
    assert (tmp_path / "b.jpg").read_bytes() == b"AAA"


def test_three_file_cycle(tmp_path: Path) -> None:
    a = make_file(tmp_path / "a.jpg", b"AAA")
    b = make_file(tmp_path / "b.jpg", b"BBB")
    c = make_file(tmp_path / "c.jpg", b"CCC")
    entries = [entry_for(a, "b.jpg"), entry_for(b, "c.jpg"), entry_for(c, "a.jpg")]
    _, _, result = run_rename(tmp_path, entries)
    assert result.error is None
    assert (tmp_path / "b.jpg").read_bytes() == b"AAA"
    assert (tmp_path / "c.jpg").read_bytes() == b"BBB"
    assert (tmp_path / "a.jpg").read_bytes() == b"CCC"


def test_case_only_rename(tmp_path: Path) -> None:
    a = make_file(tmp_path / "photo.jpg", b"PIC")
    _, _, result = run_rename(tmp_path, [entry_for(a, "Photo.jpg")])
    assert result.error is None
    names = [p.name for p in tmp_path.iterdir()]
    assert "Photo.jpg" in names
    assert "photo.jpg" not in names  # exact-case listing on Windows/NTFS


class FlakyRename:
    """Wraps os.rename and fails when the destination matches a marker."""

    def __init__(self, fail_when, times: int = 1) -> None:
        self.real_rename = os.rename
        self.fail_when = fail_when
        self.remaining = times
        self.calls: list[tuple[str, str]] = []

    def __call__(self, src, dst) -> None:
        self.calls.append((str(src), str(dst)))
        if self.remaining > 0 and self.fail_when(str(src), str(dst)):
            self.remaining -= 1
            raise OSError("injected failure")
        self.real_rename(src, dst)


def test_phase1_failure_rolls_back(tmp_path: Path, monkeypatch) -> None:
    a = make_file(tmp_path / "a.jpg", b"AAA")
    b = make_file(tmp_path / "b.jpg", b"BBB")
    # Fail when trying to move the SECOND source into its temp name.
    flaky = FlakyRename(
        fail_when=lambda src, dst: src.endswith("b.jpg") and ".filesight-tmp-" in dst
    )
    monkeypatch.setattr(os, "rename", flaky)
    log, log_path, result = run_rename(
        tmp_path, [entry_for(a, "x.jpg"), entry_for(b, "y.jpg")]
    )
    assert result.error is not None
    assert result.all_restored
    assert (tmp_path / "a.jpg").read_bytes() == b"AAA"
    assert (tmp_path / "b.jpg").read_bytes() == b"BBB"
    assert not (tmp_path / "x.jpg").exists()
    assert log.status == "rolled_back"
    statuses = {op.status for op in log.operations}
    assert statuses == {"rolled_back", "failed"}


def test_phase2_failure_rolls_back(tmp_path: Path, monkeypatch) -> None:
    a = make_file(tmp_path / "a.jpg", b"AAA")
    b = make_file(tmp_path / "b.jpg", b"BBB")
    # Fail when moving a temp file to the final name y.jpg.
    flaky = FlakyRename(
        fail_when=lambda src, dst: ".filesight-tmp-" in src and dst.endswith("y.jpg")
    )
    monkeypatch.setattr(os, "rename", flaky)
    log, _, result = run_rename(
        tmp_path, [entry_for(a, "x.jpg"), entry_for(b, "y.jpg")]
    )
    assert result.error is not None
    assert result.all_restored
    assert (tmp_path / "a.jpg").read_bytes() == b"AAA"
    assert (tmp_path / "b.jpg").read_bytes() == b"BBB"
    assert not (tmp_path / "x.jpg").exists()
    assert not (tmp_path / "y.jpg").exists()
    assert log.status == "rolled_back"
    # no stray temp files left behind
    assert not [p for p in tmp_path.iterdir() if ".filesight-tmp-" in p.name]


def test_partial_rollback_is_reported_honestly(tmp_path: Path, monkeypatch) -> None:
    a = make_file(tmp_path / "a.jpg", b"AAA")
    b = make_file(tmp_path / "b.jpg", b"BBB")

    real = os.rename

    def cursed(src, dst) -> None:
        # b.jpg can never be moved anywhere again once it is in a temp spot:
        # its phase-2 move fails AND its rollback fails.
        if str(src) in cursed.stuck_temps:
            raise OSError("injected persistent failure")
        real(src, dst)

    cursed.stuck_temps = set()

    def tracking(src, dst) -> None:
        if str(src).endswith("b.jpg") and ".filesight-tmp-" in str(dst):
            cursed.stuck_temps.add(str(dst))
        cursed(src, dst)

    monkeypatch.setattr(os, "rename", tracking)
    log, log_path, result = run_rename(
        tmp_path, [entry_for(a, "x.jpg"), entry_for(b, "y.jpg")]
    )
    assert result.error is not None
    assert not result.all_restored
    assert log.status == "partially_rolled_back"
    failed_ops = [op for op in log.operations if op.status == "failed"]
    assert failed_ops and failed_ops[0].error
    # a.jpg was restored, b's bytes still exist somewhere (in a temp file)
    assert (tmp_path / "a.jpg").read_bytes() == b"AAA"
    all_bytes = {p.read_bytes() for p in tmp_path.iterdir() if p.suffix == ".jpg"}
    assert b"BBB" in all_bytes


def test_log_is_written_before_and_during_execution(
    tmp_path: Path, monkeypatch
) -> None:
    a = make_file(tmp_path / "a.jpg", b"AAA")
    log_path = tmp_path / "rename-log.json"
    seen_statuses: list[str] = []

    import filesight.renamer as renamer_module

    real_write = renamer_module.write_log

    def spy_write(log, path) -> None:
        seen_statuses.append(
            (log.status, tuple(op.status for op in log.operations))
        )
        real_write(log, path)

    monkeypatch.setattr(renamer_module, "write_log", spy_write)
    plan = build_plan(
        report_dict([entry_for(a, "dog.jpg")]), tmp_path / "report.json"
    )
    perform_rename(plan, log_path)

    # first write happens before any file is touched: everything "planned"
    assert seen_statuses[0] == ("in_progress", ("planned",))
    # intermediate write shows the in-progress state
    assert ("in_progress", ("in_progress",)) in seen_statuses
    # final write is the completed log
    assert seen_statuses[-1][0] == "completed"
    saved = load_log(log_path)
    assert saved.status == "completed"
    assert saved.operations[0].temporary_path is not None
