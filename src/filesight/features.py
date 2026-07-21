"""Turn a caption into structured MediaFeatures.

Deterministic, dictionary-driven parsing — no NLP model. BLIP captions
follow a narrow set of shapes ("a black dog running through snow near
trees"), so a small grammar of verbs/prepositions covers most of them.
It is explicitly not a general parser; unknown shapes degrade to a
subject-only result rather than guessing.
"""

from __future__ import annotations

import re
from typing import Optional

from filesight.models import MediaFeatures
from filesight.naming import clean_caption

# Words that never carry meaning in a file name.
STOP_WORDS = {
    "a", "an", "the", "of", "is", "are", "was", "were", "be", "being",
    "been", "and", "or", "but", "that", "this", "these", "those", "it",
    "its", "there", "here", "with", "without", "some", "very", "as",
    "image", "photo", "picture", "showing", "shows", "view",
    "arafed", "araffe",  # known BLIP artifact tokens
    # Placeholder words must never reach a file name, even if the caption
    # literally contains them.
    "none", "null", "unknown", "undefined", "nan",
}

# Present participles / verbs commonly produced by the captioner.
ACTION_WORDS = {
    "running", "walking", "sitting", "standing", "playing", "jumping",
    "sleeping", "eating", "drinking", "flying", "swimming", "riding",
    "holding", "looking", "smiling", "working", "driving", "reading",
    "cooking", "dancing", "climbing", "hanging", "lying", "resting",
    "posing", "waiting", "talking", "singing", "laughing", "watching",
    "wearing", "carrying", "pointing", "waving", "surfing", "skiing",
    "skating", "fishing", "hiking", "cycling", "typing", "writing",
    "painting", "sailing", "parked", "grazing", "staring", "leaping",
}

# Prepositions that usually introduce a location phrase.
LOCATION_PREPOSITIONS = (
    "in front of", "next to", "close to", "on top of", "in the middle of",
    "through", "across", "behind", "beside", "against", "inside",
    "outside", "near", "under", "above", "over", "along", "around",
    "into", "onto", "upon", "at", "on", "in", "by",
)

# Colors/qualifiers that belong with the subject noun.
_ADJECTIVES = {
    "black", "white", "red", "blue", "green", "yellow", "orange", "brown",
    "grey", "gray", "purple", "pink", "golden", "silver", "dark", "light",
    "small", "large", "big", "little", "old", "new", "young", "tall",
    "short", "long", "wooden", "metal", "plastic", "empty", "full",
}

_WORD_RE = re.compile(r"[a-z0-9']+")

MAX_SUBJECT_WORDS = 3


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _strip_stop_words(words: list[str]) -> list[str]:
    return [w for w in words if w not in STOP_WORDS]


# Every single word that can introduce a location phrase; these must never
# end up inside a subject, location or objects value.
PREPOSITION_WORDS = {
    "in", "on", "at", "by", "near", "under", "above", "over", "along",
    "around", "into", "onto", "upon", "through", "across", "behind",
    "beside", "against", "inside", "outside", "front", "next", "close",
    "top", "middle", "of", "to", "from", "with",
}

MAX_LOCATION_WORDS = 3


def _find_preposition(words: list[str]) -> Optional[int]:
    """Index of the first word that introduces a location phrase."""
    return next((i for i, w in enumerate(words) if w in PREPOSITION_WORDS), None)


def _split_on_preposition(words: list[str]) -> tuple[list[str], Optional[str]]:
    """Split a token list at the first location preposition.

    The location is the words up to the *next* preposition, so
    "through snow near trees" yields "snow", not "snow near trees".
    Returns (head_words, location_phrase or None).
    """
    position = _find_preposition(words)
    if position is None:
        return words, None
    head = words[:position]
    tail = words[position + 1 :]
    # cut the tail at the next preposition so only one phrase is captured
    next_position = _find_preposition(tail)
    if next_position is not None:
        tail = tail[:next_position]
    location_words = [
        w for w in _strip_stop_words(tail) if w not in PREPOSITION_WORDS
    ]
    location = " ".join(location_words[:MAX_LOCATION_WORDS])
    return head, location or None


def extract_features(
    caption: Optional[str],
    media_type: str = "image",
    original_stem: str = "",
    max_objects: int = 3,
) -> MediaFeatures:
    """Parse a caption into subject / action / location / objects."""
    features = MediaFeatures(
        media_type=media_type,
        original_stem=original_stem,
        caption=caption,
    )
    if not caption or not caption.strip():
        return features

    cleaned = clean_caption(caption)
    words = _tokens(cleaned)
    if not words:
        return features

    # 1. Action: the first recognized verb splits subject from the rest.
    action_index = next(
        (i for i, w in enumerate(words) if w in ACTION_WORDS), None
    )
    if action_index is not None:
        features.action = words[action_index]
        subject_words = words[:action_index]
        remainder = words[action_index + 1 :]
    else:
        subject_words = words
        remainder = []

    # 2. Location: prefer a preposition phrase after the action; if there
    #    is no action, look inside the subject part instead.
    if remainder:
        _, location = _split_on_preposition(remainder)
        features.location = location
    if features.location is None:
        subject_words, location = _split_on_preposition(subject_words)
        features.location = location

    # 3. Subject: meaningful words before the action, capped for length.
    subject_tokens = [
        w for w in _strip_stop_words(subject_words) if w not in PREPOSITION_WORDS
    ]
    if subject_tokens:
        features.subject = " ".join(subject_tokens[-MAX_SUBJECT_WORDS:])

    # 4. Objects: distinct nouns across the caption, excluding whatever is
    #    already represented by subject/action/location.
    subject_set = set(features.subject.split()) if features.subject else set()
    objects: list[str] = []
    for word in _strip_stop_words(words):
        if word in subject_set or word in ACTION_WORDS or word in _ADJECTIVES:
            continue
        if word in PREPOSITION_WORDS:
            continue
        if word not in objects:
            objects.append(word)
    features.objects = objects[:max_objects]

    return features


def apply_subject_fallback(
    features: MediaFeatures,
    category: str,
    allow_original_stem: bool = False,
) -> MediaFeatures:
    """Fill in a subject when the caption gave us none.

    Order: first object -> category -> original stem (if allowed) -> media.
    """
    if features.subject:
        return features
    if features.objects:
        features.subject = features.objects[0]
        return features
    if category and category != "other":
        features.subject = category
        return features
    if allow_original_stem and features.original_stem:
        features.subject = features.original_stem
        return features
    features.subject = "media"
    return features
