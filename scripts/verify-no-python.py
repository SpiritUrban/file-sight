#!/usr/bin/env python
"""Prove the bundled worker runs on a machine with no Python.

    python scripts/verify-no-python.py <path to installed FileSight folder>

The claim "the installer needs no Python" cannot be checked on a developer
machine by simply launching the app: Python is on PATH, a virtualenv sits in
the checkout, and either one would be picked up and make a broken bundle look
fine. So this script does the opposite of a normal run -- it removes every
way to find an interpreter, then starts the *bundled* worker and talks to it:

* ``PATH`` is emptied of everything except the Windows system directories,
  which contain no Python;
* ``PYTHONHOME``, ``PYTHONPATH`` and ``VIRTUAL_ENV`` are cleared, so a stray
  environment variable cannot smuggle one in;
* the working directory is somewhere with no checkout above it, so the
  project-virtualenv path cannot resolve either.

If the worker answers under those conditions, it is genuinely self-contained.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKER_NAME = "filesight-worker.exe" if os.name == "nt" else "filesight-worker"


def stripped_environment() -> dict[str, str]:
    """A copy of the environment with every route to an interpreter removed."""
    env = {k: v for k, v in os.environ.items()}
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX"):
        env.pop(name, None)

    if os.name == "nt":
        system_root = env.get("SystemRoot", "C:\\Windows")
        keep = [
            system_root,
            str(Path(system_root) / "system32"),
            str(Path(system_root) / "System32" / "Wbem"),
        ]
    else:
        keep = ["/usr/bin", "/bin"]
    env["PATH"] = os.pathsep.join(keep)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def find_worker(root: Path) -> Path | None:
    direct = root / "filesight-worker" / WORKER_NAME
    if direct.is_file():
        return direct
    matches = sorted(root.rglob(WORKER_NAME))
    return matches[0] if matches else None


def main() -> int:
    # Windows consoles default to cp1252, and the worker's stderr contains
    # characters it cannot encode; printing one must never be what fails a
    # check that has otherwise passed.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover
            pass

    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    worker = find_worker(root)
    if worker is None:
        print(f"no {WORKER_NAME} found under {root}", file=sys.stderr)
        print(
            "The installer did not carry the frozen worker: check that\n"
            "tauri.windows.conf.json maps resources/filesight-worker.",
            file=sys.stderr,
        )
        return 1

    print(f"worker     : {worker}")
    env = stripped_environment()
    print(f"PATH       : {env['PATH']}")

    # Sanity check the check: if an interpreter is still reachable, a pass
    # here would prove nothing at all.
    leaked = shutil.which("python", path=env["PATH"]) or shutil.which(
        "python3", path=env["PATH"]
    )
    if leaked:
        print(f"the stripped PATH still resolves python: {leaked}", file=sys.stderr)
        return 1
    print("python     : not reachable (as intended)")

    creation = 0x0800_0000 if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="filesight-nopython-") as cwd:
        process = subprocess.Popen(
            [str(worker), "--preload"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,  # no checkout above this, so no project venv either
            creationflags=creation,
        )
        try:
            request = json.dumps(
                {"request_id": "n1", "command": "ping", "payload": {}}
            )
            process.stdin.write((request + "\n").encode("utf-8"))
            process.stdin.flush()

            answer = None
            for _ in range(50):
                raw = process.stdout.readline()
                if not raw:
                    break
                try:
                    event = json.loads(raw.decode("utf-8", "replace").strip())
                except json.JSONDecodeError:
                    continue
                if event.get("request_id") == "n1":
                    answer = event
                    break
        finally:
            try:
                process.stdin.close()
            except Exception:
                pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()

    if answer is None:
        print("\nFAILED: the bundled worker did not answer without Python", file=sys.stderr)
        stderr = process.stderr.read().decode("utf-8", "replace")
        for line in stderr.strip().splitlines()[-10:]:
            print(f"  {line}", file=sys.stderr)
        return 1

    data = answer.get("data", {})
    print(f"ping       : {answer.get('event')}, version {data.get('version')}")
    if answer.get("event") != "completed" or not data.get("pong"):
        print("\nFAILED: unexpected answer", file=sys.stderr)
        return 1

    print("\nthe installed worker runs with no Python anywhere on PATH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
