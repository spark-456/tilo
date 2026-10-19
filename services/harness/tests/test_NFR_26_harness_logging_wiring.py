"""NFR-26 wiring in tilo-harness: `run_plan` takes its writer by keyword only (the log binding reads it from the
keyword arguments), and importing the service app makes the deployed harness log JSON."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys

from tilo_harness.executor import run_plan


def test_NFR_26_run_plan_writer_is_keyword_only_so_the_log_binding_cannot_miss_it() -> None:
    assert inspect.signature(run_plan).parameters["writer"].kind is inspect.Parameter.KEYWORD_ONLY


def test_NFR_26_importing_the_harness_app_makes_it_log_json_by_default() -> None:
    env = {k: v for k, v in os.environ.items() if k not in {"K_SERVICE", "CLOUD_RUN_JOB"}}
    code = "import logging, tilo_harness.app\nlogging.getLogger('nfr26.boot').warning('nfr26 harness boot')"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    lines = [ln for ln in (done.stdout + done.stderr).splitlines() if "nfr26 harness boot" in ln]
    assert lines, f"the record never reached stdout or stderr: {done.stderr[-300:]}"
    rec = json.loads(lines[0])
    assert rec["severity"] == "WARNING" and rec["message"] == "nfr26 harness boot"
