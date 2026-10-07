"""`running_emulator()`: a context manager over the Firestore emulator (ADR-0003: local-first,
no cloud credentials). Reuses `FIRESTORE_EMULATOR_HOST` when it is already set (another process,
or an earlier fixture in this session, owns the emulator); otherwise starts one through
firebase-tools (a pinned root devDependency, run with `pnpm exec`) on a free port -- never 8080,
which `tilo-api`'s dev server uses -- waits until it answers, sets `FIRESTORE_EMULATOR_HOST`,
yields the host, and stops it on exit. Java, needed by the emulator binary itself, is assumed
already installed (root CLAUDE.md).

`_stop()` cleanly kills the whole node+java tree on a graceful exit (`finally`), but a *hard*
kill of the Python process that owns the emulator (`python -m tilo_harness.skeleton` run with no
`FIRESTORE_EMULATOR_HOST` already set, i.e. exactly `just harness-skeleton`, killed with e.g.
`taskkill /F` or a SIGKILL-equivalent) never runs that `finally` block at all, so `_stop()` never
runs and the java emulator (and the websocket port it holds) leaks. On win32 this is closed with
a Job Object carrying
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: the node process (and, transitively, the java process it
spawns as a child -- child processes join their parent's job by default) is assigned to that job
right after it is started, and the OS itself terminates every process still in the job the
instant every handle to it closes, which happens automatically when this Python process dies for
*any* reason, including a hard kill that skips every `finally`. This is a backstop on top of
`_stop()`, not a replacement for it.
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
from collections.abc import Iterator, Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
_DEMO_PROJECT = "demo-tilo"
_READY_TIMEOUT_S = 240.0  # a cold start of the emulator takes about 2.5 minutes
_READY_TIMEOUT_ENV = "TILO_EMULATOR_READY_TIMEOUT_S"


def ready_timeout_s(env: Mapping[str, str] | None = None) -> float:
    """The ready timeout: `TILO_EMULATOR_READY_TIMEOUT_S` when it is a finite number above zero, else the default."""
    raw = (os.environ if env is None else env).get(_READY_TIMEOUT_ENV)
    try:
        value = float(raw) if raw is not None else _READY_TIMEOUT_S
    except ValueError:
        return _READY_TIMEOUT_S
    return value if 0 < value < float("inf") else _READY_TIMEOUT_S


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JobObjectExtendedLimitInformation = 9
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Explicit prototypes: ctypes' default argument/return conversion for an undeclared function
    # is 32-bit `c_int`, which silently truncates a 64-bit HANDLE. Declaring these removes any
    # dependence on that default rather than relying on it happening to work.
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_void_p),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    def _create_kill_on_close_job() -> wintypes.HANDLE:
        """A Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` set: every process assigned to
        it is terminated by the OS the instant the last handle to the job closes, which Windows
        does automatically when the process holding that handle (this one) exits for any
        reason -- including a hard kill that runs no Python cleanup code at all."""
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            job,
            _JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            _kernel32.CloseHandle(job)
            raise ctypes.WinError(ctypes.get_last_error())
        return job

    def _assign_to_job(job: wintypes.HANDLE, process: subprocess.Popen[bytes]) -> None:
        # subprocess.Popen exposes the raw Win32 process handle as `_handle` on win32; there is
        # no public equivalent. Assigning right after Popen() returns, before the child (node)
        # has had time to itself spawn java, so java -- created by a process already in the
        # job -- joins the same job automatically (default job policy denies breakaway).
        ok = _kernel32.AssignProcessToJobObject(job, int(process._handle))  # type: ignore[attr-defined]  # noqa: SLF001
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())


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
        # Backstop for a hard kill of *this* process (see the module docstring): on win32 only,
        # since `start_new_session` above already gives POSIX a process group `_stop()` can
        # SIGKILL, which survives this process dying uncleanly -- win32 has no equivalent short
        # of a Job Object.
        if sys.platform == "win32":
            job = _create_kill_on_close_job()
            _assign_to_job(job, process)
        try:
            _wait_until_ready(host, ready_timeout_s())
            os.environ["FIRESTORE_EMULATOR_HOST"] = host
            yield host
        finally:
            os.environ.pop("FIRESTORE_EMULATOR_HOST", None)
            _stop(process)
            if sys.platform == "win32":
                _kernel32.CloseHandle(job)
