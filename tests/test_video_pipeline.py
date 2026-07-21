from pathlib import Path

from PIL import Image

from filesight import video_pipeline
from filesight.models import VideoMetadata
from filesight.naming import NameAllocator
from filesight.temp_files import FrameWorkspace
from filesight.video_frames import ExtractedFrame
from filesight.video_probe import ProbeError

from helpers import make_file


class FixedCaptioner:
    model_name = "fake"
    device = "cpu"

    def caption(self, image: Image.Image) -> str:
        return "a black dog running through snow"


def meta(duration=10.0) -> VideoMetadata:
    return VideoMetadata(
        duration_seconds=duration,
        width=1920,
        height=1080,
        frame_rate=30.0,
        video_codec="h264",
        container="mp4",
        has_audio=True,
        rotation_degrees=0,
    )


def usable_frame(tmp_path: Path, index: int) -> ExtractedFrame:
    import random

    rng = random.Random(index)
    img = Image.new("RGB", (32, 32))
    img.putdata([
        (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        for _ in range(32 * 32)
    ])
    path = tmp_path / f"frame-{index}.png"
    img.save(path)
    return ExtractedFrame(index, float(index), str(path))


def run(tmp_path, monkeypatch, video_meta=None, frames=None, probe_error=None, **kwargs):
    v = make_file(tmp_path / "VID_1.MP4", b"fake-video-bytes")

    def fake_probe(path, ffprobe):
        if probe_error is not None:
            raise probe_error
        return video_meta or meta()

    monkeypatch.setattr(video_pipeline, "probe_video", fake_probe)
    monkeypatch.setattr(
        video_pipeline, "compute_timestamps", lambda d, n: [1.0, 2.0, 3.0][:n]
    )
    monkeypatch.setattr(
        video_pipeline,
        "extract_frames",
        lambda ffmpeg, path, ts, out_dir: frames if frames is not None else [],
    )
    with FrameWorkspace(base=tmp_path / "ws") as ws:
        entry = video_pipeline.process_video(
            v, FixedCaptioner(), NameAllocator(), "ffmpeg", "ffprobe", ws, **kwargs
        )
    return v, entry


def test_successful_video(tmp_path: Path, monkeypatch) -> None:
    frames = [usable_frame(tmp_path, 1), usable_frame(tmp_path, 2)]
    v, entry = run(tmp_path, monkeypatch, frames=frames, num_frames=2)
    assert entry.status == "success"
    assert entry.media_type == "video"
    assert entry.suggested_name == "black-dog-running-through-snow.MP4"
    assert entry.video_metadata.duration_seconds == 10.0
    assert entry.video_analysis.analyzed_frames >= 1
    assert entry.timings is not None


def test_long_video_skipped(tmp_path: Path, monkeypatch) -> None:
    v, entry = run(
        tmp_path, monkeypatch, video_meta=meta(duration=800.0), frames=[],
        max_duration=120,
    )
    assert entry.status == "skipped"
    assert entry.error.type == "video_too_long"
    assert entry.video_metadata is not None


def test_allow_long_videos(tmp_path: Path, monkeypatch) -> None:
    frames = [usable_frame(tmp_path, 1)]
    v, entry = run(
        tmp_path, monkeypatch, video_meta=meta(duration=800.0), frames=frames,
        max_duration=120, allow_long=True, num_frames=1,
    )
    assert entry.status == "success"


def test_no_usable_frames_fails(tmp_path: Path, monkeypatch) -> None:
    black = tmp_path / "black.png"
    Image.new("RGB", (32, 32), (0, 0, 0)).save(black)
    frames = [ExtractedFrame(1, 1.0, str(black))]
    v, entry = run(tmp_path, monkeypatch, frames=frames, num_frames=1)
    assert entry.status == "failed"
    assert entry.error.type == "NoUsableVideoFrames"


def test_no_video_stream_fails(tmp_path: Path, monkeypatch) -> None:
    v, entry = run(
        tmp_path, monkeypatch,
        probe_error=ProbeError("no video stream", "NoVideoStream"),
    )
    assert entry.status == "failed"
    assert entry.error.type == "NoVideoStream"


def test_temp_frames_cleaned_after_success(tmp_path: Path, monkeypatch) -> None:
    frames = [usable_frame(tmp_path, 1)]
    ws_base = tmp_path / "ws"
    v = make_file(tmp_path / "VID_1.MP4", b"x")
    monkeypatch.setattr(video_pipeline, "probe_video", lambda p, f: meta())
    monkeypatch.setattr(video_pipeline, "compute_timestamps", lambda d, n: [1.0])
    monkeypatch.setattr(
        video_pipeline, "extract_frames", lambda a, b, c, d: frames
    )
    with FrameWorkspace(base=ws_base) as ws:
        op_dir = ws.operation_dir
        video_pipeline.process_video(
            v, FixedCaptioner(), NameAllocator(), "ffmpeg", "ffprobe", ws, num_frames=1
        )
        # per-video dir removed right after processing
        video_dirs = list(ws.operation_dir.glob("video-*"))
        assert video_dirs == []
    # this run's operation tree is removed on context exit
    assert not op_dir.exists()
