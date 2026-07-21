import json
import sys
from pathlib import Path

from filesight.config import default_config
from filesight.profiles import built_in_profile
from filesight.report_transform import regenerate_suggestions, write_report_dict

from helpers import make_file


def old_report(tmp_path: Path, entries: list[dict], schema="1.1") -> dict:
    return {
        "schema_version": schema,
        "created_at": "2026-07-21T00:00:00Z",
        "source_directory": str(tmp_path),
        "recursive": False,
        "model": {"provider": "huggingface", "name": "fake", "device": "cpu"},
        "summary": {"discovered": len(entries), "processed": len(entries),
                    "failed": 0, "duration_seconds": 1.0},
        "files": entries,
    }


def entry(path: Path, caption, status="success", **extra) -> dict:
    data = {
        "original_path": str(path),
        "original_name": path.name,
        "extension": path.suffix,
        "status": status,
        "caption": caption,
        "suggested_name": "old-name" + path.suffix,
        "processing_time_ms": 5,
        "error": None,
    }
    data.update(extra)
    return data


def test_old_report_without_features_gets_them(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_1.jpg")
    report = old_report(tmp_path, [entry(a, "a black dog running through snow")])
    updated, changes = regenerate_suggestions(report, built_in_profile("default"))

    new_entry = updated["files"][0]
    assert new_entry["features"]["subject"] == "black dog"
    assert new_entry["classification"]["category"] == "animals"
    assert new_entry["naming"]["template"] == "{subject}-{action}-{location}"
    assert new_entry["suggested_name"] == "black-dog-running-snow.jpg"
    assert changes[0].changed


def test_old_report_without_media_type_treated_as_image(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_2.jpg")
    report = old_report(tmp_path, [entry(a, "a red car")], schema="1.0")
    updated, _ = regenerate_suggestions(report, built_in_profile("default"))
    assert updated["files"][0]["classification"]["category"] == "vehicles"


def test_mixed_new_report(tmp_path: Path) -> None:
    img = make_file(tmp_path / "a.jpg")
    vid = make_file(tmp_path / "b.mp4")
    report = old_report(
        tmp_path,
        [
            entry(img, "a woman standing near a building", media_type="image"),
            entry(vid, "a black dog running", media_type="video"),
        ],
        schema="1.2",
    )
    updated, changes = regenerate_suggestions(report, built_in_profile("default"))
    assert updated["files"][0]["classification"]["category"] == "people"
    assert updated["files"][1]["classification"]["category"] == "animals"
    assert all(c.changed for c in changes)


def test_regeneration_with_a_different_profile(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_3.jpg")
    report = old_report(tmp_path, [entry(a, "a black dog running through snow")])
    compact, _ = regenerate_suggestions(report, built_in_profile("compact"))
    assert compact["files"][0]["suggested_name"] == "black-dog-running.jpg"


def test_naming_configuration_recorded(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_4.jpg")
    report = old_report(tmp_path, [entry(a, "a cat")])
    updated, _ = regenerate_suggestions(
        report, built_in_profile("photos"), config=default_config()
    )
    naming_config = updated["naming_configuration"]
    assert naming_config["profile"] == "photos"
    assert naming_config["source"] == "built-in"
    assert updated["schema_version"] == "1.3"


def test_failed_entries_keep_their_data(tmp_path: Path) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"x")
    report = old_report(
        tmp_path,
        [
            {
                "original_path": str(broken),
                "original_name": broken.name,
                "extension": ".png",
                "status": "failed",
                "caption": None,
                "suggested_name": None,
                "processing_time_ms": 3,
                "error": {"type": "UnidentifiedImageError", "message": "bad"},
            }
        ],
    )
    updated, changes = regenerate_suggestions(report, built_in_profile("default"))
    result = updated["files"][0]
    assert result["status"] == "failed"
    assert result["suggested_name"] is None
    assert result["error"]["type"] == "UnidentifiedImageError"
    assert "features" not in result
    assert changes[0].skipped_reason


def test_entry_without_caption_is_skipped(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_5.jpg")
    report = old_report(tmp_path, [entry(a, None)])
    _, changes = regenerate_suggestions(report, built_in_profile("default"))
    assert changes[0].skipped_reason == "no caption"


def test_captions_are_preserved(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_6.jpg")
    caption = "a black dog running through snow"
    report = old_report(tmp_path, [entry(a, caption)])
    updated, _ = regenerate_suggestions(report, built_in_profile("compact"))
    assert updated["files"][0]["caption"] == caption


def test_input_report_is_not_mutated(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_7.jpg")
    report = old_report(tmp_path, [entry(a, "a cat on a sofa")])
    before = json.dumps(report, sort_keys=True)
    regenerate_suggestions(report, built_in_profile("photos"))
    assert json.dumps(report, sort_keys=True) == before


def test_date_falls_back_to_source_metadata(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_8.jpg")
    stat = a.stat()
    report = old_report(
        tmp_path,
        [
            entry(
                a, "a black dog",
                source_metadata={"size_bytes": stat.st_size,
                                 "modified_at_ns": stat.st_mtime_ns},
            )
        ],
    )
    updated, _ = regenerate_suggestions(report, built_in_profile("photos"))
    # the photos template starts with {date}, so a date must have resolved
    assert updated["files"][0]["suggested_name"][:4].isdigit()


def test_no_date_available_drops_the_segment(tmp_path: Path) -> None:
    a = make_file(tmp_path / "IMG_9.jpg")
    report = old_report(tmp_path, [entry(a, "a black dog")])
    updated, _ = regenerate_suggestions(report, built_in_profile("photos"))
    name = updated["files"][0]["suggested_name"]
    assert not name[:4].isdigit()  # no date segment, no dangling separator
    assert not name.startswith("-")


def test_write_report_dict_is_utf8(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    write_report_dict({"schema_version": "1.3", "note": "Фото"}, target)
    assert "Фото" in target.read_text(encoding="utf-8")


def test_transform_never_imports_torch(tmp_path: Path) -> None:
    # regenerating names must not pull in the vision stack
    a = make_file(tmp_path / "IMG_10.jpg")
    report = old_report(tmp_path, [entry(a, "a black dog running")])
    regenerate_suggestions(report, built_in_profile("default"))
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
