import json
from pathlib import Path

from PIL import Image

from filesight.models import ModelInfo
from filesight.pipeline import process_files
from filesight.report import build_report, write_report


class FakeCaptioner:
    """Deterministic captioner for tests; never loads a real model."""

    model_name = "fake/captioner"
    device = "cpu"

    def __init__(self, caption: str = "a black dog in the snow") -> None:
        self._caption = caption

    def caption(self, image: Image.Image) -> str:
        return self._caption


def make_image(path: Path) -> Path:
    Image.new("RGB", (8, 8), color=(200, 30, 30)).save(path)
    return path


def test_pipeline_success_and_report_roundtrip(tmp_path: Path) -> None:
    files = [make_image(tmp_path / "IMG_0001.jpg"), make_image(tmp_path / "IMG_0002.jpg")]
    entries = process_files(files, FakeCaptioner())

    assert [e.status for e in entries] == ["success", "success"]
    assert entries[0].suggested_name == "black-dog-in-snow.jpg"
    assert entries[1].suggested_name == "black-dog-in-snow-002.jpg"

    report = build_report(
        source_directory=tmp_path,
        recursive=False,
        model=ModelInfo(provider="huggingface", name="fake/captioner", device="cpu"),
        entries=entries,
        discovered=len(files),
        duration_seconds=1.234,
    )
    output = tmp_path / "report.json"
    write_report(report, output)

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.4"
    assert data["recursive"] is False
    assert data["model"]["device"] == "cpu"
    assert data["summary"] == {
        "discovered": 2,
        "processed": 2,
        "failed": 0,
        "skipped": 0,
        "duration_seconds": 1.23,
    }
    assert data["files"][0]["media_type"] == "image"
    assert "video_metadata" not in data["files"][0]
    assert data["files"][0]["caption"] == "a black dog in the snow"
    assert data["files"][0]["error"] is None


def test_broken_file_does_not_stop_the_scan(tmp_path: Path) -> None:
    good = make_image(tmp_path / "good.png")
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"this is not an image at all")

    entries = process_files([broken, good], FakeCaptioner())

    assert entries[0].status == "failed"
    assert entries[0].caption is None
    assert entries[0].suggested_name is None
    assert entries[0].error is not None
    assert entries[0].error.type == "UnidentifiedImageError"

    assert entries[1].status == "success"
    assert entries[1].suggested_name == "black-dog-in-snow.png"

    report = build_report(
        source_directory=tmp_path,
        recursive=False,
        model=ModelInfo(provider="huggingface", name="fake/captioner", device="cpu"),
        entries=entries,
        discovered=2,
        duration_seconds=0.5,
    )
    assert report.summary.processed == 1
    assert report.summary.failed == 1

    data = report.to_dict()
    assert data["files"][0]["error"]["type"] == "UnidentifiedImageError"


def test_report_is_utf8_and_indented(tmp_path: Path) -> None:
    report = build_report(
        source_directory=tmp_path / "Фото",
        recursive=True,
        model=ModelInfo(provider="huggingface", name="fake/captioner", device="cpu"),
        entries=[],
        discovered=0,
        duration_seconds=0.0,
    )
    output = tmp_path / "report.json"
    write_report(report, output)
    text = output.read_text(encoding="utf-8")
    assert "Фото" in text  # not escaped to \uXXXX
    assert text.startswith("{\n  ")
