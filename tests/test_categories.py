import pytest

from filesight.categories import (
    CategoryRule,
    MediaCategorizer,
    confidence_for,
    default_rules,
)
from filesight.config import parse_config


def classify(caption, **kwargs):
    return MediaCategorizer().classify(caption, **kwargs)


@pytest.mark.parametrize(
    "caption,expected",
    [
        ("a black dog running through snow", "animals"),
        ("a woman standing near a building", "people"),
        ("a red car parked on a street", "vehicles"),
        ("a screenshot of a code editor with python", "code"),
        ("a scanned invoice document", "documents"),
        ("a plate of pizza on a table", "food"),
        ("a mountain landscape at sunset", "nature"),
    ],
)
def test_standard_categories(caption: str, expected: str) -> None:
    assert classify(caption).category == expected


def test_screenshot_detected_from_filename() -> None:
    result = classify("a blurry rectangle", original_name="Screenshot_2026-07-20.png")
    assert result.category == "screenshots"
    assert any("screenshot" in rule for rule in result.matched_rules)


def test_unknown_caption_falls_back_to_other() -> None:
    result = classify("zzzz qqqq wwww")
    assert result.category == "other"
    assert result.confidence == 0.0
    assert result.matched_rules == []


def test_more_matches_beats_priority() -> None:
    # "screenshots" has a higher priority than "animals", but two animal
    # keywords outweigh a single screenshot keyword.
    result = classify("a screen showing a dog and a cat")
    assert result.category == "animals"


def test_priority_breaks_a_tie() -> None:
    # one people keyword vs one vehicles keyword -> people has priority
    result = classify("a woman near a car")
    assert result.category == "people"


def test_confidence_is_stable_and_documented() -> None:
    assert confidence_for(0) == 0.0
    assert confidence_for(1) == 0.55
    assert confidence_for(2) == 0.70
    assert confidence_for(3) == 0.82
    assert confidence_for(9) == 0.92
    assert classify("a dog").confidence == 0.55


def test_single_match_never_reaches_full_confidence() -> None:
    assert classify("a dog").confidence < 1.0


def test_categorization_is_deterministic() -> None:
    caption = "a woman and a dog near a car"
    results = {classify(caption).category for _ in range(5)}
    assert len(results) == 1


def test_disabled_category_is_skipped() -> None:
    rules = [r for r in default_rules()]
    for rule in rules:
        if rule.name == "animals":
            rule.enabled = False
    result = MediaCategorizer(rules).classify("a black dog running")
    assert result.category != "animals"


def test_custom_category_from_config() -> None:
    config = parse_config(
        {
            "config_version": "1.0",
            "categories": {
                "receipts": {
                    "enabled": True,
                    "priority": 150,
                    "keywords_any": ["receipt", "invoice", "total"],
                }
            },
        }
    )
    assert config.errors == []
    result = MediaCategorizer(config.category_rules).classify("a total on a receipt")
    assert result.category == "receipts"


def test_more_matches_still_beats_a_custom_high_priority() -> None:
    # documented precedence: match count outranks priority, even for a
    # custom category with priority 150
    config = parse_config(
        {
            "config_version": "1.0",
            "categories": {
                "receipts": {"enabled": True, "priority": 150,
                             "keywords_any": ["receipt"]}
            },
        }
    )
    # "paper" + "receipt" are both built-in documents keywords -> 2 matches
    result = MediaCategorizer(config.category_rules).classify("a paper receipt")
    assert result.category == "documents"


def test_keywords_all_requires_every_keyword() -> None:
    rule = CategoryRule(
        name="both", priority=999, keywords_all=("dog", "snow"), order=0
    )
    categorizer = MediaCategorizer([rule] + default_rules())
    assert categorizer.classify("a dog in snow").category == "both"
    assert categorizer.classify("a dog on grass").category != "both"


def test_filename_contains_rule() -> None:
    rule = CategoryRule(
        name="scans", priority=999, filename_contains=("scan",), order=0
    )
    categorizer = MediaCategorizer([rule] + default_rules())
    assert categorizer.classify("blurry", original_name="scan_001.jpg").category == "scans"
    assert categorizer.classify("blurry", original_name="img_001.jpg").category != "scans"


def test_extensions_rule_limits_matching() -> None:
    rule = CategoryRule(
        name="pngonly", priority=999, keywords_any=("dog",), extensions=(".png",),
        order=0,
    )
    categorizer = MediaCategorizer([rule] + default_rules())
    assert categorizer.classify("a dog", extension=".png").category == "pngonly"
    assert categorizer.classify("a dog", extension=".jpg").category == "animals"


def test_media_types_rule_limits_matching() -> None:
    rule = CategoryRule(
        name="clips", priority=999, keywords_any=("dog",), media_types=("video",),
        order=0,
    )
    categorizer = MediaCategorizer([rule] + default_rules())
    assert categorizer.classify("a dog", media_type="video").category == "clips"
    assert categorizer.classify("a dog", media_type="image").category == "animals"


def test_min_matches_threshold() -> None:
    rule = CategoryRule(
        name="strict", priority=999, keywords_any=("dog", "snow"), min_matches=2,
        order=0,
    )
    categorizer = MediaCategorizer([rule] + default_rules())
    assert categorizer.classify("a dog").category != "strict"
    assert categorizer.classify("a dog in snow").category == "strict"


def test_explain_lists_matched_rules() -> None:
    matches = MediaCategorizer().evaluate("a woman near a car")
    names = {m.rule.name for m in matches}
    assert {"people", "vehicles"} <= names
    for match in matches:
        assert match.matched


def test_ukrainian_category_label() -> None:
    result = classify("a black dog", language="uk")
    assert result.category == "animals"
    assert result.category_label == "тварини"


def test_english_label_matches_internal_name() -> None:
    result = classify("a black dog", language="en")
    assert result.category_label == result.category == "animals"
