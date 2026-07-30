"""One-click FFmpeg setup.

No test here touches the network: the ffbinaries index is injected as a
parsed dict, and the download step is exercised against a local zip served
through a stubbed `urlopen`.

Every expected path is built with pathlib, never by writing a separator
(rule 6a) -- a test that asserts `"C:\\...\\ffmpeg.exe"` checks the
separator instead of the logic and goes green on exactly one OS.
"""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

import pytest

from filesight import ffmpeg_setup
from filesight.ffmpeg_setup import (
    FFmpegDownloadError,
    download_ffmpeg,
    executable_name,
    platform_keys,
    resolve_download_urls,
    search_roots,
    user_bin_dir,
    user_data_dir,
)


def _zip_with(name: str, payload: bytes = b"stub-binary") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr(name, payload)
    return buffer.getvalue()


CATALOG = {
    "version": "6.1",
    "bin": {
        "windows-64": {"ffmpeg": "https://x/win-ffmpeg.zip", "ffprobe": "https://x/win-ffprobe.zip"},
        "linux-64": {"ffmpeg": "https://x/lin-ffmpeg.zip", "ffprobe": "https://x/lin-ffprobe.zip"},
        "linux-arm64": {"ffmpeg": "https://x/arm-ffmpeg.zip", "ffprobe": "https://x/arm-ffprobe.zip"},
        "linux-32": {"ffmpeg": "https://x/l32-ffmpeg.zip", "ffprobe": "https://x/l32-ffprobe.zip"},
        "linux-armhf": {"ffmpeg": "https://x/hf-ffmpeg.zip", "ffprobe": "https://x/hf-ffprobe.zip"},
        "linux-armel": {"ffmpeg": "https://x/el-ffmpeg.zip", "ffprobe": "https://x/el-ffprobe.zip"},
        "windows-32": {"ffmpeg": "https://x/w32-ffmpeg.zip", "ffprobe": "https://x/w32-ffprobe.zip"},
        "osx-64": {"ffmpeg": "https://x/osx-ffmpeg.zip", "ffprobe": "https://x/osx-ffprobe.zip"},
    },
}


def test_executable_name_follows_the_running_os() -> None:
    expected = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    assert executable_name("ffmpeg") == expected


def test_user_data_dir_is_under_the_home_or_env_root() -> None:
    directory = user_data_dir()
    assert directory.name == ffmpeg_setup.APP_DIR_NAME
    # A relative answer would put user data wherever the app was started
    # from -- that is a bug on every platform.
    assert directory.is_absolute()


def test_user_bin_dir_sits_inside_the_data_dir() -> None:
    assert user_bin_dir() == user_data_dir() / "bin"


def test_windows_data_dir_follows_localappdata(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(Path("X:/Users/x/AppData/Local")))
    assert user_data_dir() == Path("X:/Users/x/AppData/Local") / "FileSight"


def test_linux_data_dir_follows_xdg(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(Path.home() / "custom-share"))
    assert user_data_dir() == Path.home() / "custom-share" / "FileSight"


