from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image

from filesight.video_caption import VideoCaptionAggregator, analyze_frames


@dataclass
class FakeExtracted:
    index: int
    timestamp_seconds: float
    path: Optional[str]
    error: Optional[str] = None


class ScriptedCaptioner:
    """Returns a preset caption per frame path; never loads a model."""

    model_name = "fake"
    device = "cpu"

    def __init__(self, mapping: dict) -> None:
        self._mapping = mapping

    def caption(self, image: Image.Image) -> str:
        return self._mapping.get(getattr(image, "_fs_path", None), "a scene")


# --- Aggregator (pure) ---------------------------------------------------

def test_single_caption() -> None:
    assert VideoCaptionAggregator().aggregate(["a red car on a road"]) == (
        "a red car on a road"
    )


def test_similar_captions_pick_representative() -> None:
    result = VideoCaptionAggregator().aggregate(
        [
            "a dog running through snow",
            "a black dog playing in snow",
            "a dog running outdoors",
            "a black dog near trees",
        ]
    )
    # deterministic: the caption covering the most frequent words wins
    assert result == "a black dog playing in snow"


def test_repeated_object_dominates() -> None:
    result = VideoCaptionAggregator().aggregate(
        ["a cat on a sofa", "a cat sleeping", "a cat on a chair"]
    )
    assert "cat" in result


def test_captions_with_filler_words() -> None:
    # fillers do not derail selection; result is still a real caption
    result = VideoCaptionAggregator().aggregate(
        ["a photo of a boat on water", "a boat sailing on water"]
    )
    assert "boat" in result and "water" in result


def test_empty_captions_returns_none() -> None:
    assert VideoCaptionAggregator().aggregate([]) is None
    assert VideoCaptionAggregator().aggregate(["", "   "]) is None


def test_aggregation_is_stable() -> None:
    captions = ["a bird flying", "a bird on a branch", "a bird in the sky"]
    agg = VideoCaptionAggregator()
    assert agg.aggregate(captions) == agg.aggregate(captions)


# --- analyze_frames (integration with quality + captioner) ---------------

def _frame(tmp_path: Path, name: str, color) -> str:
    path = tmp_path / name
    Image.new("RGB", (32, 32), color).save(path)
    return str(path)


def _noisy_frame(tmp_path: Path, name: str, seed: int) -> str:
    import random

    rng = random.Random(seed)
    img = Image.new("RGB", (32, 32))
    img.putdata([
        (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        for _ in range(32 * 32)
    ])
    path = tmp_path / name
    img.save(path)
    return str(path)


class PathCaptioner:
    model_name = "fake"
    device = "cpu"

    def __init__(self, tmp_path: Path) -> None:
        self._tmp = tmp_path

    def caption(self, image: Image.Image) -> str:
        return "a colorful abstract scene"


def test_analyze_frames_partial_success(tmp_path: Path) -> None:
    frames = [
        FakeExtracted(1, 0.5, _frame(tmp_path, "black.jpg", (0, 0, 0))),  # too dark
        FakeExtracted(2, 1.5, _noisy_frame(tmp_path, "good1.png", 1)),   # usable
        FakeExtracted(3, 2.5, None, "extract failed"),                    # failed
    ]
    result = analyze_frames(frames, PathCaptioner(tmp_path))
    statuses = [f.status for f in result.frame_results]
    assert statuses == ["skipped", "success", "failed"]
    assert result.frame_results[0].skip_reason == "too_dark"
    assert result.usable_frames == 1
    assert result.analyzed_frames == 1
    assert result.aggregated_caption == "a colorful abstract scene"
    assert "partial_frame_analysis" in result.warnings


def test_analyze_frames_all_failed(tmp_path: Path) -> None:
    frames = [
        FakeExtracted(1, 0.5, None, "boom"),
        FakeExtracted(2, 1.5, _frame(tmp_path, "black.jpg", (0, 0, 0))),
    ]
    result = analyze_frames(frames, PathCaptioner(tmp_path))
    assert result.aggregated_caption is None
    assert result.analyzed_frames == 0


def test_analyze_frames_no_warning_when_all_usable(tmp_path: Path) -> None:
    frames = [
        FakeExtracted(1, 0.5, _noisy_frame(tmp_path, "a.png", 1)),
        FakeExtracted(2, 1.5, _noisy_frame(tmp_path, "b.png", 2)),
    ]
    result = analyze_frames(frames, PathCaptioner(tmp_path))
    assert result.analyzed_frames == 2
    assert result.warnings == []
