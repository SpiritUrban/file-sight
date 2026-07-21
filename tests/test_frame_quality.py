import random
from pathlib import Path

from PIL import Image

from filesight.frame_quality import (
    DECODE_FAILED,
    LOW_VARIANCE,
    NEAR_DUPLICATE,
    TOO_BRIGHT,
    TOO_DARK,
    assess_frame,
    difference_hash,
    hamming_distance,
)


def solid(path: Path, color, size=(64, 64)) -> str:
    Image.new("RGB", size, color).save(path)
    return str(path)


def noisy(path: Path, seed: int, size=(64, 64)) -> str:
    rng = random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata([
        (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        for _ in range(size[0] * size[1])
    ])
    img.save(path)
    return str(path)


def test_black_frame_rejected(tmp_path: Path) -> None:
    result = assess_frame(solid(tmp_path / "b.jpg", (0, 0, 0)))
    assert not result.usable
    assert result.skip_reason == TOO_DARK


def test_white_frame_rejected(tmp_path: Path) -> None:
    result = assess_frame(solid(tmp_path / "w.png", (255, 255, 255)))
    assert not result.usable
    assert result.skip_reason == TOO_BRIGHT


def test_low_variance_frame_rejected(tmp_path: Path) -> None:
    result = assess_frame(solid(tmp_path / "g.png", (128, 128, 128)))
    assert not result.usable
    assert result.skip_reason == LOW_VARIANCE


def test_normal_frame_is_usable(tmp_path: Path) -> None:
    result = assess_frame(noisy(tmp_path / "n.png", seed=1))
    assert result.usable
    assert result.skip_reason is None
    assert result.dhash is not None


def test_two_identical_frames_are_near_duplicates(tmp_path: Path) -> None:
    first = assess_frame(noisy(tmp_path / "a.png", seed=7))
    second = assess_frame(noisy(tmp_path / "b.png", seed=7), previous_hash=first.dhash)
    assert first.usable
    assert not second.usable
    assert second.skip_reason == NEAR_DUPLICATE


def test_two_different_frames_are_not_duplicates(tmp_path: Path) -> None:
    first = assess_frame(noisy(tmp_path / "a.png", seed=1))
    second = assess_frame(noisy(tmp_path / "b.png", seed=999), previous_hash=first.dhash)
    assert first.usable
    assert second.usable


def test_corrupt_image_decode_failed(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"this is not an image")
    result = assess_frame(str(broken))
    assert not result.usable
    assert result.skip_reason == DECODE_FAILED


def test_hamming_distance_basic() -> None:
    assert hamming_distance(0b1010, 0b1000) == 1
    assert hamming_distance(0xFF, 0x00) == 8


def test_difference_hash_is_stable(tmp_path: Path) -> None:
    path = noisy(tmp_path / "x.png", seed=5)
    with Image.open(path) as img:
        assert difference_hash(img) == difference_hash(img)
