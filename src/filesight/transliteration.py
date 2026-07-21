"""Ukrainian -> Latin transliteration (official KMU resolution No. 55, 2010).

This is the standard used for Ukrainian passports and place names, so the
output is predictable rather than an invented phonetic scheme.

Rules implemented:
- Most letters map 1:1 (а->a, б->b, в->v, г->h, ґ->g, ...).
- Є, Ї, Й, Ю, Я are position-dependent: at the start of a word they become
  ye, yi, y, yu, ya; elsewhere ie, i, i, iu, ia.
- The digraph зг becomes zgh (so it is not confused with ж -> zh).
- The soft sign (ь) and the apostrophe (’ / ') are dropped.
"""

from __future__ import annotations

_SIMPLE = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ь": "", "'": "", "’": "", "ʼ": "",
}

# Letters whose transliteration depends on their position in the word.
_POSITIONAL = {
    "є": ("ye", "ie"),
    "ї": ("yi", "i"),
    "й": ("y", "i"),
    "ю": ("yu", "iu"),
    "я": ("ya", "ia"),
}


def _match_case(source: str, latin: str) -> str:
    """Mirror the source letter's case onto the latin replacement."""
    if not latin or not source.isupper():
        return latin
    # Ukrainian uppercase maps to Capitalized latin (Ж -> Zh), not ZH.
    return latin[0].upper() + latin[1:]


def transliterate(text: str) -> str:
    """Transliterate Ukrainian text to Latin; other characters pass through."""
    result: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        lower = char.lower()

        # зг -> zgh (digraph handled before the plain з rule)
        if lower == "з" and index + 1 < length and text[index + 1].lower() == "г":
            piece = _match_case(char, "zgh")
            if char.isupper() and text[index + 1].isupper():
                piece = "ZGH"
            result.append(piece)
            index += 2
            continue

        if lower in _POSITIONAL:
            at_word_start = index == 0 or not text[index - 1].isalpha()
            start_form, mid_form = _POSITIONAL[lower]
            result.append(_match_case(char, start_form if at_word_start else mid_form))
            index += 1
            continue

        if lower in _SIMPLE:
            result.append(_match_case(char, _SIMPLE[lower]))
            index += 1
            continue

        result.append(char)
        index += 1
    return "".join(result)


def contains_cyrillic(text: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in text)
