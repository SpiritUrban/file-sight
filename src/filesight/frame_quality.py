"""Cheap, model-free heuristics to drop useless or duplicate frames.

Keeps the captioner from wasting time on black/blank/near-identical
frames. No neural network, no heavy blur detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PIL import Image, UnidentifiedImageError

from filesight.constants import (
    BRIGHT_MEAN_THRESHOLD,
    DARK_MEAN_THRESHOLD,
    LOW_VARIANCE_STDDEV_THRESHOLD,
    NEAR_DUPLICATE_HAMMING_THRESHOLD,
)

# Skip reason codes
TOO_DARK = "too_dark"
TOO_BRIGHT = "too_bright"
LOW_VARIANCE = "low_variance"
NEAR_DUPLICATE = "near_duplicate"
DECODE_FAILED = "decode_failed"


@dataclass
class FrameQuality:
    usable: bool
    skip_reason: Optional[str] = None
    dhash: Optional[int] = None


def _mean_std(gray: Image.Image) -> tuple[float, float]:
    pixels = gray.tobytes()  # one byte per pixel in mode "L"
    count = len(pixels)
    if count == 0:
        return 0.0, 0.0
    mean = sum(pixels) / count
    variance = sum((p - mean) ** 2 for p in pixels) / count
    return mean, variance**0.5


def difference_hash(image: Image.Image, size: int = 8) -> int:
    """Row-wise difference hash: (size x size) bits packed into an int."""
    small = image.convert("L").resize((size + 1, size), Image.BILINEAR)
    pixels = small.tobytes()
    bits = 0
    for row in range(size):
        base = row * (size + 1)
        for col in range(size):
            left = pixels[base + col]
            right = pixels[base + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def assess_frame(path: str, previous_hash: Optional[int] = None) -> FrameQuality:
    """Judge one extracted frame; compare against the previous kept frame."""
    try:
        with Image.open(path) as img:
            img.load()
            rgb = img.convert("RGB")
    except (UnidentifiedImageError, OSError):
        return FrameQuality(usable=False, skip_reason=DECODE_FAILED)

    gray = rgb.convert("L")
    mean, stddev = _mean_std(gray)
    dhash = difference_hash(rgb)

    if mean <= DARK_MEAN_THRESHOLD:
        return FrameQuality(False, TOO_DARK, dhash)
    if mean >= BRIGHT_MEAN_THRESHOLD:
        return FrameQuality(False, TOO_BRIGHT, dhash)
    if stddev <= LOW_VARIANCE_STDDEV_THRESHOLD:
        return FrameQuality(False, LOW_VARIANCE, dhash)
    if (
        previous_hash is not None
        and hamming_distance(dhash, previous_hash)
        <= NEAR_DUPLICATE_HAMMING_THRESHOLD
    ):
        return FrameQuality(False, NEAR_DUPLICATE, dhash)

    return FrameQuality(usable=True, dhash=dhash)
