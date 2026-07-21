from filesight.features import apply_subject_fallback, extract_features
from filesight.models import MediaFeatures


def test_subject_only_caption() -> None:
    f = extract_features("a red bicycle")
    assert f.subject == "red bicycle"
    assert f.action is None
    assert f.location is None


def test_subject_and_action() -> None:
    f = extract_features("a black dog running")
    assert f.subject == "black dog"
    assert f.action == "running"


def test_subject_action_location() -> None:
    f = extract_features("a black dog running through snow")
    assert f.subject == "black dog"
    assert f.action == "running"
    assert f.location == "snow"


def test_location_stops_at_next_preposition() -> None:
    f = extract_features("a black dog running through snow near trees")
    assert f.location == "snow"


def test_multiple_objects_collected() -> None:
    # objects lists things *besides* the subject, so subject words are excluded
    f = extract_features("a bicycle near a tree and a bench", max_objects=3)
    assert "tree" in f.objects
    assert "bench" in f.objects
    assert all(" " not in o for o in f.objects)


def test_objects_never_repeat_the_subject() -> None:
    f = extract_features("a dog and a cat near a tree", max_objects=5)
    assert f.subject
    for word in f.subject.split():
        assert word not in f.objects


def test_leading_filler_is_stripped() -> None:
    f = extract_features("A photo of a woman standing near a red car")
    assert f.subject == "woman"
    assert f.action == "standing"
    assert f.location == "red car"


def test_caption_without_action() -> None:
    f = extract_features("a mountain landscape at sunset")
    assert f.action is None
    assert f.subject


def test_caption_without_location() -> None:
    f = extract_features("a child playing")
    assert f.location is None
    assert f.action == "playing"


def test_empty_caption_returns_blank_features() -> None:
    f = extract_features("")
    assert f.subject is None and f.action is None and f.location is None
    assert f.objects == []


def test_none_caption_is_safe() -> None:
    f = extract_features(None)
    assert f.subject is None


def test_objects_exclude_prepositions_and_actions() -> None:
    f = extract_features("a dog running through the snow near trees", max_objects=5)
    for noise in ("through", "near", "running", "the"):
        assert noise not in f.objects


def test_subject_capped_to_three_words() -> None:
    f = extract_features("a very large fluffy brown dog sitting")
    assert len(f.subject.split()) <= 3


def test_objects_limit_respected() -> None:
    f = extract_features("a dog cat bird horse cow", max_objects=2)
    assert len(f.objects) == 2


def test_video_media_type_is_recorded() -> None:
    f = extract_features("a dog running", media_type="video")
    assert f.media_type == "video"


def test_fallback_uses_first_object() -> None:
    f = MediaFeatures(objects=["bicycle", "tree"])
    apply_subject_fallback(f, "other")
    assert f.subject == "bicycle"


def test_fallback_uses_category_when_no_objects() -> None:
    f = MediaFeatures()
    apply_subject_fallback(f, "animals")
    assert f.subject == "animals"


def test_fallback_uses_media_for_other_category() -> None:
    f = MediaFeatures()
    apply_subject_fallback(f, "other")
    assert f.subject == "media"


def test_fallback_can_use_original_stem_when_allowed() -> None:
    f = MediaFeatures(original_stem="birthday-party")
    apply_subject_fallback(f, "other", allow_original_stem=True)
    assert f.subject == "birthday-party"


def test_fallback_does_not_override_existing_subject() -> None:
    f = MediaFeatures(subject="black dog")
    apply_subject_fallback(f, "animals")
    assert f.subject == "black dog"


def test_no_null_words_leak_into_features() -> None:
    for caption in ("a dog", "", "a photo of", "none"):
        f = extract_features(caption)
        for value in (f.subject, f.action, f.location):
            if value is not None:
                assert value.lower() not in ("none", "null", "unknown", "undefined")
