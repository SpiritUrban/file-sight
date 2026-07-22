"""Turning model captions into safe, readable file names.

This module is pure string processing and has no dependency on the
neural network, so it is fully unit-testable.
"""

from __future__ import annotations

import re

MAX_NAME_LENGTH = 80  # characters, excluding the extension
MAX_WORDS = 8
FALLBACK_NAME = "untitled"

# Leading filler phrases models like to produce. Stripped repeatedly
# from the start of the caption before slugification.
_LEADING_FILLERS = (
    "there is",
    "there are",
    "this is",
    "it is",
    "an image of",
    "a photo of",
    "a picture of",
    "image of",
    "photo of",
    "picture of",
    "a close up of",
    "close up of",
)

# Words that carry no meaning in a file name, dropped wherever they appear.
_DROPPED_WORDS = {
    "a",
    "an",
    "the",
    "of",
    "image",
    "photo",
    "picture",
    "showing",
    "arafed",  # known BLIP artifact token
    "araffe",
    # Fragments left when a contraction/possessive is split on punctuation.
    "s", "t", "re", "ve", "ll",
}

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def clean_caption(caption: str) -> str:
    """Normalize whitespace and strip leading filler phrases."""
    text = " ".join(caption.split()).strip()
    lowered = text.lower()
    changed = True
    while changed:
        changed = False
        for filler in _LEADING_FILLERS:
            if lowered.startswith(filler + " "):
                text = text[len(filler) + 1 :]
                lowered = lowered[len(filler) + 1 :]
                changed = True
    return text.strip()


def caption_to_words(caption: str) -> list[str]:
    """Split a caption into meaningful lowercase words."""
    cleaned = clean_caption(caption).lower()
    raw_words = [w for w in _NON_WORD_RE.split(cleaned) if w]
    return [w for w in raw_words if w not in _DROPPED_WORDS]


def build_stem(caption: str) -> str:
    """Build the file name stem (no extension) from a caption."""
    words = caption_to_words(caption)[:MAX_WORDS]
    stem = ""
    for word in words:
        candidate = word if not stem else f"{stem}-{word}"
        if len(candidate) > MAX_NAME_LENGTH:
            break
        stem = candidate
    return stem or FALLBACK_NAME


def build_suggested_name(caption: str, extension: str) -> str:
    """Build a safe suggested file name, keeping the original extension."""
    return f"{build_stem(caption)}{extension}"


class FinalNameAllocator:
    """Deduplicates already-built base names within one report.

    The first occurrence keeps its name; later duplicates get -002, -003.
    Comparison is case-insensitive because Windows file names are.
    """

    def __init__(self, separator: str = "-") -> None:
        self._counts: dict[str, int] = {}
        self._separator = separator

    def allocate(self, base: str, extension: str) -> str:
        key = f"{base}{extension}".lower()
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        if count == 1:
            return f"{base}{extension}"
        return f"{base}{self._separator}{count:03d}{extension}"


class NameAllocator:
    """Assigns stable, unique suggested names within one report.

    The first occurrence of a stem keeps its plain name; later duplicates
    get ``-002``, ``-003`` and so on, in processing order. Comparison is
    case-insensitive because Windows file names are.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def allocate(self, caption: str, extension: str) -> str:
        stem = build_stem(caption)
        key = f"{stem}{extension}".lower()
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        if count == 1:
            return f"{stem}{extension}"
        return f"{stem}-{count:03d}{extension}"
