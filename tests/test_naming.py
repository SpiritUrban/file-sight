from filesight.naming import (
    MAX_NAME_LENGTH,
    NameAllocator,
    build_stem,
    build_suggested_name,
    clean_caption,
)


def test_basic_caption_to_name() -> None:
    name = build_suggested_name("A black dog running through the snow.", ".jpg")
    assert name == "black-dog-running-through-snow.jpg"


def test_filler_phrases_removed() -> None:
    caption = "A photo of a woman standing near a red car in a parking lot."
    assert build_stem(caption) == "woman-standing-near-red-car-in-parking-lot"


def test_clean_caption_strips_stacked_fillers() -> None:
    assert clean_caption("there is a photo of a cat on a sofa") == "a cat on a sofa"


def test_forbidden_windows_characters_removed() -> None:
    name = build_suggested_name('dog <>:"/\\|?* jumping', ".png")
    assert name == "dog-jumping.png"
    for char in '<>:"/\\|?* ':
        assert char not in name


def test_lowercase_and_hyphens() -> None:
    name = build_suggested_name("Big RED Truck On Highway", ".jpg")
    assert name == "big-red-truck-on-highway.jpg"
    assert " " not in name
    assert name == name.lower()


def test_no_leading_trailing_or_double_hyphens() -> None:
    stem = build_stem("-- weird ---- caption --")
    assert not stem.startswith("-")
    assert not stem.endswith("-")
    assert "--" not in stem


def test_extension_preserved_including_case() -> None:
    assert build_suggested_name("a cat", ".JPG").endswith(".JPG")
    assert build_suggested_name("a cat", ".webp").endswith(".webp")


def test_length_limit() -> None:
    caption = " ".join(["extraordinarily"] * 30)
    stem = build_stem(caption)
    assert len(stem) <= MAX_NAME_LENGTH
    assert not stem.endswith("-")


def test_word_count_limited_to_eight() -> None:
    caption = "one two three four five six seven eight nine ten"
    assert build_stem(caption).count("-") <= 7


def test_empty_caption_falls_back() -> None:
    assert build_stem("a photo of") == "untitled"
    assert build_stem("") == "untitled"


def test_duplicate_names_get_stable_numbering() -> None:
    allocator = NameAllocator()
    first = allocator.allocate("black dog in snow", ".jpg")
    second = allocator.allocate("black dog in snow", ".jpg")
    third = allocator.allocate("black dog in snow", ".jpg")
    assert first == "black-dog-in-snow.jpg"
    assert second == "black-dog-in-snow-002.jpg"
    assert third == "black-dog-in-snow-003.jpg"


def test_duplicates_are_case_insensitive_but_extensions_differ() -> None:
    allocator = NameAllocator()
    first = allocator.allocate("a cat", ".JPG")
    second = allocator.allocate("a cat", ".jpg")
    assert first == "cat.JPG"
    assert second == "cat-002.jpg"


def test_different_extensions_do_not_conflict() -> None:
    allocator = NameAllocator()
    assert allocator.allocate("a cat", ".jpg") == "cat.jpg"
    assert allocator.allocate("a cat", ".png") == "cat.png"
