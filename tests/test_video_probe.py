import json
import os
import subprocess

import pytest

from filesight import video_probe
from filesight.video_probe import (
    FFmpegNotFound,
    ProbeError,
    parse_probe_output,
    probe_video,
    resolve_tools,
)


def probe_json(**stream_over):
    video_stream = {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30/1",
        "duration": "18.42",
    }
    video_stream.update(stream_over)
    return {
        "streams": [video_stream, {"codec_type": "audio", "codec_name": "aac"}],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "18.42"},
    }


def test_parse_valid_json() -> None:
    meta = parse_probe_output(probe_json())
    assert meta.duration_seconds == 18.42
    assert meta.width == 1920
    assert meta.height == 1080
    assert meta.frame_rate == 30.0
    assert meta.video_codec == "h264"
    assert meta.has_audio is True
    assert meta.rotation_degrees == 0


def test_video_with_audio_flag() -> None:
    assert parse_probe_output(probe_json()).has_audio is True


def test_video_without_audio() -> None:
    data = probe_json()
    data["streams"] = [data["streams"][0]]  # drop the audio stream
    assert parse_probe_output(data).has_audio is False


def test_rotation_from_tags() -> None:
    meta = parse_probe_output(probe_json(tags={"rotate": "90"}))
    assert meta.rotation_degrees == 90


def test_rotation_from_side_data() -> None:
    meta = parse_probe_output(
        probe_json(side_data_list=[{"rotation": -90}])
    )
    assert meta.rotation_degrees == 270  # normalized into [0, 360)


def test_fractional_frame_rate() -> None:
    meta = parse_probe_output(probe_json(avg_frame_rate="30000/1001"))
    assert meta.frame_rate == pytest.approx(29.97, abs=0.01)


def test_duration_falls_back_to_format() -> None:
    data = probe_json()
    del data["streams"][0]["duration"]  # only format has it
    assert parse_probe_output(data).duration_seconds == 18.42


def test_no_video_stream() -> None:
    data = {"streams": [{"codec_type": "audio"}], "format": {"duration": "5"}}
    with pytest.raises(ProbeError) as exc:
        parse_probe_output(data)
    assert exc.value.error_type == "NoVideoStream"


def test_zero_duration() -> None:
    with pytest.raises(ProbeError) as exc:
        parse_probe_output(probe_json(duration="0"))
    assert exc.value.error_type == "ZeroDuration"


def test_unknown_duration() -> None:
    data = probe_json()
    del data["streams"][0]["duration"]
    del data["format"]["duration"]
    with pytest.raises(ProbeError) as exc:
        parse_probe_output(data)
    assert exc.value.error_type == "UnknownDuration"


def _fake_run(stdout=b"", returncode=0, raise_exc=None):
    def runner(*args, **kwargs):
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(
            args, returncode=returncode, stdout=stdout, stderr=b"boom"
        )

    return runner


def test_probe_video_success(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", _fake_run(stdout=json.dumps(probe_json()).encode())
    )
    meta = probe_video("x.mp4", "ffprobe")
    assert meta.duration_seconds == 18.42


def test_probe_corrupt_json(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=b"{not json"))
    with pytest.raises(ProbeError):
        probe_video("x.mp4", "ffprobe")


def test_probe_nonzero_exit(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1))
    with pytest.raises(ProbeError) as exc:
        probe_video("x.mp4", "ffprobe")
    assert exc.value.error_type == "ProbeFailed"


def test_probe_timeout(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(raise_exc=subprocess.TimeoutExpired(cmd="ffprobe", timeout=30)),
    )
    with pytest.raises(ProbeError) as exc:
        probe_video("x.mp4", "ffprobe")
    assert exc.value.error_type == "ProbeTimeout"


def test_resolve_tools_missing(monkeypatch) -> None:
    # also hide any FFmpeg unpacked into the project folder
    monkeypatch.setattr(video_probe, "_candidate_roots", lambda: [])
    monkeypatch.setattr(video_probe.shutil, "which", lambda name: None)
    with pytest.raises(FFmpegNotFound):
        resolve_tools()


def test_resolve_tools_explicit_bad_path(monkeypatch) -> None:
    monkeypatch.setattr(video_probe.shutil, "which", lambda name: None)
    with pytest.raises(FFmpegNotFound):
        resolve_tools(ffmpeg_path="C:\\nope\\ffmpeg.exe")


def test_finds_an_unpacked_ffmpeg_build_in_the_project(tmp_path) -> None:
    """Dropping an FFmpeg release into the folder is enough."""
    from filesight.video_probe import find_bundled_tool

    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bin_dir = tmp_path / "ffmpeg-8.1.2-essentials_build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / name).write_bytes(b"stub")

    found = find_bundled_tool("ffmpeg", roots=[tmp_path])
    assert found == str(bin_dir / name)


def test_finds_a_bare_executable_in_the_project(tmp_path) -> None:
    from filesight.video_probe import find_bundled_tool

    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    (tmp_path / name).write_bytes(b"stub")
    assert find_bundled_tool("ffprobe", roots=[tmp_path]) == str(tmp_path / name)


def test_finds_a_flat_ffmpeg_folder(tmp_path) -> None:
    from filesight.video_probe import find_bundled_tool

    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    folder = tmp_path / "ffmpeg"
    folder.mkdir()
    (folder / name).write_bytes(b"stub")
    assert find_bundled_tool("ffmpeg", roots=[tmp_path]) == str(folder / name)


def test_no_bundled_tool_returns_none(tmp_path) -> None:
    from filesight.video_probe import find_bundled_tool

    assert find_bundled_tool("ffmpeg", roots=[tmp_path]) is None


def test_bundled_tool_is_preferred_over_path(tmp_path, monkeypatch) -> None:
    """A deliberately placed build beats whatever is on PATH."""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bin_dir = tmp_path / "ffmpeg-build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / name).write_bytes(b"stub")

    monkeypatch.setattr(
        video_probe, "_candidate_roots", lambda: [tmp_path]
    )
    monkeypatch.setattr(
        video_probe.shutil, "which", lambda _: "C:\\system\\ffmpeg.exe"
    )
    assert video_probe._resolve_one("ffmpeg", None) == str(bin_dir / name)


def test_explicit_path_still_wins_over_bundled(tmp_path, monkeypatch) -> None:
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bundled_dir = tmp_path / "ffmpeg-build" / "bin"
    bundled_dir.mkdir(parents=True)
    (bundled_dir / name).write_bytes(b"stub")
    chosen = tmp_path / "chosen.exe"
    chosen.write_bytes(b"stub")

    monkeypatch.setattr(video_probe, "_candidate_roots", lambda: [tmp_path])
    assert video_probe._resolve_one("ffmpeg", str(chosen)) == str(chosen)


def test_resolve_tools_from_path(monkeypatch) -> None:
    monkeypatch.setattr(video_probe, "_candidate_roots", lambda: [])
    monkeypatch.setattr(
        video_probe.shutil, "which", lambda name: f"C:\\bin\\{name}.exe"
    )
    tools = resolve_tools()
    assert tools.ffmpeg == "C:\\bin\\ffmpeg.exe"
    assert tools.ffprobe == "C:\\bin\\ffprobe.exe"
