"""Rule-based media categorization.

Deterministic keyword/rule matching — no second model. The confidence
value is a documented rule-based score, NOT a model probability.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from filesight.localization import category_label
from filesight.models import ClassificationResult

OTHER = "other"

# Standard taxonomy. Order matters only as the final tie-break.
STANDARD_CATEGORIES = (
    "people", "animals", "nature", "food", "vehicles", "documents",
    "screenshots", "code", "products", "buildings", "travel", "sports",
    "events", "art", "memes", "medical", "other",
)

DEFAULT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "animals": (
        "dog", "cat", "bird", "horse", "cow", "animal", "puppy", "kitten",
        "fish", "rabbit", "bear", "sheep", "elephant", "zebra", "giraffe",
    ),
    "people": (
        "person", "man", "woman", "child", "boy", "girl", "people", "group",
        "family", "portrait", "baby", "crowd", "selfie",
    ),
    "screenshots": (
        "screenshot", "screen", "window", "interface", "dialog", "menu",
        "application", "browser", "desktop", "webpage", "website",
    ),
    "code": (
        "code", "editor", "terminal", "console", "javascript", "python",
        "typescript", "html", "css", "function", "repository", "programming",
    ),
    "documents": (
        "document", "paper", "letter", "invoice", "receipt", "form",
        "certificate", "contract", "page", "handwriting", "printed",
    ),
    "vehicles": (
        "car", "truck", "bus", "train", "airplane", "motorcycle", "bicycle",
        "vehicle", "boat", "ship", "tractor",
    ),
    "nature": (
        "forest", "mountain", "river", "lake", "sea", "tree", "flower",
        "sky", "sunset", "landscape", "beach", "field", "garden", "snow",
        "ocean", "waterfall", "sunrise",
    ),
    "food": (
        "food", "meal", "plate", "pizza", "bread", "cake", "meat", "fruit",
        "vegetable", "drink", "coffee", "sandwich", "salad", "restaurant",
    ),
    "buildings": (
        "building", "house", "church", "tower", "castle", "bridge",
        "architecture", "skyscraper", "apartment", "roof",
    ),
    "sports": (
        "sport", "football", "soccer", "basketball", "tennis", "running",
        "swimming", "bicycle race", "stadium", "player", "game",
    ),
    "travel": (
        "travel", "airport", "luggage", "hotel", "map", "passport",
        "tourist", "vacation", "suitcase", "backpack", "boarding",
    ),
    "art": (
        "painting", "drawing", "art", "sculpture", "mural", "illustration",
        "graffiti", "museum",
    ),
    "products": (
        "product", "package", "box", "bottle", "shoe", "watch", "phone",
        "laptop", "camera", "furniture",
    ),
    "medical": (
        "medical", "doctor", "hospital", "medicine", "x-ray", "pill",
        "syringe", "clinic",
    ),
    "events": (
        "wedding", "party", "concert", "birthday", "celebration",
        "conference", "festival", "ceremony",
    ),
    "memes": ("meme", "caption text", "funny image"),
}

# Filenames that strongly indicate a screenshot regardless of caption.
_SCREENSHOT_NAME_RE = re.compile(
    r"^(screenshot|screen[\s_-]?shot|snip|capture)", re.IGNORECASE
)

DEFAULT_PRIORITIES: dict[str, int] = {
    # More specific categories outrank generic ones on ties.
    "screenshots": 80,
    "code": 75,
    "documents": 70,
    "medical": 65,
    "memes": 60,
    "events": 55,
    "people": 50,
    "animals": 45,
    "vehicles": 40,
    "food": 35,
    "sports": 30,
    "travel": 28,
    "art": 26,
    "products": 24,
    "buildings": 22,
    "nature": 20,
}


@dataclass
class CategoryRule:
    """One category's matching rules (built-in or user-defined)."""

    name: str
    enabled: bool = True
    priority: int = 10
    keywords_any: tuple[str, ...] = ()
    keywords_all: tuple[str, ...] = ()
    filename_contains: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    media_types: tuple[str, ...] = ()
    caption_contains: tuple[str, ...] = ()
    min_matches: int = 1
    order: int = 0  # definition order, final tie-break


