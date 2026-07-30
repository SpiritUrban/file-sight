#!/usr/bin/env python
"""Freeze the Python worker into a standalone folder with PyInstaller.

Why this exists: the desktop app spawns the analysis core as a child process.
Without a frozen copy the installer cannot work on a machine that has no
Python, which is the single biggest barrier to actually using FileSight.

    python scripts/build-worker.py [--clean] [--output DIR]

Output: ``<output>/filesight-worker/filesight-worker[.exe]`` plus its
dependencies, ready to be handed to Tauri as a bundled resource.

Deliberate choices, each with a reason:

* **one-folder, not one-file.** A one-file build unpacks several hundred
  megabytes of native libraries into a temp directory on *every* start. That
  is slow, it multiplies disk use, and it is a reliable way to earn an
  antivirus false positive.
* **model weights are NOT frozen in.** They are ~1 GB and change
  independently of the code; they are downloaded on first analysis and cached
  in the user's Hugging Face cache, exactly as they are today.
* **no UPX.** Compressing native ML libraries saves little and breaks some of
  them outright.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY = REPO_ROOT / "scripts" / "worker_entry.py"
NAME = "filesight-worker"

# Windows refuses paths over 260 characters unless long-path support is
# enabled system-wide, which an installer cannot rely on. Everything below
# keeps the bundle comfortably inside that budget, and the build fails loudly
# if it does not -- a truncated copy would only break on a user's machine.
MAX_WINDOWS_PATH = 250

# Directories that exist for building C++ extensions or for torch's own test
# suite. Several tens of megabytes, never read at run time.
PRUNE_DIRS = [
    "torch/include",
    "torch/test",
    "torch/utils/bottleneck",
    "torch/utils/tensorboard",
]

# Modules the worker reaches only through a runtime import, so PyInstaller's
# static analysis cannot see them. Anything missing here shows up as an
# ImportError at run time, in a child process, with no console -- i.e. as
# "the worker will not start" and nothing else. Keep the list explicit.
HIDDEN_IMPORTS = [
    # Backends are constructed by id from a registry.
    "filesight.inference.pytorch_cpu",
    "filesight.inference.onnx_backends",
    "filesight.inference.onnx_caption",
    "filesight.inference.captioner_adapter",
    "filesight.captioner",
    # transformers resolves model classes by name at run time.
    "transformers.models.blip",
    "transformers.models.blip.modeling_blip",
    "transformers.models.blip.processing_blip",
    "transformers.models.blip.image_processing_blip",
    "transformers.models.bert.tokenization_bert",
    # Pillow codecs.
    "PIL.Image",
    "PIL.ImageFile",
    "PIL.JpegImagePlugin",
    "PIL.PngImagePlugin",
    "PIL.WebPImagePlugin",
    "PIL.BmpImagePlugin",
    "PIL.TiffImagePlugin",
]

# Whole packages whose data files and submodules must come along. `transformers`
# is a plugin registry pretending to be a library: its config files and lazy
# module map are data, not code, and dropping them turns a working model into
# "Unrecognized model type".
COLLECT_ALL = ["transformers", "tokenizers", "safetensors"]

# Cutting these out is where the size saving is. Each one is a heavyweight
# dependency that the caption path never touches; leaving them in roughly
# doubles the bundle. If a future feature needs one, remove it from here --
# do not add a workaround.
# Only whole third-party packages that torch and transformers do not import
# on any path we use. Excluding *submodules of torch* is a trap: `sympy` and
# `torch.distributed` were on this list, and `torch.utils.data.dataloader`
# imports `torch.distributed` unconditionally, so transformers failed to load
# any model at all -- reported as "Could not import module 'BlipProcessor'",
# which names the wrong package entirely. If the size ever has to come down,
# take it out of the model, not out of torch.
EXCLUDES = [
    "tkinter",
    "matplotlib",
    "pandas",
    "IPython",
    "notebook",
    "jupyter",
    "pytest",
    "torchvision",
    "torchaudio",
    "onnx",            # the ONNX exporter, not onnxruntime
]


def human(bytes_: int) -> str:
    return f"{bytes_ / 1048576:.0f} MB"


def tree_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def flatten_license_trees(root: Path) -> tuple[int, int]:
    """Move nested third-party licence texts into one shallow folder.

    PyInstaller copies each package's whole ``dist-info``, and torch's holds
    107 licence files nested up to 144 characters deep (`third_party/kineto/
    libkineto/third_party/dynolog/...`). Added to an installation path that is
    itself long, that blows past Windows' 260-character limit and the build
    dies with WinError 206.

    These files are licence *texts*, not code: torch is redistributed on the
    condition that they travel with it, so deleting them is not an option.
    They are moved instead -- flattened into ``third-party-licenses/`` with
    sequential names, and ``INDEX.txt`` records which original path each one
    came from, so attribution survives intact and every path gets short.
    """
    destination = root / "third-party-licenses"
    index: list[str] = []
    moved = 0

    for dist_info in sorted(root.rglob("*.dist-info")):
        licenses = dist_info / "licenses"
        if not licenses.is_dir():
            continue
        package = dist_info.name.split("-")[0]
        for path in sorted(p for p in licenses.rglob("*") if p.is_file()):
            relative = path.relative_to(licenses).as_posix()
            # A short, collision-free name: the mapping lives in INDEX.txt.
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / f"{moved:04d}.txt"
            shutil.move(str(path), str(target))
            index.append(f"{target.name}  {package}: {relative}")
            moved += 1
        shutil.rmtree(licenses, ignore_errors=True)

    if moved:
        header = (
            "Third-party licence texts bundled with the FileSight worker.\n"
            "Each file below is an unmodified copy; the original path inside\n"
            "the upstream package follows the file name.\n\n"
        )
        (destination / "INDEX.txt").write_text(
            header + "\n".join(index) + "\n", encoding="utf-8"
        )
    return moved, len(index)


def prune(root: Path) -> int:
    """Delete build-time-only directories. Returns bytes reclaimed."""
    reclaimed = 0
    for relative in PRUNE_DIRS:
        for base in (root, root / "_internal"):
            target = base / relative
            if target.is_dir():
                reclaimed += tree_size(target)
                shutil.rmtree(target, ignore_errors=True)
    return reclaimed


def longest_path(root: Path, install_prefix_length: int) -> tuple[int, Path | None]:
    """Longest path this bundle would occupy once installed."""
    worst = 0
    worst_path: Path | None = None
    for path in root.rglob("*"):
        length = install_prefix_length + len(str(path.relative_to(root)))
        if length > worst:
            worst, worst_path = length, path
    return worst, worst_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "desktop" / "src-tauri" / "resources"),
        help="directory the worker folder is written into",
    )
    parser.add_argument(
        "--clean", action="store_true", help="discard PyInstaller's cache first"
    )
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "PyInstaller is not installed. Install it with:\n"
            '  pip install "pyinstaller>=6.10"',
            file=sys.stderr,
        )
        return 2

    # Fail early and clearly: a frozen worker without these is useless, and
    # PyInstaller would otherwise produce a build that dies at run time.
    missing = []
    for module in ("torch", "transformers", "PIL", "typer", "numpy"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        print(
            f"missing runtime dependencies: {', '.join(missing)}\n"
            "Build from the environment the app actually uses:\n"
            '  pip install torch --index-url https://download.pytorch.org/whl/cpu\n'
            '  pip install -e ".[dev]"',
            file=sys.stderr,
        )
        return 2

    output = Path(args.output).resolve()
    # Built in a short temp directory, not straight into the repository: the
    # repo path here is 79 characters before the bundle even starts, and
    # torch's nested licence tree needs another ~200. PyInstaller would fail
    # mid-write. After flattening, the result fits anywhere.
    staging = Path(tempfile.gettempdir()) / "fsw-build"
    shutil.rmtree(staging, ignore_errors=True)
    work = staging / "work"
    dist = staging / "dist"

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(ENTRY),
        "--name",
        NAME,
        "--onedir",
        "--noconfirm",
        "--console",  # a GUI-subsystem build has no usable stdio, and stdio IS the protocol
        "--noupx",
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(work),
        "--paths",
        str(REPO_ROOT / "src"),
        "--log-level",
        "WARN",
    ]
    if args.clean:
        command.append("--clean")
    for name in HIDDEN_IMPORTS:
        command += ["--hidden-import", name]
    for name in COLLECT_ALL:
        command += ["--collect-all", name]
    for name in EXCLUDES:
        command += ["--exclude-module", name]

    staged = dist / NAME
    print(f"building {NAME} in {staging}")
    started = time.perf_counter()
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        print(f"PyInstaller failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode

    raw_size = tree_size(staged)

    reclaimed = prune(staged)
    moved, _ = flatten_license_trees(staged)
    print(
        f"pruned {human(reclaimed)} of build-only files; "
        f"flattened {moved} third-party licence texts"
    )

    # The prefix a real installation adds, measured rather than guessed:
    # C:\Users\<name>\AppData\Local\FileSight\resources\filesight-worker\ is
    # about 70 characters; 110 is a deliberately pessimistic allowance.
    worst, worst_path = longest_path(staged, install_prefix_length=110)
    print(f"longest installed path: ~{worst} characters")
    if worst > MAX_WINDOWS_PATH:
        print(
            f"path too long for Windows: {worst} > {MAX_WINDOWS_PATH}\n  {worst_path}",
            file=sys.stderr,
        )
        return 1

    target = output / NAME
    output.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(staged), str(target))
    shutil.rmtree(staging, ignore_errors=True)

    executable = target / (f"{NAME}.exe" if os.name == "nt" else NAME)
    if not executable.is_file():
        print(f"build reported success but {executable} is missing", file=sys.stderr)
        return 1

    final = tree_size(target)
    print(
        f"\nbuilt in {time.perf_counter() - started:.0f}s: {human(final)} in "
        f"{sum(1 for _ in target.rglob('*'))} files "
        f"(from {human(raw_size)} before pruning)"
    )
    print(f"executable: {executable}")
    print(
        "\nThis proves it links, not that it runs. Verify with:\n"
        "  python scripts/verify-worker.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
