"""Tunable constants for FileSight. No magic numbers scattered in code."""

from __future__ import annotations

# Video analysis defaults
DEFAULT_MAX_VIDEO_DURATION = 120  # seconds
DEFAULT_VIDEO_FRAMES = 6
MIN_VIDEO_FRAMES = 1
MAX_VIDEO_FRAMES = 20

# External process timeouts (seconds)
FFPROBE_TIMEOUT_SECONDS = 30
FRAME_EXTRACTION_TIMEOUT_SECONDS = 60

# Short videos get a hand-picked spread biased toward the middle; longer
# videos are sampled evenly between these bounds.
SHORT_VIDEO_THRESHOLD_SECONDS = 5.0
SHORT_VIDEO_POSITIONS = (0.15, 0.35, 0.55, 0.75, 0.90)
LONG_VIDEO_START_FRACTION = 0.05
LONG_VIDEO_END_FRACTION = 0.95

# Frame quality heuristics (grayscale 0..255 space)
DARK_MEAN_THRESHOLD = 16.0
BRIGHT_MEAN_THRESHOLD = 240.0
LOW_VARIANCE_STDDEV_THRESHOLD = 6.0
# Two frames whose 8x8 dHash differ by <= this many bits are near-duplicates.
NEAR_DUPLICATE_HAMMING_THRESHOLD = 6

# Naming / template limits
MIN_FILENAME_LENGTH = 20
MAX_FILENAME_LENGTH_LIMIT = 240
DEFAULT_MAX_FILENAME_LENGTH = 80
DEFAULT_MAX_OBJECTS = 3
DEFAULT_MAX_CAPTION_WORDS = 8
DEFAULT_INDEX_PADDING = 3
MAX_INDEX_PADDING = 10
