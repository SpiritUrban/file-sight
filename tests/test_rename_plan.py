from pathlib import Path

from filesight.rename_plan import build_plan
from filesight.validation import (
    SKIP_DISABLED,
    SKIP_OVER_LIMIT,
    SKIP_UNCHANGED,
)

from helpers import entry_for, error_codes, make_file, report_dict


def plan_for(tmp_path: Path, entries: list[dict], **kwargs):
    return build_plan(report_dict(entries), tmp_path / "report.json", **kwargs)


def test_normal_plan(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg")
    plan = plan_for(tmp_path, [entry_for(a, "dog.jpg")])
    assert len(plan.renames) == 1
    item = plan.renames[0]
    assert item.final_path == str(tmp_path / "dog.jpg")
    assert item.action == "rename"


def test_failed_entries_are_skipped(tmp_path: Path) -> None:
    broken = make_file(tmp_path / "broken.png")
    plan = plan_for(
        tmp_path, [entry_for(broken, None, status="failed", with_metadata=False)]
    )
    assert plan.renames == []
    assert plan.skipped[0].skip_reason == "report status is failed"
    assert error_codes(plan) == []


def test_rename_enabled_false_is_skipped(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg")
    plan = plan_for(tmp_path, [entry_for(a, "dog.jpg", rename_enabled=False)])
    assert plan.renames == []
    assert plan.skipped[0].skip_reason == SKIP_DISABLED


def test_unchanged_name_is_skipped(tmp_path: Path) -> None:
    a = make_file(tmp_path / "dog.jpg")
    plan = plan_for(tmp_path, [entry_for(a, "dog.jpg")])
    assert plan.renames == []
    assert plan.skipped[0].skip_reason == SKIP_UNCHANGED


def test_case_only_change_is_not_skipped(tmp_path: Path) -> None:
    a = make_file(tmp_path / "photo.jpg")
    plan = plan_for(tmp_path, [entry_for(a, "Photo.jpg")])
    assert len(plan.renames) == 1
    assert plan.renames[0].target_name == "Photo.jpg"
    assert error_codes(plan) == []


def test_limit_is_stable_and_in_report_order(tmp_path: Path) -> None:
    files = [make_file(tmp_path / f"img_{i}.jpg") for i in range(5)]
    entries = [entry_for(f, f"name-{i}.jpg") for i, f in enumerate(files)]
    plan = plan_for(tmp_path, entries, limit=2)
    assert [item.original_name for item in plan.renames] == ["img_0.jpg", "img_1.jpg"]
    over_limit = [
        item for item in plan.skipped if item.skip_reason == SKIP_OVER_LIMIT
    ]
    assert len(over_limit) == 3


def test_resolve_conflicts_numbers_duplicates(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg")
    b = make_file(tmp_path / "IMG_2.jpg")
    c = make_file(tmp_path / "IMG_3.jpg")
    make_file(tmp_path / "dog-in-snow-002.jpg")  # foreign file occupies -002
    entries = [
        entry_for(a, "dog-in-snow.jpg"),
        entry_for(b, "dog-in-snow.jpg"),
        entry_for(c, "dog-in-snow.jpg"),
    ]
    plan = plan_for(tmp_path, entries, resolve_conflicts=True)
    assert error_codes(plan) == []
    names = [item.target_name for item in plan.renames]
    assert names == ["dog-in-snow.jpg", "dog-in-snow-003.jpg", "dog-in-snow-004.jpg"]
    assert [item.conflict_resolved for item in plan.renames] == [False, True, True]


def test_resolve_conflicts_around_foreign_file(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg")
    make_file(tmp_path / "dog.jpg")  # foreign
    plan = plan_for(tmp_path, [entry_for(a, "dog.jpg")], resolve_conflicts=True)
    assert error_codes(plan) == []
    assert plan.renames[0].target_name == "dog-002.jpg"


def test_extension_case_preserved_in_plan(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.JPG")
    plan = plan_for(tmp_path, [entry_for(a, "dog-running.jpg")])
    assert plan.renames[0].final_path == str(tmp_path / "dog-running.JPG")


def test_without_resolve_conflicts_duplicates_are_errors(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg")
    b = make_file(tmp_path / "IMG_2.jpg")
    plan = plan_for(
        tmp_path, [entry_for(a, "dog.jpg"), entry_for(b, "dog.jpg")]
    )
    assert "DUPLICATE_TARGET" in error_codes(plan)
