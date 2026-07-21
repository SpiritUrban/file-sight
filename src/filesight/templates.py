"""The filename template engine.

Substitutes {variables}, drops empty segments, normalizes separators,
enforces Windows-safe rules and the length limit, and always produces a
non-empty base name.
"""

from __future__ import annotations

import re
from typing import Optional

from filesight.localization import localize_phrase
from filesight.models import ClassificationResult, MediaFeatures, NamingResult
from filesight.naming import clean_caption
from filesight.profiles import NamingProfile
from filesight.transliteration import transliterate
from filesight.validation import FORBIDDEN_CHARS, RESERVED_NAMES

SUPPORTED_VARIABLES = (
    "subject", "action", "location", "objects", "text", "category",
    "media_type", "date", "time", "year", "month", "day",
    "original_stem", "index", "caption", "width", "height", "duration",
)

_VARIABLE_RE = re.compile(r"\{([a-z_]+)\}")

# Camera/phone/screenshot filename patterns that carry no meaning.
_NOISY_STEM_PATTERNS = (
    re.compile(r"^img[-_ ]?\d+$", re.IGNORECASE),
    re.compile(r"^dsc[-_ ]?\d+$", re.IGNORECASE),
    re.compile(r"^dscn[-_ ]?\d+$", re.IGNORECASE),
    re.compile(r"^vid[-_ ]?[\d_-]+$", re.IGNORECASE),
    re.compile(r"^pxl[-_ ]?[\d_-]+$", re.IGNORECASE),
    re.compile(r"^mvimg[-_ ]?[\d_-]+$", re.IGNORECASE),
    re.compile(r"^screenshot[-_ ]?[\d\-_. ]*$", re.IGNORECASE),
    re.compile(r"^photo[-_ ]?[\d\-_. ]*$", re.IGNORECASE),
    re.compile(r"^image[-_ ]?[\d\-_. ]*$", re.IGNORECASE),
    re.compile(r"^\d{4}[-_]?\d{2}[-_]?\d{2}[-_ ]?[\d.\-_]*$", re.IGNORECASE),
    re.compile(r"^[\d\-_. ]+$"),
)

FALLBACK_STEM = "media"


def template_variables(template: str) -> list[str]:
    return _VARIABLE_RE.findall(template)


def unknown_variables(template: str) -> list[str]:
    return [v for v in template_variables(template) if v not in SUPPORTED_VARIABLES]


def clean_stem(stem: str) -> str:
    """Drop meaningless camera-style stems; keep genuinely named files."""
    candidate = stem.strip()
    if not candidate:
        return ""
    for pattern in _NOISY_STEM_PATTERNS:
        if pattern.match(candidate):
            return ""
    return candidate


def _limit_words(text: str, max_words: int) -> str:
    words = text.split()
    return " ".join(words[:max_words]) if max_words > 0 else ""


def _collapse_repeats(text: str, separator: str) -> str:
    """Drop adjacent duplicate words ("code-code-editor" -> "code-editor").

    Different template segments often mention the same word (category
    "code" plus subject "code editor"); repeating it reads badly.
    """
    if not text:
        return text
    parts = text.split(separator)
    collapsed: list[str] = []
    for part in parts:
        if collapsed and part.lower() == collapsed[-1].lower():
            continue
        collapsed.append(part)
    return separator.join(collapsed)


