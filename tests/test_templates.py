import pytest

from filesight.models import ClassificationResult, MediaFeatures
from filesight.naming_preview import build_naming
from filesight.profiles import built_in_profile
from filesight.templates import (
    FilenameTemplateEngine,
    clean_stem,
    unknown_variables,
)


def features(**kwargs) -> MediaFeatures:
    base = dict(subject="black dog", action="running", location="snow", objects=[])
    base.update(kwargs)
    return MediaFeatures(**base)


def classification(
    category: str = "animals", label: str | None = None
) -> ClassificationResult:
    # category_label is what the {category} variable renders; the real
    # categorizer localizes it at classification time.
    return ClassificationResult(category, label or category, 0.7, "rules", [])


def build(profile, template=None, feats=None, cls=None, ext=".jpg", **kwargs):
    engine = FilenameTemplateEngine(profile)
    return engine.build(
        feats if feats is not None else features(),
        cls if cls is not None else classification(),
        extension=ext,
        template=template,
        **kwargs,
    )


def test_simple_template() -> None:
    p = built_in_profile("default")
    assert build(p, "{subject}-{action}").base_name == "black-dog-running"


def test_empty_action_segment_is_dropped() -> None:
    p = built_in_profile("default")
    result = build(p, "{subject}-{action}-{location}", feats=features(action=None))
    assert result.base_name == "black-dog-snow"
    assert "--" not in result.base_name


def test_empty_location_segment_is_dropped() -> None:
    p = built_in_profile("default")
    result = build(p, "{subject}-{action}-{location}", feats=features(location=None))
    assert result.base_name == "black-dog-running"


def test_several_empty_segments() -> None:
    p = built_in_profile("default")
    result = build(
        p, "{date}-{category}-{subject}-{action}-{location}",
        feats=features(action=None, location=None),
    )
    assert result.base_name == "animals-black-dog"
    assert not result.base_name.startswith("-")
    assert not result.base_name.endswith("-")


def test_unknown_variable_is_detected() -> None:
    assert unknown_variables("{subject}-{bogus}") == ["bogus"]
    assert unknown_variables("{subject}-{date}") == []


def test_unknown_variable_renders_empty_not_literal() -> None:
    p = built_in_profile("default")
    result = build(p, "{subject}-{bogus}")
    assert result.base_name == "black-dog"
    assert "bogus" not in result.base_name


@pytest.mark.parametrize(
    "style,expected",
    [
        ("lower", "black-dog-running"),
        ("upper", "BLACK-DOG-RUNNING"),
        ("title", "Black-Dog-Running"),
    ],
)
def test_case_styles(style: str, expected: str) -> None:
    p = built_in_profile("default")
    p.case_style = style
    assert build(p, "{subject}-{action}").base_name == expected


def test_preserve_case_style() -> None:
    p = built_in_profile("default")
    p.case_style = "preserve"
    result = build(p, "{subject}", feats=features(subject="Black Dog"))
    assert result.base_name == "Black-Dog"


@pytest.mark.parametrize("separator", ["-", "_"])
def test_separators(separator: str) -> None:
    p = built_in_profile("default")
    p.separator = separator
    result = build(p, "{subject}-{action}")
    assert result.base_name == f"black{separator}dog{separator}running"
    assert separator * 2 not in result.base_name


def test_no_double_separators_or_edges() -> None:
    p = built_in_profile("default")
    result = build(p, "--{subject}--{action}--", feats=features(action=None))
    assert result.base_name == "black-dog"


def test_ukrainian_characters_preserved() -> None:
    p = built_in_profile("default")
    p.language = "uk"
    result = build(p, "{category}-{subject}-{action}",
                   cls=classification("animals", "тварини"))
    assert result.base_name == "тварини-чорний-пес-біжить"


def test_ukrainian_transliteration() -> None:
    p = built_in_profile("default")
    p.language = "uk"
    p.transliterate = True
    result = build(p, "{category}-{subject}-{action}",
                   cls=classification("animals", "тварини"))
    assert result.base_name == "tvaryny-chornyi-pes-bizhyt"
    assert result.transliterated is True


def test_ukrainian_end_to_end_through_the_pipeline() -> None:
    p = built_in_profile("default")
    p.language = "uk"
    outcome = build_naming(
        "a black dog running through snow", "IMG_1.jpg", p,
        template="{category}-{subject}-{action}",
    )
    assert outcome.naming.base_name == "тварини-чорний-пес-біжить"


