"""The shared naming pipeline: caption + metadata -> suggested file name.

Used by scan, `naming preview` and `report rename-suggestions`, so all
three produce identical results. Imports nothing heavy — no PyTorch, no
FFmpeg — which keeps the preview commands instant.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from filesight.categories import CategoryRule, MediaCategorizer
from filesight.features import apply_subject_fallback, extract_features
from filesight.media_dates import date_parts
from filesight.models import (
    ClassificationResult,
    MediaFeatures,
    NamingResult,
)
from filesight.profiles import NamingProfile
from filesight.templates import FilenameTemplateEngine


@dataclass
class NamingOutcome:
    features: MediaFeatures
    classification: ClassificationResult
    naming: NamingResult


class NamingSession:
    """Names every file of one scan/report consistently.

    Owns the index counters (global / per-category / per-directory) and
    the duplicate-name allocator, so results are stable for a given
    ordered input list.
    """

    def __init__(
        self,
        profile: NamingProfile,
        category_rules: Optional[list[CategoryRule]] = None,
        template: Optional[str] = None,
    ) -> None:
        from filesight.naming import FinalNameAllocator

        self.profile = profile
        self.category_rules = category_rules
        self.template = template
        self._allocator = FinalNameAllocator(profile.separator)
        self._counters: dict[str, int] = {}

    def _next_index(self, category: str, directory: str) -> int:
        scope = self.profile.index_scope
        if scope == "category":
            key = f"category:{category}"
        elif scope == "directory":
            key = f"directory:{os.path.normcase(directory)}"
        else:
            key = "global"
        current = self._counters.get(key, self.profile.index_start - 1) + 1
        self._counters[key] = current
        return current

    def name_for(
        self,
        original_path: str,
        original_name: str,
        caption: Optional[str],
        media_type: str = "image",
        captured_at: Optional[str] = None,
        text: Optional[str] = None,
        extra: Optional[dict[str, str]] = None,
    ) -> NamingOutcome:
        """Produce features, classification and a unique suggested name."""
        stem, ext = os.path.splitext(original_name or "")
        profile = self.profile

        features = extract_features(
            caption,
            media_type=media_type,
            original_stem=stem,
            max_objects=profile.max_objects,
        )
        features.text = text

        classification = MediaCategorizer(self.category_rules).classify(
            caption,
            original_name=original_name,
            media_type=media_type,
            extension=ext,
            text=text,
            language=profile.language,
        )
        apply_subject_fallback(
            features,
            classification.category,
            allow_original_stem=profile.allow_original_stem_fallback,
        )

        index = self._next_index(
            classification.category, os.path.dirname(original_path or "")
        )
        engine = FilenameTemplateEngine(profile)
        naming = engine.build(
            features,
            classification,
            extension=ext,
            template=self.template,
            date_parts=date_parts(
                captured_at, profile.date_format, profile.time_format
            ),
            index=index,
            extra=extra,
        )
        # de-duplicate across the whole report
        naming.suggested_name = self._allocator.allocate(naming.base_name, ext)
        return NamingOutcome(
            features=features, classification=classification, naming=naming
        )


def build_naming(
    caption: Optional[str],
    original_name: str,
    profile: NamingProfile,
    media_type: str = "image",
    extension: Optional[str] = None,
    captured_at: Optional[str] = None,
    index: Optional[int] = None,
    category_rules: Optional[list[CategoryRule]] = None,
    template: Optional[str] = None,
    text: Optional[str] = None,
    extra: Optional[dict[str, str]] = None,
) -> NamingOutcome:
    """Run caption -> features -> category -> template -> suggested name."""
    stem, detected_ext = os.path.splitext(original_name or "")
    ext = extension if extension is not None else detected_ext

    features = extract_features(
        caption,
        media_type=media_type,
        original_stem=stem,
        max_objects=profile.max_objects,
    )
    features.text = text

    categorizer = MediaCategorizer(category_rules)
    classification = categorizer.classify(
        caption,
        original_name=original_name,
        media_type=media_type,
        extension=ext,
        text=text,
        language=profile.language,
    )

    apply_subject_fallback(
        features,
        classification.category,
        allow_original_stem=profile.allow_original_stem_fallback,
    )

    engine = FilenameTemplateEngine(profile)
    naming = engine.build(
        features,
        classification,
        extension=ext,
        template=template,
        date_parts=date_parts(captured_at, profile.date_format, profile.time_format),
        index=index,
        extra=extra,
    )
    return NamingOutcome(
        features=features, classification=classification, naming=naming
    )
