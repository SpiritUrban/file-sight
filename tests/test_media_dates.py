import os
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

from filesight.media_dates import (
    SOURCE_EXIF_DIGITIZED,
    SOURCE_EXIF_ORIGINAL,
    SOURCE_FS_CREATED,
    SOURCE_FS_MODIFIED,
    SOURCE_VIDEO_CREATION,
    date_parts,
    is_plausible,
    parse_video_creation_time,
    read_image_date,
    resolve_media_date,
)

TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME_DIGITIZED = 36868


def image_with_exif(path: Path, tags: dict[int, str]) -> Path:
    img = Image.new("RGB", (8, 8), (120, 60, 30))
    exif = img.getexif()
    for tag, value in tags.items():
        exif[tag] = value
    img.save(path, exif=exif)
    return path


def plain_image(path: Path) -> Path:
    Image.new("RGB", (8, 8), (10, 90, 200)).save(path)
    return path


def test_exif_datetime_original(tmp_path: Path) -> None:
    path = image_with_exif(
        tmp_path / "a.jpg", {TAG_DATETIME_ORIGINAL: "2026:01:14 15:42:10"}
    )
    moment, source = read_image_date(path)
    assert source == SOURCE_EXIF_ORIGINAL
    assert moment == datetime(2026, 1, 14, 15, 42, 10)


def test_exif_datetime_digitized_used_when_original_absent(tmp_path: Path) -> None:
    path = image_with_exif(
        tmp_path / "b.jpg", {TAG_DATETIME_DIGITIZED: "2025:03:02 08:00:00"}
    )
    moment, source = read_image_date(path)
    assert source == SOURCE_EXIF_DIGITIZED
    assert moment == datetime(2025, 3, 2, 8, 0, 0)


def test_original_wins_over_digitized(tmp_path: Path) -> None:
    path = image_with_exif(
        tmp_path / "c.jpg",
        {
            TAG_DATETIME_ORIGINAL: "2026:01:14 15:42:10",
            TAG_DATETIME_DIGITIZED: "2020:01:01 00:00:00",
        },
    )
    moment, source = read_image_date(path)
    assert source == SOURCE_EXIF_ORIGINAL
    assert moment.year == 2026


def test_filesystem_fallback_without_exif(tmp_path: Path) -> None:
    path = plain_image(tmp_path / "d.png")
    result = resolve_media_date(path, media_type="image")
    assert result.date_source in (SOURCE_FS_CREATED, SOURCE_FS_MODIFIED)
    assert result.captured_at is not None


def test_modified_time_fallback(tmp_path: Path) -> None:
    path = plain_image(tmp_path / "e.png")
    target = datetime(2024, 5, 17, 9, 30, 0).timestamp()
    os.utime(path, (target, target))
    result = resolve_media_date(path, media_type="image")
    assert result.captured_at is not None
    # whichever filesystem source is used, it must be a real date
    assert result.date_source in (SOURCE_FS_CREATED, SOURCE_FS_MODIFIED)


def test_video_creation_time(tmp_path: Path) -> None:
    path = tmp_path / "v.mp4"
    path.write_bytes(b"not really a video")
    result = resolve_media_date(
        path, media_type="video",
        video_tags={"creation_time": "2026-07-21T18:42:10.000000Z"},
    )
    assert result.date_source == SOURCE_VIDEO_CREATION
    assert result.captured_at.startswith("2026-07-21")


def test_video_without_creation_time_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "v2.mp4"
    path.write_bytes(b"x")
    result = resolve_media_date(path, media_type="video", video_tags={})
    assert result.date_source in (SOURCE_FS_CREATED, SOURCE_FS_MODIFIED)


def test_parse_video_creation_time_variants() -> None:
    assert parse_video_creation_time("2026-07-21T18:42:10.000000Z") is not None
    assert parse_video_creation_time("2026:07:21 18:42:10") is not None
    assert parse_video_creation_time("") is None
    assert parse_video_creation_time(None) is None
    assert parse_video_creation_time("garbage") is None


def test_naive_timestamp_stays_naive() -> None:
    moment = parse_video_creation_time("2026:07:21 18:42:10")
    assert moment.tzinfo is None


def test_implausible_dates_rejected() -> None:
    assert not is_plausible(datetime(1970, 1, 1))
    assert not is_plausible(datetime(1900, 1, 1))
    assert not is_plausible(datetime(2200, 1, 1))
    assert is_plausible(datetime(2026, 7, 21))


def test_epoch_exif_date_falls_back_with_warning(tmp_path: Path) -> None:
    path = image_with_exif(
        tmp_path / "f.jpg", {TAG_DATETIME_ORIGINAL: "1970:01:01 00:00:00"}
    )
    result = resolve_media_date(path, media_type="image")
    assert result.date_source != SOURCE_EXIF_ORIGINAL
    assert "implausible_metadata_date" in result.warnings


def test_far_future_video_date_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "g.mp4"
    path.write_bytes(b"x")
    result = resolve_media_date(
        path, media_type="video",
        video_tags={"creation_time": "2200-01-01T00:00:00Z"},
    )
    assert result.date_source != SOURCE_VIDEO_CREATION
    assert "implausible_metadata_date" in result.warnings


def test_malformed_exif_date_is_ignored(tmp_path: Path) -> None:
    path = image_with_exif(
        tmp_path / "h.jpg", {TAG_DATETIME_ORIGINAL: "not a date"}
    )
    moment, _ = read_image_date(path)
    assert moment is None


def test_date_source_always_reported(tmp_path: Path) -> None:
    path = plain_image(tmp_path / "i.png")
    result = resolve_media_date(path)
    assert isinstance(result.date_source, str) and result.date_source


def test_date_parts_rendering() -> None:
    parts = date_parts("2026-01-14T15:42:10", "%Y-%m-%d", "%H-%M-%S")
    assert parts["date"] == "2026-01-14"
    assert parts["time"] == "15-42-10"
    assert parts["year"] == "2026"
    assert parts["month"] == "01"
    assert parts["day"] == "14"


def test_date_parts_empty_for_missing_or_bad_input() -> None:
    assert date_parts(None, "%Y", "%H") == {}
    assert date_parts("nonsense", "%Y", "%H") == {}
