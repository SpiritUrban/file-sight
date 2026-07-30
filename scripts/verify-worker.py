#!/usr/bin/env python
"""Prove a frozen worker actually works, not merely that it linked.

    python scripts/verify-worker.py [path-to-executable] [--preload] [--scan DIR]

A PyInstaller build that reports success can still fail at run time in ways
nothing else catches:

* a module reached only through a runtime import is missing, and the process
  dies in a child with no console;
* a native extension imports fine standalone but deadlocks once stdio is a
  pipe -- the failure this project already hit, and the reason the worker is
  started with ``--preload``;
* the protocol works but the environment probe reports the frozen build as
  something it is not.

So the checks here speak the real JSON-Lines protocol over real pipes, with a
timeout, which is exactly how the desktop app talks to it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT = (
    REPO_ROOT
    / "desktop"
    / "src-tauri"
    / "resources"
    / "filesight-worker"
    / ("filesight-worker.exe" if os.name == "nt" else "filesight-worker")
)


class Worker:
    """The desktop app's side of the conversation, in miniature."""

    def __init__(self, executable: Path, preload: bool) -> None:
        command = [str(executable)]
        if preload:
            command.append("--preload")
        creation = 0
        if os.name == "nt":
            creation = 0x0800_0000  # CREATE_NO_WINDOW, as the app does
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            creationflags=creation,
        )
        self.events: Queue = Queue()
        self.logs: list[str] = []
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        for raw in self.process.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                self.events.put(json.loads(line))
            except json.JSONDecodeError:
                self.events.put({"event": "__unparseable__", "raw": line})

    def _read_stderr(self) -> None:
        for raw in self.process.stderr:
            self.logs.append(raw.decode("utf-8", "replace").rstrip())

    def send(self, request_id: str, command: str, payload: dict | None = None) -> None:
        line = json.dumps(
            {"request_id": request_id, "command": command, "payload": payload or {}}
        )
        self.process.stdin.write((line + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def await_terminal(self, request_id: str, timeout: float) -> dict | None:
        """Wait for the completed/error event of one request."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=0.5)
            except Empty:
                if self.process.poll() is not None:
                    return None
                continue
            if event.get("request_id") != request_id:
                continue
            if event.get("event") in ("completed", "error", "benchmark_completed"):
                return event
        return None

    def close(self) -> None:
        try:
            self.send("bye", "shutdown")
            self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", nargs="?", default=str(DEFAULT))
    # --preload is the default because it is what the app does, and because
    # WITHOUT it the worker deadlocks on Windows the first time anything
    # imports torch: the loader lock is held while the reader thread sits in a
    # stdin read. Verifying the non-preload path would only reproduce a known
    # design constraint.
    parser.add_argument(
        "--no-preload",
        dest="preload",
        action="store_false",
        help="start without --preload (expect a deadlock on Windows)",
    )
    parser.add_argument("--scan", help="also scan this directory end to end")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.set_defaults(preload=True)
    args = parser.parse_args()

    executable = Path(args.executable)
    if not executable.is_file():
        print(f"not found: {executable}", file=sys.stderr)
        print("Build it first: python scripts/build-worker.py", file=sys.stderr)
        return 2

    print(f"executable : {executable}")
    print(f"preload    : {args.preload}")

    failures: list[str] = []
    started = time.perf_counter()
    worker = Worker(executable, preload=args.preload)

    try:
        # 1. ping. If this hangs, the protocol never starts -- the classic
        #    symptom of a native extension deadlocking behind a pipe.
        worker.send("p1", "ping")
        pong = worker.await_terminal("p1", args.timeout)
        if pong is None:
            failures.append("ping never answered (worker dead or deadlocked)")
        elif pong["event"] != "completed" or not pong["data"].get("pong"):
            failures.append(f"ping answered oddly: {pong}")
        else:
            print(f"ping       : ok, version {pong['data'].get('version')}")

        # 2. the environment probe: what the app shows in its status bar.
        worker.send("e1", "get_environment")
        env = worker.await_terminal("e1", args.timeout)
        if env is None or env["event"] != "completed":
            failures.append(f"get_environment failed: {env}")
        else:
            data = env["data"]
            print(f"python     : {data['python']['version']} (frozen interpreter)")
            print(f"core       : {data['filesight']['version']}")
            print(f"ffmpeg     : {'ready' if data['ffmpeg']['available'] else 'not found'}")
            backends = data.get("inference", {}).get("backends", [])
            usable = [b["backend_id"] for b in backends if b.get("can_caption")]
            print(f"can caption: {', '.join(usable) if usable else 'NOTHING'}")
            if not usable:
                failures.append(
                    "no backend can caption -- the frozen build cannot analyse "
                    "anything, which is the whole point of it"
                )

        # 2b. Does a caption backend actually LOAD?
        #
        # `can_caption` above only says "the runtime and the model files are
        # present". It said yes on a build whose every caption path was broken
        # by a packaging fault, and this script reported success. A self-test
        # runs the real model on a real image, which is the only claim worth
        # making about a frozen bundle.
        worker.send("t1", "test_backend", {"backend": "auto"})
        diag = worker.await_terminal("t1", max(args.timeout, 300))
        if diag is None or diag["event"] != "completed":
            failures.append(f"backend self-test never finished: {diag}")
        else:
            d = diag["data"]
            print(
                f"self-test  : {d.get('backend_id')} -> "
                f"{'passed' if d.get('self_test_passed') else 'FAILED'}"
                + (f" ({d['inference_ms']} ms)" if d.get("inference_ms") else "")
            )
            if not d.get("self_test_passed"):
                failures.append(
                    f"backend {d.get('backend_id')} cannot caption in the frozen "
                    f"build: {d.get('error')}"
                )

        # 3. profiles and config: they exercise the packaged data files that a
        #    frozen build silently drops.
        worker.send("g1", "get_profiles")
        profiles = worker.await_terminal("g1", args.timeout)
        if profiles is None or profiles["event"] != "completed":
            failures.append(f"get_profiles failed: {profiles}")
        else:
            names = [p["name"] for p in profiles["data"]["profiles"]]
            print(f"profiles   : {', '.join(names[:6])}")
            if "default" not in names:
                failures.append("built-in profiles are missing from the bundle")

        # 4. optional full scan: the only check that proves captioning works.
        if args.scan:
            print(f"scanning   : {args.scan} (may download the model)")
            # Not `max_files: 1`: files are scanned in name order, and one
            # unlucky file (a deliberately corrupt fixture, a stray icon)
            # would then be the entire sample and the check would blame the
            # bundle for it.
            worker.send("s1", "scan", {"directory": args.scan, "max_files": 4})
            result = worker.await_terminal("s1", max(args.timeout, 900))
            if result is None or result["event"] != "completed":
                failures.append(f"scan failed: {result}")
            else:
                data = result["data"]
                processed = data.get("processed", 0)
                print(
                    f"scan       : {processed} processed, {data.get('failed', 0)} failed, "
                    f"{data.get('total', 0)} total"
                )
                # A scan that captions nothing "succeeds" -- it is a valid
                # answer for an empty folder, and a useless one for a build
                # check. The point of --scan is to prove the model runs.
                if processed == 0:
                    failures.append(
                        "the scan processed no files: either the folder holds no "
                        "media, or the frozen build cannot caption"
                    )
                # Individual files are allowed to fail -- a corrupt image must
                # never stop a scan, and the test fixtures include one on
                # purpose. What must not happen is nothing succeeding.
                if data.get("failed"):
                    print(
                        f"             note: {data['failed']} file(s) failed, which is "
                        "expected if the folder contains a corrupt one"
                    )
                report_path = data.get("report_path")
                if report_path:
                    print(f"report     : {report_path}")
                    try:
                        report = json.loads(Path(report_path).read_text("utf-8"))
                        for entry in report.get("files", [])[:3]:
                            print(
                                f"             {entry.get('status')}: "
                                f"{entry.get('suggested_name')}"
                            )
                    except Exception as exc:
                        failures.append(f"report unreadable: {exc}")
    finally:
        worker.close()

    print(f"elapsed    : {time.perf_counter() - started:.0f}s")
    if worker.logs:
        print("\nworker stderr (last 15 lines):")
        for line in worker.logs[-15:]:
            print(f"  {line}")

    # The worker keeps running after a preload failure -- deliberately, since
    # the light commands still work. That is right for a user and wrong for a
    # build check: a bundle whose model never loads must not pass.
    broken = [line for line in worker.logs if "failed" in line.lower()]
    if broken:
        failures.append(
            "the worker logged failures during startup: " + " | ".join(broken[:3])
        )

    if failures:
        print("\nFAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
