from pathlib import Path

from typer.testing import CliRunner

from filesight.cli import app

from helpers import make_file

runner = CliRunner()


def test_images_only_and_videos_only_conflict(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["scan", str(tmp_path), "--images-only", "--videos-only"]
    )
    assert result.exit_code == 2
    assert "cannot be combined" in result.output


def test_images_only_and_include_videos_conflict(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["scan", str(tmp_path), "--images-only", "--include-videos"]
    )
    assert result.exit_code == 2


def test_invalid_video_frames_low(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--video-frames", "0"])
    assert result.exit_code == 2
    assert "video-frames" in result.output


def test_invalid_video_frames_high(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--video-frames", "50"])
    assert result.exit_code == 2


def test_include_videos_empty_folder_ok(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--include-videos"])
    assert result.exit_code == 0
    assert "Videos: enabled" in result.output


def test_default_scan_has_videos_disabled(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0
    assert "Videos: disabled" in result.output


def test_max_video_duration_and_allow_long_parse(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "scan",
            str(tmp_path),
            "--include-videos",
            "--max-video-duration",
            "180",
            "--allow-long-videos",
        ],
    )
    assert result.exit_code == 0
    assert "Maximum video duration: 180 seconds" in result.output


def test_videos_only_with_bad_ffmpeg_path(tmp_path: Path) -> None:
    make_file(tmp_path / "clip.mp4")  # a video to trigger ffmpeg resolution
    result = runner.invoke(
        app,
        [
            "scan",
            str(tmp_path),
            "--videos-only",
            "--ffmpeg-path",
            "C:\\definitely\\missing\\ffmpeg.exe",
            "--ffprobe-path",
            "C:\\definitely\\missing\\ffprobe.exe",
        ],
    )
    assert result.exit_code == 2
    assert "not found" in result.output.lower()


def test_bad_language_still_rejected(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path), "--language", "de"])
    assert result.exit_code == 2
