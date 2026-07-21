import os
import time
from pathlib import Path

import pytest

from filesight.rename_plan import build_plan
from filesight.report import ReportLoadError, load_report_dict
from filesight.report import write_report  # noqa: F401  (import sanity)

from helpers import entry_for, error_codes, make_file, report_dict


def plan_for(tmp_path: Path, entries: list[dict], **kwargs):
    report = report_dict(entries)
    return build_plan(report, tmp_path / "report.json", **kwargs)


def test_valid_report_has_no_errors(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg")
    b = make_file(tmp_path / "IMG_2.png")
    plan = plan_for(
        tmp_path,
        [entry_for(a, "dog-in-snow.jpg"), entry_for(b, "cat-on-sofa.png")],
    )
    assert error_codes(plan) == []
    assert len(plan.renames) == 2


def test_missing_source_file(tmp_path: Path) -> None:
    ghost = tmp_path / "missing.jpg"
    plan = plan_for(tmp_path, [entry_for(ghost, "dog.jpg", with_metadata=False)])
    assert "SOURCE_MISSING" in error_codes(plan)
    assert plan.renames == []


def test_forbidden_characters(tmp_path: Path) -> None:
    a = make_file(tmp_path / "a.jpg")
    plan = plan_for(tmp_path, [entry_for(a, "dog:in*snow.jpg")])
    assert "INVALID_NAME" in error_codes(plan)


@pytest.mark.parametrize("bad", ["CON.jpg", "nul.jpg", "com3.jpg", "LPT9.jpg"])
def test_reserved_windows_names(tmp_path: Path, bad: str) -> None:
    a = make_file(tmp_path / "a.jpg")
    plan = plan_for(tmp_path, [entry_for(a, bad)])
    assert "RESERVED_NAME" in error_codes(plan)


@pytest.mark.parametrize("bad", ["dog. .jpg. ", "dog.jpg ", "..", ". "])
def test_trailing_dots_and_spaces(tmp_path: Path, bad: str) -> None:
    a = make_file(tmp_path / "a.jpg")
    codes = error_codes(plan_for(tmp_path, [entry_for(a, bad)]))
    assert codes  # rejected one way or another
    assert "INVALID_NAME" in codes or "NAME_IS_PATH" in codes


@pytest.mark.parametrize(
    "bad",
    [
        "..\\other-folder\\file.jpg",
        "folder\\file.jpg",
        "folder/file.jpg",
        "C:\\other\\file.jpg",
        "/file.jpg",
    ],
)
def test_path_traversal_and_moves_rejected(tmp_path: Path, bad: str) -> None:
    a = make_file(tmp_path / "a.jpg")
    codes = error_codes(plan_for(tmp_path, [entry_for(a, bad)]))
    assert "NAME_IS_PATH" in codes


def test_extension_change_rejected(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.JPG")
    plan = plan_for(tmp_path, [entry_for(a, "dog-running.png")])
    assert "EXTENSION_CHANGED" in error_codes(plan)


def test_extension_case_is_preserved_from_original(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.JPG")
    plan = plan_for(tmp_path, [entry_for(a, "dog-running.jpg")])
    assert error_codes(plan) == []
    assert plan.renames[0].target_name == "dog-running.JPG"


def test_duplicate_targets(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.jpg")
    b = make_file(tmp_path / "IMG_002.jpg")
    plan = plan_for(
        tmp_path,
        [entry_for(a, "family-at-lake.jpg"), entry_for(b, "family-at-lake.jpg")],
    )
    assert "DUPLICATE_TARGET" in error_codes(plan)


def test_target_occupied_by_foreign_file(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.jpg")
    make_file(tmp_path / "dog.jpg")  # foreign file, not in the report
    plan = plan_for(tmp_path, [entry_for(a, "dog.jpg")])
    assert "TARGET_ALREADY_EXISTS" in error_codes(plan)


def test_duplicate_source_entries(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.jpg")
    plan = plan_for(tmp_path, [entry_for(a, "one.jpg"), entry_for(a, "two.jpg")])
    assert "DUPLICATE_SOURCE" in error_codes(plan)
    assert len(plan.renames) == 1


def test_old_schema_without_metadata_warns_but_does_not_block(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.jpg")
    report = report_dict(
        [entry_for(a, "dog.jpg", with_metadata=False)], schema_version="1.0"
    )
    plan = build_plan(report, tmp_path / "report.json")
    assert error_codes(plan) == []
    assert any(w.code == "NO_METADATA" for w in plan.warnings)
    assert len(plan.renames) == 1


def test_report_survives_a_javascript_json_round_trip(tmp_path: Path) -> None:
    """The desktop UI parses the report in JS, where numbers are doubles.

    A nanosecond mtime (~1.8e18) exceeds JS's exact-integer range and comes
    back rounded. An untouched file must not be reported as modified.
    """
    a = make_file(tmp_path / "IMG_1.jpg")
    entry = entry_for(a, "dog.jpg")
    exact = entry["source_metadata"]["modified_at_ns"]

    # float() reproduces exactly what JSON.parse gives a JS Number
    rounded = int(float(exact))
    entry["source_metadata"]["modified_at_ns"] = rounded

    plan = plan_for(tmp_path, [entry])
    assert "SOURCE_MODIFIED" not in error_codes(plan)
    assert len(plan.renames) == 1


def test_a_real_edit_is_still_detected_despite_the_tolerance(tmp_path: Path) -> None:
    from filesight.validation import MTIME_TOLERANCE_NS

    a = make_file(tmp_path / "IMG_1.jpg")
    entry = entry_for(a, "dog.jpg")
    # far beyond rounding, well inside what a real edit looks like
    entry["source_metadata"]["modified_at_ns"] -= MTIME_TOLERANCE_NS * 1000

    plan = plan_for(tmp_path, [entry])
    assert "SOURCE_MODIFIED" in error_codes(plan)


def test_a_size_change_is_never_tolerated(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg", b"original")
    entry = entry_for(a, "dog.jpg")
    a.write_bytes(b"different length content")
    os.utime(a, ns=(entry["source_metadata"]["modified_at_ns"],
                    entry["source_metadata"]["modified_at_ns"]))

    plan = plan_for(tmp_path, [entry])
    assert "SOURCE_MODIFIED" in error_codes(plan)


def test_modified_source_is_blocked(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.jpg")
    entry = entry_for(a, "dog.jpg")  # captures current metadata
    a.write_bytes(b"changed after the scan!")
    os.utime(a, ns=(time.time_ns(), time.time_ns()))
    plan = plan_for(tmp_path, [entry])
    assert "SOURCE_MODIFIED" in error_codes(plan)


def test_unsupported_schema_version_is_fatal(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    import json

    report_path.write_text(
        json.dumps(report_dict([], schema_version="99.0")), encoding="utf-8"
    )
    with pytest.raises(ReportLoadError):
        load_report_dict(report_path)


def test_invalid_json_is_fatal(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReportLoadError):
        load_report_dict(report_path)


def test_missing_suggested_name_for_success_entry(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_001.jpg")
    plan = plan_for(tmp_path, [entry_for(a, None)])
    assert "MISSING_SUGGESTED_NAME" in error_codes(plan)
