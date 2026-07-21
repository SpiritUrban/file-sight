import json
from pathlib import Path

from filesight.models import (
    FileEntry,
    ModelInfo,
    Timings,
    VideoAnalysis,
    VideoFrameResult,
    VideoMetadata,
)
from filesight.rename_plan import build_plan
from filesight.report import build_report, write_report

from helpers import make_file


def video_entry(path: Path) -> FileEntry:
    stat = path.stat()
    from filesight.models import SourceMetadata

    return FileEntry(
        original_path=str(path),
        original_name=path.name,
        extension=path.suffix,
        status="success",
        media_type="video",
        caption="a black dog running through snow",
        suggested_name="black-dog-running-through-snow" + path.suffix,
        processing_time_ms=18420,
        source_metadata=SourceMetadata(stat.st_size, stat.st_mtime_ns),
        video_metadata=VideoMetadata(
            duration_seconds=18.42,
            width=1920,
            height=1080,
            frame_rate=30.0,
            video_codec="h264",
            container="mov,mp4,m4a,3gp,3g2,mj2",
            has_audio=True,
            rotation_degrees=0,
        ),
        video_analysis=VideoAnalysis(
            requested_frames=6,
            extracted_frames=6,
            usable_frames=4,
            analyzed_frames=4,
            frames=[
                VideoFrameResult(1, 0.92, "skipped", skip_reason="too_dark"),
                VideoFrameResult(2, 4.23, "success", caption="a black dog"),
            ],
            warnings=[],
        ),
        timings=Timings(120, 940, 14320, 4, 15420),
    )


def image_entry(path: Path) -> FileEntry:
    return FileEntry(
        original_path=str(path),
        original_name=path.name,
        extension=path.suffix,
        status="success",
        media_type="image",
        caption="a cat",
        suggested_name="cat" + path.suffix,
        processing_time_ms=10,
    )


def test_video_entry_serializes(tmp_path: Path) -> None:
    v = make_file(tmp_path / "VID_1.MP4")
    report = build_report(
        source_directory=tmp_path,
        recursive=False,
        model=ModelInfo("huggingface", "fake", "cpu"),
        entries=[video_entry(v)],
        discovered=1,
        duration_seconds=18.42,
        videos_enabled=True,
    )
    out = tmp_path / "report.json"
    write_report(report, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    entry = data["files"][0]
    assert entry["media_type"] == "video"
    assert entry["video_metadata"]["duration_seconds"] == 18.42
    assert entry["video_metadata"]["frame_rate"] == 30.0
    assert entry["video_analysis"]["usable_frames"] == 4
    assert entry["video_analysis"]["frames"][0]["skip_reason"] == "too_dark"
    assert entry["timings"]["total_ms"] == 15420


def test_mixed_report_summary(tmp_path: Path) -> None:
    img = make_file(tmp_path / "pic.jpg")
    vid = make_file(tmp_path / "VID_1.MP4")
    report = build_report(
        source_directory=tmp_path,
        recursive=False,
        model=ModelInfo("huggingface", "fake", "cpu"),
        entries=[image_entry(img), video_entry(vid)],
        discovered=2,
        duration_seconds=20.0,
        videos_enabled=True,
    )
    out = tmp_path / "report.json"
    write_report(report, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["images"]["processed"] == 1
    assert data["summary"]["videos"]["processed"] == 1
    # image entry stays clean (no video keys)
    image = next(e for e in data["files"] if e["media_type"] == "image")
    assert "video_metadata" not in image


def test_old_image_report_without_media_type_still_validates(tmp_path: Path) -> None:
    # simulate an iteration-1/2 report entry: no media_type key
    a = make_file(tmp_path / "IMG_1.jpg")
    report = {
        "schema_version": "1.1",
        "created_at": "2026-07-21T00:00:00Z",
        "source_directory": str(tmp_path),
        "recursive": False,
        "model": {"provider": "huggingface", "name": "fake", "device": "cpu"},
        "summary": {"discovered": 1, "processed": 1, "failed": 0, "duration_seconds": 1},
        "files": [
            {
                "original_path": str(a),
                "original_name": a.name,
                "extension": ".jpg",
                "status": "success",
                "caption": "a cat",
                "suggested_name": "cat.jpg",
                "processing_time_ms": 5,
                "error": None,
            }
        ],
    }
    plan = build_plan(report, tmp_path / "report.json")
    assert not plan.errors
    assert len(plan.renames) == 1


def test_skipped_video_entry_is_not_renamed(tmp_path: Path) -> None:
    v = make_file(tmp_path / "long.mp4")
    report = {
        "schema_version": "1.2",
        "created_at": "2026-07-21T00:00:00Z",
        "source_directory": str(tmp_path),
        "recursive": False,
        "model": {"provider": "huggingface", "name": "fake", "device": "cpu"},
        "summary": {"discovered": 1, "processed": 0, "failed": 0, "duration_seconds": 1},
        "files": [
            {
                "original_path": str(v),
                "original_name": v.name,
                "extension": ".mp4",
                "status": "skipped",
                "media_type": "video",
                "caption": None,
                "suggested_name": None,
                "processing_time_ms": 5,
                "error": {"type": "video_too_long", "message": "too long"},
            }
        ],
    }
    plan = build_plan(report, tmp_path / "report.json")
    assert plan.renames == []
    assert plan.skipped[0].skip_reason == "report status is skipped"
