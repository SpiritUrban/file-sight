"""One-click FFmpeg setup and the list of places FFmpeg may live.

Requiring the user to "install FFmpeg and put it on PATH" is a wall most
people will not climb, so video support has to be one button. This module
owns both halves of that:

* :func:`search_roots` -- every directory a usable FFmpeg may already sit in,
  best candidate first. ``video_probe`` resolves through this list.
* :func:`download_ffmpeg` -- fetch static ffmpeg/ffprobe builds into a
  per-user directory and return where they landed, so the feature switches on
  without a restart and without touching anything outside the user's own
  data directory.

**Trust boundary, stated plainly:** the archives come from ffbinaries.com
over HTTPS and are not signed by us; the guarantee is transport security and
a known host, not provenance. Nothing is downloaded unless the user asks for
it, nothing is written outside the per-user data directory, and nothing is
executed by this module.

Everything here is deliberately platform-neutral in behaviour, not just in
compilation (rule 6a): paths are built with ``pathlib`` only, no separator is
ever spelled out, and no path is case-folded.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Optional

APP_DIR_NAME = "FileSight"

FFBINARIES_LATEST = "https://ffbinaries.com/api/v1/version/latest"

#: Read timeout for every network call, seconds.
NETWORK_TIMEOUT = 60

#: Refuse absurd downloads instead of filling the user's disk.
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024

TOOL_NAMES = ("ffmpeg", "ffprobe")


def executable_name(tool: str) -> str:
    """``ffmpeg`` or ``ffmpeg.exe`` depending on the running OS."""
    return f"{tool}.exe" if os.name == "nt" else tool


def user_data_dir() -> Path:
    """Per-user application data directory, by platform convention.

    Windows uses ``%LOCALAPPDATA%``, macOS ``~/Library/Application Support``,
    everything else the XDG data directory. No path is hardcoded: on a
    machine where the environment variable is missing the home directory is
    still a valid answer.
    """
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_DIR_NAME


def user_bin_dir() -> Path:
    """Where a one-click download puts the executables."""
    return user_data_dir() / "bin"


def _interpreter_roots() -> list[Path]:
    """Directories around the interpreter or the frozen worker executable.

    These only matter once the worker ships inside the desktop bundle, where
    resources land next to the executable (Windows/Linux), one level up
    (``_up_/resources`` for a sidecar), or in ``Contents/Resources`` on
    macOS. Listing them now costs nothing and means the bundled build needs
    no second lookup path.
    """
    roots: list[Path] = []
    try:
        exe_dir = Path(sys.executable).resolve().parent
    except (OSError, ValueError):  # pragma: no cover - defensive
        return roots
    roots.append(exe_dir)
    roots.append(exe_dir / "resources")
    roots.append(exe_dir / "_up_" / "resources")
    roots.append(exe_dir.parent / "Resources")
    return roots


def search_roots() -> list[Path]:
    """Every directory FFmpeg may live in, best candidate first.

    A one-click download wins: the user asked for exactly that copy. Then a
    build unpacked into the checkout (a deliberate developer choice), then
    the current directory, then the bundle layouts. ``PATH`` is consulted by
    the caller after all of these.
    """
    roots: list[Path] = [user_bin_dir()]
    try:
        # src/filesight/ffmpeg_setup.py -> <repo root>
        roots.append(Path(__file__).resolve().parents[2])
    except IndexError:  # pragma: no cover - defensive
        pass
    try:
        roots.append(Path.cwd())
    except OSError:  # pragma: no cover - defensive
        pass
    roots.extend(_interpreter_roots())

    # Keep the order, drop repeats: the same directory probed twice only
    # slows startup down.
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def platform_keys() -> list[str]:
    """Candidate ffbinaries platform keys for this machine, best first.

    Two keys are returned for macOS on purpose: the API has used both
    ``macos-64`` and ``osx-64``, and guessing wrong is a 404 the user cannot
    do anything about. Trying both costs one extra dictionary lookup.
    """
    machine = platform.machine().lower()
    sixty_four = sys.maxsize > 2**32
    if sys.platform.startswith("win"):
        return ["windows-64"] if sixty_four else ["windows-32"]
    if sys.platform == "darwin":
        return ["macos-64", "osx-64"]
    if machine in {"aarch64", "arm64"}:
        return ["linux-arm64", "linux-armhf"]
    if machine.startswith("arm"):
        return ["linux-armhf", "linux-armel"]
    return ["linux-64"] if sixty_four else ["linux-32"]


class FFmpegDownloadError(Exception):
    """The download could not be completed. Message is user-facing."""


def _fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "FileSight"})
    try:
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            payload = response.read(4 * 1024 * 1024)
    except Exception as exc:  # urllib raises a wide family of errors
        raise FFmpegDownloadError(
            f"Could not reach {url}: {exc}. Check the internet connection."
        ) from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FFmpegDownloadError(
            f"{url} did not return usable JSON ({exc})."
        ) from exc


def resolve_download_urls(catalog: Optional[dict] = None) -> tuple[dict[str, str], str]:
    """Pick the download URLs for this platform out of the ffbinaries index.

    Returns ``({tool: url}, version)``. Raises :class:`FFmpegDownloadError`
    with an actionable message when this platform is not offered.
    """
    data = catalog if catalog is not None else _fetch_json(FFBINARIES_LATEST)
    binaries = data.get("bin") or {}
    keys = platform_keys()
    for key in keys:
        entry = binaries.get(key)
        if not entry:
            continue
        urls = {tool: entry[tool] for tool in TOOL_NAMES if entry.get(tool)}
        if urls:
            return urls, str(data.get("version") or "unknown")
    raise FFmpegDownloadError(
        "No prebuilt FFmpeg is offered for this platform "
        f"(tried {', '.join(keys)}). Install FFmpeg manually and set its "
        "path in Settings."
    )


def _download_to(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "FileSight"})
    try:
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            written = 0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_ARCHIVE_BYTES:
                        raise FFmpegDownloadError(
                            f"{url} is larger than the {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB "
                            "limit; refusing to continue."
                        )
                    handle.write(chunk)
    except FFmpegDownloadError:
        raise
    except Exception as exc:
        raise FFmpegDownloadError(f"Downloading {url} failed: {exc}") from exc


def _extract_tool(archive: Path, tool: str, target_dir: Path) -> Path:
    """Pull one executable out of a zip, ignoring the archive's own layout.

    The member is matched on its file name only and written to a flat target
    directory, so a crafted archive cannot place a file outside it -- the
    archive's directory components are never used to build the output path.
    """
    wanted = executable_name(tool)
    with zipfile.ZipFile(archive) as bundle:
        member = None
        for name in bundle.namelist():
            if name.endswith("/"):
                continue
            # Zip entry names are archive-internal strings, not filesystem
            # paths: the format specifies "/", but some writers emit "\".
            # Normalizing here is the opposite of the rule-6a mistake -- it
            # never touches a real path, and `PurePosixPath` then gives the
            # same answer on every OS.
            if PurePosixPath(name.replace("\\", "/")).name == wanted:
                member = name
                break
        if member is None:
            raise FFmpegDownloadError(
                f"The downloaded archive does not contain {wanted}."
            )
        target = target_dir / wanted
        with bundle.open(member) as source, target.open("wb") as handle:
            shutil.copyfileobj(source, handle)
    if os.name != "nt":
        # Zip entries carry no usable permission bits here; without this the
        # freshly written file is not executable and every call fails with
        # "Permission denied".
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def download_ffmpeg(
    tools: Iterable[str] = TOOL_NAMES,
    target_dir: Optional[Path] = None,
    catalog: Optional[dict] = None,
    on_progress: Optional[Callable[[str, str], None]] = None,
) -> dict:
    """Download the requested tools into the per-user bin directory.

    ``catalog`` exists for tests: pass a parsed index and no network call is
    made for the lookup step.

    Returns a JSON-friendly summary: the directory, the resolved version, and
    the absolute path of every executable installed.
    """
    wanted = [tool for tool in tools if tool in TOOL_NAMES]
    if not wanted:
        raise FFmpegDownloadError(
            f"Nothing to download: expected any of {', '.join(TOOL_NAMES)}."
        )

    urls, version = resolve_download_urls(catalog)
    missing = [tool for tool in wanted if tool not in urls]
    if missing:
        raise FFmpegDownloadError(
            f"This platform's FFmpeg build does not offer {', '.join(missing)}."
        )

    directory = Path(target_dir) if target_dir is not None else user_bin_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FFmpegDownloadError(f"Cannot create {directory}: {exc}") from exc

    installed: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="filesight-ffmpeg-") as scratch:
        for tool in wanted:
            if on_progress:
                on_progress(tool, "downloading")
            archive = Path(scratch) / f"{tool}.zip"
            _download_to(urls[tool], archive)
            if on_progress:
                on_progress(tool, "extracting")
            installed[tool] = str(_extract_tool(archive, tool, directory))

    return {
        "directory": str(directory),
        "version": version,
        "source": FFBINARIES_LATEST,
        "installed": installed,
    }
