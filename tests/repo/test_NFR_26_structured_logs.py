"""NFR-26 (PRD 17.2): "Structured logs with run, world and trace ids" (first half; the runbook is
tests/repo/test_NFR_26_runbook.py, the harness half is services/harness/tests/test_NFR_26_harness_run_logs.py).

The PRD names no field names, so these defaults are pinned here (builder: change them only with an ADR):

* Shape: one JSON object per line on stdout or stderr (Cloud Run ships both to Cloud Logging). Cloud Logging reads
  `severity` and `message` natively, the same two keys `tilo_metering.cost_alerts` (NFR-27) already writes. Severity
  is the Python level name (INFO, WARNING, ERROR, CRITICAL).
* Ids: `run_id` and `world_id` keys. Trace id: the Cloud Logging key `logging.googleapis.com/trace`, because that is
  the one field that links a log line to its Cloud Trace span (PRD 6: "Cloud Logging, Monitoring, Trace"). Cloud Run
  adds `X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=1` to every request, so that header is the source (`traceparent` is
  not pinned). The value is `projects/<project>/traces/<TRACE_ID>` or the bare trace id: it must end with TRACE_ID.
* tilo-api: `world_id` comes from the request path `/worlds/{world_id}/...`; `run_id` is the world's `run_id` in the
  `deps.Store` ("tilo-api reads this, never invents it"). An unknown world has no run id. No header, no trace key.
* Outside any request or run: no id keys at all (absent, never null, "unknown" or "-"): no made-up ids.
* The formatter adds nothing secret: no header, token, cookie or e-mail address is ever copied into a line (PRD 16:
  secrets never enter logs).
* Neutral shared place: a workspace package imported as `tilo_logging` (suggested path `packages/logging`), with one
  public function `configure_logging(stream=None, level=logging.INFO)`: it leaves exactly one JSON handler on the
  root logger, writing to `stream` (default stdout). Importing a service app (`tilo_api`) calls it, so a deployed
  service logs JSON with no further setup. Binding ids is internal: the tests only observe lines.

Fails today with ModuleNotFoundError: tilo_logging does not exist.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import pathlib
import secrets
import subprocess
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_api import app, deps
from tilo_logging import configure_logging

TRACE_KEY = "logging.googleapis.com/trace"
TRACE_ID = "105445aa7843bc8bf206b12000100000"
WORLD, RUN = "w_nfr26_world", "r_nfr26_run"
PROBE = "nfr26 probe hello"
ID_KEYS = ("run_id", "world_id", TRACE_KEY)
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def _configured(stream: io.StringIO):
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        configure_logging(stream=stream)
        yield
    finally:
        root.handlers[:], root.level = handlers, level


def _lines(stream: io.StringIO) -> list[dict]:
    out = [line for line in stream.getvalue().split("\n") if line.strip()]
    return [json.loads(line) for line in out]  # every line must be JSON: a plain-text line is a failure


def _one(stream: io.StringIO, message: str) -> dict:
    found = [r for r in _lines(stream) if r.get("message") == message]
    assert len(found) == 1, f"expected exactly one JSON line with message {message!r}, got {len(found)}"
    return found[0]


@pytest.fixture
def buf(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("K_SERVICE", raising=False)  # not deployed: no SEC-15 gate in front of the probe route
    stream = io.StringIO()
    with _configured(stream):
        yield stream


@pytest.fixture
def client(buf):
    from fastapi.testclient import TestClient

    store = deps.Store(worlds={WORLD: deps.WorldRecord(owner="u_owner", districts={}, run_id=RUN)})

    def probe(world_id: str) -> dict:
        logging.getLogger("nfr26.probe").warning("nfr26 probe %s", "hello")  # a record emitted inside the request
        return {}

    app.dependency_overrides[deps.get_store] = lambda: store
    app.add_api_route("/worlds/{world_id}/nfr26-probe", probe, methods=["GET"])
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.router.routes.pop()
        app.dependency_overrides.pop(deps.get_store, None)


def test_NFR_26_api_request_log_is_one_json_line_with_severity_message_run_world_and_trace_ids(client, buf) -> None:
    client.get(f"/worlds/{WORLD}/nfr26-probe", headers={"X-Cloud-Trace-Context": f"{TRACE_ID}/1;o=1"})
    rec = _one(buf, PROBE)
    assert rec["severity"] == "WARNING"
    assert (rec["run_id"], rec["world_id"]) == (RUN, WORLD)
    assert rec[TRACE_KEY].endswith(TRACE_ID) and not rec[TRACE_KEY].endswith("o=1")


def test_NFR_26_request_without_trace_header_or_known_world_gets_no_made_up_ids(client, buf) -> None:
    client.get(f"/worlds/{WORLD}/nfr26-probe")
    assert TRACE_KEY not in _one(buf, PROBE)
    buf.seek(0)
    buf.truncate(0)
    client.get("/worlds/w_nfr26_unknown/nfr26-probe")
    rec = _one(buf, PROBE)
    assert rec["world_id"] == "w_nfr26_unknown" and "run_id" not in rec  # the path names it; no run exists


def test_NFR_26_log_outside_a_request_or_run_carries_no_ids_before_or_after(client, buf) -> None:
    log = logging.getLogger("nfr26.outside")
    log.error("before")
    client.get(f"/worlds/{WORLD}/nfr26-probe", headers={"X-Cloud-Trace-Context": f"{TRACE_ID}/1;o=1"})
    log.error("after")
    for message in ("before", "after"):
        rec = _one(buf, message)
        assert rec["severity"] == "ERROR" and not [k for k in ID_KEYS if k in rec], rec


def test_NFR_26_formatter_adds_no_header_token_cookie_or_email(client, buf) -> None:
    token, session = "tok_" + secrets.token_hex(16), "sess_" + secrets.token_hex(16)
    email = "person." + secrets.token_hex(4) + "@example.test"
    client.get(
        f"/worlds/{WORLD}/nfr26-probe",
        headers={
            "Authorization": "Bearer " + token,
            "Cookie": "session=" + session,
            "X-Goog-Authenticated-User-Email": "accounts.google.com:" + email,
            "X-Cloud-Trace-Context": f"{TRACE_ID}/1;o=1",
        },
    )
    _one(buf, PROBE)
    text = buf.getvalue()
    assert not [s for s in (token, session, email) if s in text], "a secret or an e-mail address reached the log"


@pytest.mark.parametrize("level", [logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL])
def test_NFR_26_severity_is_the_level_name(level: int) -> None:
    stream = io.StringIO()
    with _configured(stream):
        logging.getLogger("nfr26.sev").log(level, "level %s", "check")
    assert _one(stream, "level check")["severity"] == logging.getLevelName(level)


@settings(max_examples=60, deadline=None)
@given(text=st.text(), level=st.sampled_from([logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL]))
def test_NFR_26_property_any_message_is_exactly_one_json_line_that_round_trips(text: str, level: int) -> None:
    stream = io.StringIO()
    with _configured(stream):
        logging.getLogger("nfr26.prop").log(level, "%s", text)
    out = stream.getvalue()
    assert out.endswith("\n") and out.count("\n") == 1  # newlines, quotes and unicode cannot split a record
    rec = json.loads(out)
    assert rec["message"] == text and rec["severity"] == logging.getLevelName(level)


def test_NFR_26_importing_the_service_app_makes_it_log_json_by_default() -> None:
    env = {k: v for k, v in os.environ.items() if k not in {"K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"}}
    code = "import logging, tilo_api\nlogging.getLogger('nfr26.boot').warning('nfr26 boot message')"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    lines = [ln for ln in (done.stdout + done.stderr).splitlines() if "nfr26 boot message" in ln]
    assert lines, f"the record never reached stdout or stderr: {done.stderr[-300:]}"
    rec = json.loads(lines[0])  # a plain-text 'WARNING:nfr26.boot:...' line fails here
    assert rec["severity"] == "WARNING" and rec["message"] == "nfr26 boot message"
