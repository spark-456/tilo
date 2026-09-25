"""`running_emulator()`: a context manager over the Firestore emulator (ADR-0003: local-first,
no cloud credentials). Reuses `FIRESTORE_EMULATOR_HOST` when it is already set (another process,
or an earlier fixture in this session, owns the emulator); otherwise starts one through
firebase-tools (a pinned root devDependency, run with `pnpm exec`) on a free port -- never 8080,
which `tilo-api`'s dev server uses -- waits until it answers, sets `FIRESTORE_EMULATOR_HOST`,
yields the host, and stops it on exit. Java, needed by the emulator binary itself, is assumed
already installed (root CLAUDE.md).
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
_DEMO_PROJECT = "demo-tilo"
_READY_TIMEOUT_S = 120.0


def _free_port() -> int:
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port != 8080:
            return port


def _wait_until_ready(host: str, timeout_s: float) -> None:
    hostname, _, port = host.partition(":")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection(hostname, int(port), timeout=2)
            try:
                conn.request("GET", "/")
                conn.getresponse()
            finally:
                conn.close()
            return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"Firestore emulator did not answer on {host} within {timeout_s}s")


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Stops the whole process tree: firebase-tools (node) spawns the emulator (java) as a
    child, and terminating only the node process leaves the java emulator running behind."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process.wait(timeout=15)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=15)


@contextlib.contextmanager
def running_emulator() -> Iterator[str]:
    existing = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if existing:
        yield existing
        return

    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError("running_emulator(): pnpm not found on PATH")

    port = _free_port()
    host = f"127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="tilo-firestore-emulator-") as tmp:
        config_path = Path(tmp) / "firebase.json"
        config_path.write_text(
            json.dumps(
                {
                    "firestore": {},
                    "emulators": {
                        "firestore": {"host": "127.0.0.1", "port": port},
                        "ui": {"enabled": False},
                    },
                }
            ),
            encoding="utf-8",
        )
        process = subprocess.Popen(
            [
                pnpm,
                "exec",
                "firebase",
                "-c",
                str(config_path),
                "emulators:start",
                "--only",
                "firestore",
                "--project",
                _DEMO_PROJECT,
                "--non-interactive",
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
        )
        try:
            _wait_until_ready(host, _READY_TIMEOUT_S)
            os.environ["FIRESTORE_EMULATOR_HOST"] = host
            yield host
        finally:
            os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
            _stop(process)
