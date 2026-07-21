from pathlib import Path

from filesight.scanner import (
    SUPPORTED_VIDEO_EXTENSIONS,
    find_media,
    find_videos,
    is_video,
)

from helpers import make_file


def test_finds_mp4(tmp_path: Path) -> None:
    v = make_file(tmp_path / "clip.mp4")
    assert find_videos(tmp_path) == [v]


def test_finds_uppercase_mov(tmp_path: Path) -> None:
    v = make_file(tmp_path / "MOVIE.MOV")
    assert find_videos(tmp_path) == [v]


def test_all_video_extensions_recognized() -> None:
    assert SUPPORTED_VIDEO_EXTENSIONS == {
        ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"
    }


def test_videos_ignored_without_include(tmp_path: Path) -> None:
    make_file(tmp_path / "clip.mp4")
    img = make_file(tmp_path / "pic.jpg")
    found = find_media(tmp_path, include_images=True, include_videos=False)
    assert found == [img]


def test_include_videos_returns_both(tmp_path: Path) -> None:
    img = make_file(tmp_path / "pic.jpg")
    vid = make_file(tmp_path / "clip.mp4")
    found = find_media(tmp_path, include_images=True, include_videos=True)
    assert set(found) == {img, vid}


def test_videos_only(tmp_path: Path) -> None:
    make_file(tmp_path / "pic.jpg")
    vid = make_file(tmp_path / "clip.mp4")
    found = find_media(tmp_path, include_images=False, include_videos=True)
    assert found == [vid]


def test_recursive_video_search(tmp_path: Path) -> None:
    top = make_file(tmp_path / "top.mp4")
    deep = make_file(tmp_path / "sub" / "deep.mov")
    found = find_media(
        tmp_path, recursive=True, include_images=False, include_videos=True
    )
    assert set(found) == {top, deep}


def test_is_video() -> None:
    assert is_video(Path("a.MP4"))
    assert is_video(Path("a.mkv"))
    assert not is_video(Path("a.jpg"))