def test_max_length_trims_whole_words() -> None:
    p = built_in_profile("default")
    p.max_filename_length = 24  # 4 chars go to ".jpg"
    result = build(p, "{subject}-{action}-{location}")
    assert len(result.suggested_name) <= 24
    assert not result.base_name.endswith("-")
    assert "truncated_to_max_length" in result.warnings


def test_extension_is_preserved_exactly() -> None:
    p = built_in_profile("default")
    assert build(p, "{subject}", ext=".JPG").suggested_name.endswith(".JPG")
    assert build(p, "{subject}", ext=".webp").suggested_name.endswith(".webp")


def test_reserved_windows_name_is_defused() -> None:
    p = built_in_profile("default")
    result = build(p, "{subject}", feats=features(subject="CON"))
    assert result.base_name.upper() != "CON"
    assert "reserved_windows_name" in result.warnings


def test_forbidden_characters_removed() -> None:
    p = built_in_profile("default")
    result = build(p, "{subject}", feats=features(subject='dog<>:"|?*name'))
    for char in '<>:"/\\|?*':
        assert char not in result.suggested_name


def test_apostrophes_and_quotes_are_stripped_from_names() -> None:
    p = built_in_profile("default")
    result = build(p, "{subject}", feats=features(subject="loris 's face"))
    for char in "'’`":
        assert char not in result.suggested_name


def test_template_cannot_create_a_path() -> None:
    p = built_in_profile("default")
    result = build(
        p, "{subject}", feats=features(subject="../../etc/passwd")
    )
    assert "/" not in result.suggested_name
    assert "\\" not in result.suggested_name
    assert ".." not in result.base_name


def test_fallback_when_everything_is_empty() -> None:
    p = built_in_profile("default")
    empty = MediaFeatures()
    result = build(p, "{subject}-{action}", feats=empty, cls=classification("other"),
                   index=1)
    assert result.base_name
    assert result.suggested_name == "other-001.jpg"


def test_fallback_to_media_when_no_category() -> None:
    p = built_in_profile("default")
    empty = MediaFeatures()
    blank = ClassificationResult("", "", 0.0, "rules", [])
    result = build(p, "{subject}", feats=empty, cls=blank, index=2)
    assert result.suggested_name == "media-002.jpg"


def test_index_padding() -> None:
    p = built_in_profile("default")
    p.index_padding = 4
    result = build(p, "{subject}-{index}", index=7)
    assert result.base_name == "black-dog-0007"


def test_objects_limit_and_separator() -> None:
    p = built_in_profile("default")
    p.max_objects = 2
    feats = features(subject="dog", objects=["tree", "snow", "fence"])
    result = build(p, "{objects}", feats=feats)
    assert result.base_name == "tree-snow"


def test_caption_word_limit() -> None:
    p = built_in_profile("default")
    p.max_caption_words = 3
    feats = features(caption="a black dog running through deep snow near tall trees")
    result = build(p, "{caption}", feats=feats)
    assert len(result.base_name.split("-")) <= 3


@pytest.mark.parametrize(
    "stem",
    ["IMG_9482", "DSC_1024", "VID_20260720_184510", "PXL_20260720_184510",
     "Screenshot_2026-07-20", "20260720_184510", "1234"],
)
def test_original_stem_cleanup_drops_camera_noise(stem: str) -> None:
    assert clean_stem(stem) == ""


def test_original_stem_kept_when_meaningful() -> None:
    assert clean_stem("birthday-party-2026") == "birthday-party-2026"


def test_clean_original_stem_in_template() -> None:
    p = built_in_profile("default")
    p.clean_original_stem = True
    feats = features(original_stem="IMG_9482")
    result = build(p, "{original_stem}-{subject}", feats=feats)
    assert result.base_name == "black-dog"


def test_adjacent_duplicate_words_collapse() -> None:
    p = built_in_profile("default")
    feats = features(subject="code editor", action=None, location=None)
    result = build(p, "{category}-{subject}", cls=classification("code"), feats=feats)
    assert result.base_name == "code-editor"


def test_date_variables(  ) -> None:
    p = built_in_profile("photos")
    outcome = build_naming(
        "a black dog running through snow", "IMG_1.jpg", p,
        captured_at="2026-01-14T15:42:10",
    )
    assert outcome.naming.suggested_name.startswith("2026-01-14-")


def test_all_supported_variables_render() -> None:
    from filesight.templates import SUPPORTED_VARIABLES

    p = built_in_profile("default")
    template = "".join(f"{{{name}}}-" for name in SUPPORTED_VARIABLES)
    assert unknown_variables(template) == []
    result = build(p, template, index=1)
    assert result.base_name  # renders without raising and is non-empty
