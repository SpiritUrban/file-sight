from pathlib import Path

import pytest

from filesight.video_frames import compute_timestamps, extract_frames


def test_two_second_video_positions_within_bounds() -> None:
    ts = compute_timestamps(2.0, 6)
    assert len(ts) == 6
    assert all(0 < t < 2.0 for t in ts)
    assert ts == sorted(ts)


def test_five_second_video() -> None:
    ts = compute_timestamps(5.0, 5)
    assert len(ts) == 5
    assert all(0 < t < 5.0 for t in ts)


def test_thirty_second_video_spread() -> None:
    ts = compute_timestamps(30.0, 6)
    assert len(ts) == 6
    # long-video sampling starts at 5% and ends at 95%
    assert ts[0] == pytest.approx(1.5, abs=0.01)
    assert ts[-1] == pytest.approx(28.5, abs=0.01)


def test_120_second_video() -> None:
    ts = compute_timestamps(120.0, 6)
    assert ts[0] == pytest.approx(6.0, abs=0.05)
    assert ts[-1] == pytest.approx(114.0, abs=0.05)
    assert all(t < 120.0 for t in ts)


def test_single_frame_is_near_middle() -> None:
    assert compute_timestamps(100.0, 1) == [pytest.approx(50.0, abs=0.1)]


def test_six_frames_matches_documented_example() -> None:
    ts = compute_timestamps(100.0, 6)
    assert ts == [5.0, 23.0, 41.0, 59.0, 77.0, 95.0]


def test_twenty_frames() -> None:
    ts = compute_timestamps(60.0, 20)
    assert len(ts) == 20
    assert all(0 < t < 60.0 for t in ts)
    assert ts == sorted(ts)


def test_never_uses_exact_zero_or_end() -> None:
    ts = compute_timestamps(10.0, 6)
    assert ts[0] > 0.0
    assert ts[-1] < 10.0


def test_positions_are_stable() -> None:
    assert compute_timestamps(42.0, 8) == compute_timestamps(42.0, 8)


def test_extract_frames_records_success_and_failure(tmp_path: Path, monkeypatch) -> None:
    import filesight.video_frames as vf

    calls = []

    def fake_extract_one(ffmpeg, video_path, timestamp, out_path):
        calls.append(timestamp)
        # succeed for the first two, fail for the third
        if len(calls) <= 2:
            Path(out_path).write_bytes(b"jpegdata")
            return None
        return "FFmpeg exit 1: boom"

    monkeypatch.setattr(vf, "_extract_one", fake_extract_one)
    results = extract_frames("ffmpeg", "video.mp4", [1.0, 2.0, 3.0], tmp_path)
    assert [r.path is not None for r in results] == [True, True, False]
    assert results[2].error and "boom" in results[2].error
    assert [r.index for r in results] == [1, 2, 3]


def test_extract_frames_treats_empty_output_as_failure(
    tmp_path: Path, monkeypatch
) -> None:
    import filesight.video_frames as vf

    def fake_extract_one(ffmpeg, video_path, timestamp, out_path):
        Path(out_path).write_bytes(b"")  # zero-byte file
        return None

    monkeypatch.setattr(vf, "_extract_one", fake_extract_one)
    results = extract_frames("ffmpeg", "v.mp4", [1.0], tmp_path)
    assert results[0].path is None
