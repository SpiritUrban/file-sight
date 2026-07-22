"""Turning model captions into safe, readable file names.

This module is pure string processing and has no dependency on the
neural network, so it is fully unit-testable.
"""

from __future__ import annotations

import re
from typing import Optional

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


class _SlotAllocator:
    """Hands out ``stem``, ``stem-002``, ``stem-003`` … within one report.

    Slots are numbered from 1, where slot 1 is the plain, unsuffixed name.

    A file whose *current* name already occupies a free slot of its own
    family keeps that exact name. Without this, names are handed out in
    processing order and a folder of look-alike images shuffles: the first
    file scanned takes the plain name that a later file already had, which
    then has to move aside, and so on — a chain of renames that changes
    every file and improves nothing. Stability wins over tidiness here: a
    file already carrying a name we would have suggested is left alone.
    """

    def __init__(self, separator: str = "-") -> None:
        self._used: dict[str, set[int]] = {}
        self._separator = separator

    def _format(self, base: str, extension: str, slot: int) -> str:
        if slot == 1:
            return f"{base}{extension}"
        return f"{base}{self._separator}{slot:03d}{extension}"

    def _current_slot(
        self, base: str, extension: str, current_name: Optional[str]
    ) -> Optional[int]:
        """Which slot of this family the current name already occupies."""
        if not current_name:
            return None
        current = current_name.lower()
        if current == f"{base}{extension}".lower():
            return 1
        prefix = f"{base}{self._separator}".lower()
        suffix = extension.lower()
        if not (current.startswith(prefix) and current.endswith(suffix)):
            return None
        middle = current[len(prefix): len(current) - len(suffix)] if suffix else current[len(prefix):]
        # Only the exact zero-padded form we generate counts, so an
        # unrelated name like "cat-dog.jpg" is never mistaken for a slot.
        if len(middle) == 3 and middle.isdigit():
            slot = int(middle)
            if slot >= 2:
                return slot
        return None

    def allocate_base(
        self, base: str, extension: str, current_name: Optional[str] = None
    ) -> str:
        key = f"{base}{extension}".lower()
        used = self._used.setdefault(key, set())

        mine = self._current_slot(base, extension, current_name)
        if mine is not None and mine not in used:
            used.add(mine)
            return self._format(base, extension, mine)

        slot = 1
        while slot in used:
            slot += 1
        used.add(slot)
        return self._format(base, extension, slot)


class FinalNameAllocator(_SlotAllocator):
    """Deduplicates already-built base names within one report."""

    def allocate(
        self, base: str, extension: str, current_name: Optional[str] = None
    ) -> str:
        return self.allocate_base(base, extension, current_name)


class NameAllocator(_SlotAllocator):
    """Assigns stable, unique suggested names within one report.

    Comparison is case-insensitive because Windows file names are.
    """

    def allocate(
        self, caption: str, extension: str, current_name: Optional[str] = None
    ) -> str:
        return self.allocate_base(build_stem(caption), extension, current_name)
