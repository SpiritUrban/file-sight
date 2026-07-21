"""Naming profiles: built-in defaults plus user overrides."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Optional

from filesight.constants import (
    DEFAULT_INDEX_PADDING,
    DEFAULT_MAX_CAPTION_WORDS,
    DEFAULT_MAX_FILENAME_LENGTH,
    DEFAULT_MAX_OBJECTS,
)

SUPPORTED_SEPARATORS = ("-", "_", " ")
SUPPORTED_CASE_STYLES = ("lower", "upper", "title", "preserve")
SUPPORTED_INDEX_SCOPES = ("global", "category", "directory")


@dataclass
class NamingProfile:
    """Everything that controls how one file name is built."""

    name: str = "default"
    template: str = "{subject}-{action}-{location}"
    language: str = "en"
    separator: str = "-"
    case_style: str = "lower"
    transliterate: bool = False
    max_filename_length: int = DEFAULT_MAX_FILENAME_LENGTH
    max_objects: int = DEFAULT_MAX_OBJECTS
    max_caption_words: int = DEFAULT_MAX_CAPTION_WORDS
    objects_separator: str = "-"
    date_format: str = "%Y-%m-%d"
    time_format: str = "%H-%M-%S"
    index_start: int = 1
    index_padding: int = DEFAULT_INDEX_PADDING
    index_scope: str = "global"
    clean_original_stem: bool = True
    allow_original_stem_fallback: bool = False

    def merged_with(self, overrides: dict[str, Any]) -> "NamingProfile":
        """Return a copy with non-None overrides applied."""
        clean = {k: v for k, v in overrides.items() if v is not None}
        return replace(self, **clean) if clean else self


# Built-in profiles. "default" reproduces iteration 1-3 behavior closely.
BUILT_IN_PROFILES: dict[str, NamingProfile] = {
    "default": NamingProfile(
        name="default",
        template="{subject}-{action}-{location}",
    ),
    "photos": NamingProfile(
        name="photos",
        template="{date}-{category}-{subject}-{location}",
        max_filename_length=100,
    ),
    "compact": NamingProfile(
        name="compact",
        template="{subject}-{action}",
        max_filename_length=70,
    ),
    "archive": NamingProfile(
        name="archive",
        template="{date}-{media_type}-{category}-{subject}-{index}",
        max_filename_length=120,
    ),
    "screenshots": NamingProfile(
        name="screenshots",
        template="{date}-{category}-{text}",
        max_filename_length=120,
    ),
}


def built_in_profile(name: str) -> Optional[NamingProfile]:
    profile = BUILT_IN_PROFILES.get(name)
    return replace(profile) if profile is not None else None


def built_in_names() -> list[str]:
    return sorted(BUILT_IN_PROFILES)
