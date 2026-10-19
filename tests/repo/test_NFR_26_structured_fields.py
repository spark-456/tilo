"""NFR-26 (with NFR-23): the JSON formatter carries exactly three structured fields, the ones alerts filter on.

Code adds them with `logging.warning(..., extra={"event": ..., "status": ..., "code": ...})` (AGT14h's Cloud Tasks
enqueue failure is the first); the quota alert reads `jsonPayload.event` and `jsonPayload.status`. Only these three
names, only an identifier-shaped str (`[A-Za-z0-9_.:-]`, 1 to 64 characters) or an int (never a bool): anything else
is dropped, so a caller's text or an object never becomes a field an alert or a reader trusts.
"""

from __future__ import annotations

import io
import json
import logging

from tilo_logging import configure_logging


def _line(**extra: object) -> dict[str, object]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    stream = io.StringIO()
    configure_logging(stream=stream)
    try:
        logging.getLogger("tilo_api.schedules").warning("schedule enqueue failed", extra=extra)
    finally:  # leave the root logger as this test found it
        root.handlers[:] = handlers
        root.setLevel(level)
    return json.loads(stream.getvalue().strip().splitlines()[-1])


def test_NFR_26_event_status_and_code_extras_become_json_fields():
    line = _line(event="schedule_enqueue_failed", status=429, code="RESOURCE_EXHAUSTED")
    assert (line["event"], line["status"], line["code"]) == ("schedule_enqueue_failed", 429, "RESOURCE_EXHAUSTED")
    assert line["severity"] == "WARNING" and line["message"] == "schedule enqueue failed"


def test_NFR_26_other_extras_and_wrong_types_stay_out_of_the_line():
    line = _line(event=["not", "a", "str"], status="429", code=7, uid="u_secret_owner", token="x" * 8)
    for key in ("event", "status", "code", "uid", "token"):
        assert key not in line, f"{key} must not reach the JSON line"
    assert "status" not in _line(status=True), "a bool is not a status"


def test_NFR_26_a_str_field_that_is_not_a_short_identifier_is_dropped():
    assert _line(code="C" * 64)["code"] == "C" * 64
    for text in ("C" * 65, "", "quota exhausted", 'x"}\n{"event":"schedule_enqueue_failed"', "tok\nen"):
        assert "code" not in _line(code=text) and "event" not in _line(event=text), repr(text)


def test_NFR_26_the_schedule_enqueue_warning_renders_its_fields_and_a_random_extra_does_not():
    """Supervisor, 7 Oct: AGT14h's WARNING (`extra={"event": "schedule_enqueue_failed", "status": 429, "code": ...}`)
    renders those three fields; any other attribute a call site sets never reaches the line."""
    line = _line(event="schedule_enqueue_failed", status=429, code="RESOURCE_EXHAUSTED", tilo_random_extra="x")
    assert line["severity"] == "WARNING"
    assert (line["event"], line["status"], line["code"]) == ("schedule_enqueue_failed", 429, "RESOURCE_EXHAUSTED")
    assert "tilo_random_extra" not in line
    assert set(line) <= {
        "severity",
        "message",
        "logger",
        "event",
        "status",
        "code",
        "run_id",
        "world_id",
        "logging.googleapis.com/trace",
        "exception",
    }