def default_rules() -> list[CategoryRule]:
    """Built-in category rules in a stable, documented order."""
    rules: list[CategoryRule] = []
    for order, name in enumerate(
        [c for c in STANDARD_CATEGORIES if c != OTHER]
    ):
        rules.append(
            CategoryRule(
                name=name,
                priority=DEFAULT_PRIORITIES.get(name, 10),
                keywords_any=DEFAULT_KEYWORDS.get(name, ()),
                order=order,
            )
        )
    return rules


def confidence_for(matches: int) -> float:
    """Rule-based confidence score (documented, not a model probability)."""
    if matches <= 0:
        return 0.0
    if matches == 1:
        return 0.55
    if matches == 2:
        return 0.70
    if matches == 3:
        return 0.82
    return 0.92


@dataclass
class RuleMatch:
    rule: CategoryRule
    matched: list[str] = field(default_factory=list)

    @property
    def score(self) -> int:
        return len(self.matched)


def _words_of(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


class MediaCategorizer:
    """Assigns a category from caption + filename + metadata, by rules."""

    def __init__(self, rules: Optional[list[CategoryRule]] = None) -> None:
        self.rules = rules if rules is not None else default_rules()

    def evaluate(
        self,
        caption: Optional[str],
        original_name: str = "",
        media_type: str = "image",
        extension: str = "",
        text: Optional[str] = None,
    ) -> list[RuleMatch]:
        """Score every enabled rule; returns all rules that matched."""
        haystack = " ".join(filter(None, [caption or "", text or ""]))
        words = _words_of(haystack)
        lower_caption = haystack.lower()
        lower_name = (original_name or "").lower()
        ext = (extension or os.path.splitext(original_name or "")[1]).lower()

        results: list[RuleMatch] = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.media_types and media_type not in rule.media_types:
                continue
            if rule.extensions and ext not in tuple(
                e.lower() for e in rule.extensions
            ):
                continue

            matched: list[str] = []
            for keyword in rule.keywords_any:
                if self._keyword_hits(keyword, words, lower_caption):
                    matched.append(f"keyword:{keyword}")
            if rule.keywords_all:
                if all(
                    self._keyword_hits(k, words, lower_caption)
                    for k in rule.keywords_all
                ):
                    matched.extend(f"keyword_all:{k}" for k in rule.keywords_all)
                else:
                    continue  # keywords_all is mandatory when present
            for fragment in rule.filename_contains:
                if fragment.lower() in lower_name:
                    matched.append(f"filename:{fragment}")
            for fragment in rule.caption_contains:
                if fragment.lower() in lower_caption:
                    matched.append(f"caption:{fragment}")

            if rule.name == "screenshots" and _SCREENSHOT_NAME_RE.match(lower_name):
                matched.append("filename:screenshot-prefix")

            if matched and len(matched) >= rule.min_matches:
                results.append(RuleMatch(rule=rule, matched=matched))
        return results

    @staticmethod
    def _keyword_hits(keyword: str, words: set[str], lower_caption: str) -> bool:
        key = keyword.lower()
        if " " in key:  # multi-word keyword: substring match
            return key in lower_caption
        return key in words

    def classify(
        self,
        caption: Optional[str],
        original_name: str = "",
        media_type: str = "image",
        extension: str = "",
        text: Optional[str] = None,
        language: str = "en",
    ) -> ClassificationResult:
        """Pick the winning category deterministically."""
        matches = self.evaluate(caption, original_name, media_type, extension, text)
        if not matches:
            return ClassificationResult(
                category=OTHER,
                category_label=category_label(OTHER, language),
                confidence=0.0,
                method="rules",
                matched_rules=[],
            )
        # more matches wins; then higher priority; then earlier definition
        best = max(
            matches,
            key=lambda m: (m.score, m.rule.priority, -m.rule.order),
        )
        return ClassificationResult(
            category=best.rule.name,
            category_label=category_label(best.rule.name, language),
            confidence=confidence_for(best.score),
            method="rules",
            matched_rules=list(best.matched),
        )
