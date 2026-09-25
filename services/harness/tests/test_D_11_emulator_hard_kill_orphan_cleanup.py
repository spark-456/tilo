"""D-11 fix round 3, qa-breaker's second finding: hard-killing `python -m tilo_harness.skeleton`
while it owns its own emulator (`FIRESTORE_EMULATOR_HOST` unset -- exactly `just
harness-skeleton`) left the java Firestore emulator process, and the websocket port it holds,
running behind: `_stop()`'s cleanup only ever runs from a `finally` block, and a hard kill (no
`/T`, no SIGTERM, no Python-level cleanup at all) never reaches it.

`running_emulator()`'s backstop for this is a win32 Job Object carrying
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (`_create_kill_on_close_job`/`_assign_to_job`): it does not
depend on any code running in the dying process, so it is exercised here directly against a
throwaway long-running child (`ping -t`) rather than the real firebase/java stack --
test_D_11_emulator_kill_and_takeover.py and test_PRD_15_3_emulator_skeleton_run.py already cover
the graceful `_stop()` path against that real stack, and standing it up a second time just to
prove an unrelated OS-level mechanism would only add flakiness.

win32-only: POSIX's backstop is `start_new_session=True` + `_stop()`'s `os.killpg(...,
SIGKILL)`, which needs no such mechanism because a whole process *group* can be signalled from
outside even after the group leader has already died.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the Job Object backstop is win32-only (see the module docstring)",
)

_CHILD_SCRIPT = """
import subprocess, sys, time
sys.path.insert(0, {src_path!r})
from tilo_harness.emulator import _assign_to_job, _create_kill_on_close_job

proc = subprocess.Popen(["ping", "-t", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
job = _create_kill_on_close_job()
_assign_to_job(job, proc)
print(proc.pid, flush=True)
while True:
    time.sleep(1)
"""


def _process_alive(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return str(pid) in result.stdout


def test_D_11_hard_killing_the_owning_process_still_reaps_a_job_assigned_child(repo_root) -> None:
    src_dir = str(repo_root / "services/harness/src")
    script = _CHILD_SCRIPT.format(src_path=src_dir)
    owner = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        child_pid_line = owner.stdout.readline()
        assert child_pid_line.strip(), f"owning process never printed the child pid, stderr:\n{owner.stderr.read()}"
        child_pid = int(child_pid_line.strip())
        assert _process_alive(child_pid), "the child (ping) must be running before the hard kill"

        # Popen.kill() on win32 calls TerminateProcess directly -- exactly a hard kill, no
        # SIGTERM, no atexit, no `finally` in the owning process. The owner here plays the role
        # `python -m tilo_harness.skeleton` plays when it owns its own emulator; the child plays
        # the java emulator process node spawns.
        owner.kill()
        owner.wait(timeout=15)

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and _process_alive(child_pid):
            time.sleep(0.3)

        assert not _process_alive(child_pid), (
            "D-11: a Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE must terminate the "
            "assigned child once the owning process's last handle to the job closes, even when "
            "the owning process is hard-killed and runs no cleanup of its own"
        )
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=15)
