from pathlib import Path

from filesight.scanner import SUPPORTED_EXTENSIONS, find_images


def make_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"stub")
    return path


def test_finds_supported_extensions_case_insensitively(tmp_path: Path) -> None:
    expected = {
        make_file(tmp_path / "a.jpg"),
        make_file(tmp_path / "b.JPEG"),
        make_file(tmp_path / "c.PNG"),
        make_file(tmp_path / "d.WebP"),
    }
    found = set(find_images(tmp_path))
    assert found == expected


def test_ignores_unsupported_files(tmp_path: Path) -> None:
    make_file(tmp_path / "notes.txt")
    make_file(tmp_path / "anim.gif")
    make_file(tmp_path / "video.mp4")
    make_file(tmp_path / "report.json")
    make_file(tmp_path / "noextension")
    assert find_images(tmp_path) == []


def test_non_recursive_skips_subfolders(tmp_path: Path) -> None:
    top = make_file(tmp_path / "top.jpg")
    make_file(tmp_path / "nested" / "deep.jpg")
    assert find_images(tmp_path, recursive=False) == [top]


def test_recursive_includes_subfolders(tmp_path: Path) -> None:
    top = make_file(tmp_path / "top.jpg")
    deep = make_file(tmp_path / "nested" / "deep.png")
    assert set(find_images(tmp_path, recursive=True)) == {top, deep}


def test_result_is_sorted_and_stable(tmp_path: Path) -> None:
    make_file(tmp_path / "b.jpg")
    make_file(tmp_path / "A.jpg")
    names = [p.name for p in find_images(tmp_path)]
    assert names == ["A.jpg", "b.jpg"]


def test_supported_extensions_constant() -> None:
    assert SUPPORTED_EXTENSIONS == {".jpg", ".jpeg", ".png", ".webp"}