def test_macos_data_dir_uses_application_support(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    expected = Path.home() / "Library" / "Application Support" / "FileSight"
    assert user_data_dir() == expected


def test_search_roots_start_with_the_download_target() -> None:
    roots = search_roots()
    assert roots[0] == user_bin_dir()
    # No duplicates: probing the same directory twice only costs startup time.
    assert len(roots) == len({str(root) for root in roots})


def test_platform_keys_offer_both_macos_spellings(monkeypatch) -> None:
    # The index has used `macos-64` and `osx-64` at different times; guessing
    # one gives the user a 404 they cannot act on.
    monkeypatch.setattr(sys, "platform", "darwin")
    assert platform_keys() == ["macos-64", "osx-64"]


def test_platform_keys_pick_arm_on_arm_linux(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(ffmpeg_setup.platform, "machine", lambda: "aarch64")
    assert platform_keys()[0] == "linux-arm64"


def test_resolve_urls_falls_back_to_the_second_macos_key(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    urls, version = resolve_download_urls(CATALOG)
    # `macos-64` is absent from this catalog, so `osx-64` must be used.
    assert urls["ffmpeg"] == "https://x/osx-ffmpeg.zip"
    assert version == "6.1"


def test_resolve_urls_explains_an_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(ffmpeg_setup.platform, "machine", lambda: "riscv64")
    with pytest.raises(FFmpegDownloadError) as exc:
        resolve_download_urls({"version": "6.1", "bin": {}})
    assert "linux-64" in str(exc.value)
    assert "Settings" in str(exc.value)


def test_download_installs_both_tools(tmp_path, monkeypatch) -> None:
    archives = {
        "https://x/win-ffmpeg.zip": _zip_with(f"ffmpeg-6.1/bin/{executable_name('ffmpeg')}"),
        "https://x/win-ffprobe.zip": _zip_with(executable_name("ffprobe")),
        "https://x/lin-ffmpeg.zip": _zip_with(f"ffmpeg-6.1/bin/{executable_name('ffmpeg')}"),
        "https://x/lin-ffprobe.zip": _zip_with(executable_name("ffprobe")),
        "https://x/osx-ffmpeg.zip": _zip_with(f"ffmpeg-6.1/bin/{executable_name('ffmpeg')}"),
        "https://x/osx-ffprobe.zip": _zip_with(executable_name("ffprobe")),
    }

    def fake_urlopen(request, timeout=None):  # noqa: ARG001 - signature parity
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url not in archives:
            raise AssertionError(f"unexpected download: {url}")
        return io.BytesIO(archives[url])

    monkeypatch.setattr(ffmpeg_setup.urllib.request, "urlopen", fake_urlopen)

    stages: list[tuple[str, str]] = []
    summary = download_ffmpeg(
        target_dir=tmp_path,
        catalog=CATALOG,
        on_progress=lambda tool, stage: stages.append((tool, stage)),
    )

    for tool in ("ffmpeg", "ffprobe"):
        expected = tmp_path / executable_name(tool)
        assert summary["installed"][tool] == str(expected)
        assert expected.is_file()
        assert expected.read_bytes() == b"stub-binary"
        if os.name != "nt":
            assert os.access(expected, os.X_OK), "downloaded tool must be executable"

    assert summary["directory"] == str(tmp_path)
    assert summary["version"] == "6.1"
    assert ("ffmpeg", "downloading") in stages
    assert ("ffprobe", "extracting") in stages


def test_download_rejects_unknown_tools(tmp_path) -> None:
    with pytest.raises(FFmpegDownloadError):
        download_ffmpeg(tools=["rm"], target_dir=tmp_path, catalog=CATALOG)


def test_archive_without_the_executable_is_reported(tmp_path, monkeypatch) -> None:
    payload = _zip_with("README.txt")

    monkeypatch.setattr(
        ffmpeg_setup.urllib.request,
        "urlopen",
        lambda request, timeout=None: io.BytesIO(payload),  # noqa: ARG005
    )
    with pytest.raises(FFmpegDownloadError) as exc:
        download_ffmpeg(tools=["ffmpeg"], target_dir=tmp_path, catalog=CATALOG)
    assert executable_name("ffmpeg") in str(exc.value)


def test_extraction_ignores_archive_directories(tmp_path) -> None:
    """A member path from the archive must never build the output path.

    An entry called `../../evil/ffmpeg` has to land in the target directory
    like any other, not above it.
    """
    name = executable_name("ffmpeg")
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"../../{name}", b"stub-binary")

    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    written = ffmpeg_setup._extract_tool(archive, "ffmpeg", target_dir)
    assert written == target_dir / name
    assert written.parent == target_dir


def test_download_target_is_a_directory_resolve_tools_searches(tmp_path) -> None:
    """The download destination and the lookup list must not drift apart."""
    from filesight import video_probe

    assert user_bin_dir() in video_probe._candidate_roots()