class FilenameTemplateEngine:
    """Builds a safe base name from features + classification + a profile."""

    def __init__(self, profile: NamingProfile) -> None:
        self.profile = profile

    # -- variable values ---------------------------------------------------

    def build_values(
        self,
        features: MediaFeatures,
        classification: Optional[ClassificationResult],
        date_parts: Optional[dict[str, str]] = None,
        index: Optional[int] = None,
        extra: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        profile = self.profile
        language = profile.language
        date_parts = date_parts or {}

        def localized(value: Optional[str]) -> str:
            if not value:
                return ""
            return localize_phrase(value, language)

        objects = [
            o for o in features.objects
            if not features.subject or o not in features.subject.split()
        ][: profile.max_objects]
        objects_text = profile.objects_separator.join(
            localized(o) for o in objects
        )

        caption_text = ""
        if features.caption:
            caption_text = _limit_words(
                localized(clean_caption(features.caption)),
                profile.max_caption_words,
            )

        stem = features.original_stem or ""
        if profile.clean_original_stem:
            stem = clean_stem(stem)

        values: dict[str, str] = {
            "subject": localized(features.subject),
            "action": localized(features.action),
            "location": localized(features.location),
            "objects": objects_text,
            "text": localized(_limit_words(features.text or "", 6)),
            "category": (
                classification.category_label if classification else ""
            ),
            "media_type": features.media_type or "",
            "date": date_parts.get("date", ""),
            "time": date_parts.get("time", ""),
            "year": date_parts.get("year", ""),
            "month": date_parts.get("month", ""),
            "day": date_parts.get("day", ""),
            "original_stem": stem,
            "index": (
                f"{index:0{profile.index_padding}d}" if index is not None else ""
            ),
            "caption": caption_text,
        }
        if extra:
            values.update({k: str(v) for k, v in extra.items() if v is not None})
        for name in SUPPORTED_VARIABLES:
            values.setdefault(name, "")
        return values

    # -- rendering ---------------------------------------------------------

    def render(self, template: str, values: dict[str, str]) -> str:
        """Substitute variables, dropping segments whose value is empty."""
        profile = self.profile

        def substitute(match: re.Match) -> str:
            return values.get(match.group(1), "") or ""

        rendered = _VARIABLE_RE.sub(substitute, template)
        base = self.normalize(rendered)
        if profile.transliterate:
            base = transliterate(base)
            base = self.normalize(base)
        return base

    def normalize(self, text: str) -> str:
        """Apply separator, case, charset and collapsing rules."""
        profile = self.profile
        separator = profile.separator

        # Any run of whitespace or separator characters collapses to one.
        text = re.sub(r"[\s\-_]+", separator, text)
        # Strip characters Windows forbids, plus path separators and dots.
        text = "".join(
            ch for ch in text if ch not in FORBIDDEN_CHARS and ch not in "./\\"
        )
        text = re.sub(re.escape(separator) + r"{2,}", separator, text)
        text = text.strip(separator + " .")
        text = _collapse_repeats(text, separator)

        if profile.case_style == "lower":
            text = text.lower()
        elif profile.case_style == "upper":
            text = text.upper()
        elif profile.case_style == "title":
            text = separator.join(
                part[:1].upper() + part[1:] for part in text.split(separator) if part
            )
        return text

    def enforce_length(self, base: str, extension: str) -> tuple[str, list[str]]:
        """Trim to max_filename_length without breaking words or Unicode."""
        profile = self.profile
        warnings: list[str] = []
        budget = profile.max_filename_length - len(extension)
        if budget <= 0:
            budget = 1
        if len(base) <= budget:
            return base, warnings

        warnings.append("truncated_to_max_length")
        separator = profile.separator
        parts = base.split(separator)
        trimmed = ""
        for part in parts:
            candidate = part if not trimmed else f"{trimmed}{separator}{part}"
            if len(candidate) > budget:
                break
            trimmed = candidate
        if not trimmed:  # a single word longer than the budget
            trimmed = base[:budget]
        return trimmed.strip(separator + " ."), warnings

    def finalize(self, base: str, extension: str, index: Optional[int]) -> tuple[
        str, list[str]
    ]:
        """Apply fallbacks, length and reserved-name rules. Never empty."""
        profile = self.profile
        warnings: list[str] = []
        if not base:
            warnings.append("empty_template_result")
            number = index if index is not None else profile.index_start
            base = f"{FALLBACK_STEM}{profile.separator}{number:0{profile.index_padding}d}"
            base = self.normalize(base)

        base, length_warnings = self.enforce_length(base, extension)
        warnings.extend(length_warnings)

        if not base:
            base = FALLBACK_STEM
        if base.split(".")[0].strip().upper() in RESERVED_NAMES:
            base = f"{base}{profile.separator}file"
            warnings.append("reserved_windows_name")
            base, _ = self.enforce_length(base, extension)
        return base, warnings

    # -- one-shot ----------------------------------------------------------

    def build(
        self,
        features: MediaFeatures,
        classification: Optional[ClassificationResult],
        extension: str,
        template: Optional[str] = None,
        date_parts: Optional[dict[str, str]] = None,
        index: Optional[int] = None,
        extra: Optional[dict[str, str]] = None,
    ) -> NamingResult:
        profile = self.profile
        active_template = template or profile.template
        values = self.build_values(features, classification, date_parts, index, extra)
        base = self.render(active_template, values)

        if not base:
            # Documented fallback: {category}-{index}, or media-{index}
            # when there is no category to fall back to.
            category = values.get("category") or FALLBACK_STEM
            number = index if index is not None else profile.index_start
            fallback = f"{category}{profile.separator}{number:0{profile.index_padding}d}"
            base = self.normalize(fallback)

        base, warnings = self.finalize(base, extension, index)
        return NamingResult(
            profile=profile.name,
            template=active_template,
            language=profile.language,
            transliterated=profile.transliterate,
            base_name=base,
            suggested_name=f"{base}{extension}",
            warnings=warnings,
        )
