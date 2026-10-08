"""CL-LIVE-1: (4) the scopes are the minimum config/connectors.yaml already declares, pinned here (Gmail read and
compose-draft only: no send, no modify, no delete; Drive `drive.file` only; Calendar read-only), with no widening in
code; (5) privacy: what real adapters read (mailbox, Drive, Calendar) is never written to a recording, fixture, event,
log or the output. A fake transport plants marker strings; every artifact is scanned for them and for the tokens.
API: API_CL_LIVE_1.md.
"""

from __future__ import annotations

import logging
import re

import pytest
from _cl_live_lib import (
    CALENDAR_READONLY,
    DRIVE_FILE,
    GMAIL_COMPOSE,
    GMAIL_READONLY,
    GMAIL_SEND,
    REAL_PY,
    dump,
    leaks,
    make_real_env,
    read_everything,
    real,
    tree_files,
)
from _cl_live_lib import clean_process_env as clean_process_env  # autouse fixture
from _cl_live_lib import socket_guard as socket_guard  # autouse fixture
from _oauth_lib import OWNER

PINNED = {
    "gmail": {GMAIL_READONLY, GMAIL_COMPOSE},
    "google_drive": {DRIVE_FILE},
    "google_calendar": {CALENDAR_READONLY},
}
FORBIDDEN_FRAGMENTS = (
    "gmail.send",
    "gmail.modify",
    "mail.google.com",
    "gmail.metadata",
    "gmail.insert",
    "gmail.labels",
    "gmail.settings",
    "drive.readonly",
    "drive.metadata",
    "drive.appdata",
    "drive.photos",
    "calendar.events",
    "calendar.settings",
)


def _requested(plan) -> dict[str, set[str]]:
    return {row["connector"]: set(row["scopes"]) for row in plan}


# ---------------------------------------------------------------------------
# Scopes


def test_CL_LIVE_1_real_scopes_are_exactly_the_pinned_minimum():
    scopes = real().REAL_SCOPES
    assert {k: set(v) for k, v in scopes.items()} == PINNED
    flat = " ".join(s for v in scopes.values() for s in v)
    assert not [f for f in FORBIDDEN_FRAGMENTS if f in flat]
    assert not re.search(r"auth/(drive|calendar)\b(?!\.)", flat), "no full-Drive or full-Calendar scope"


def test_CL_LIVE_1_the_plan_lists_each_google_connector_read_only_with_those_scopes():
    g = make_real_env()

    plan = real().real_connector_plan(g.registry)

    assert [row["connector"] for row in plan] == ["gmail", "google_drive", "google_calendar"]
    assert all(row["mode"] == "read_only" for row in plan)
    assert _requested(plan) == PINNED
    assert all(isinstance(row["scopes"], tuple) for row in plan)


def test_CL_LIVE_1_the_pinned_scopes_are_a_subset_of_what_the_shipped_config_declares():
    """Contracts and config win: the code narrows the config, it never adds to it."""
    g = make_real_env()
    for connector_id, pinned in PINNED.items():
        declared = {s for scopes in g.registry.get(connector_id)["scopes"].values() for s in scopes}
        assert pinned <= declared, connector_id
    gmail = g.registry.get("gmail")["scopes"]
    assert GMAIL_SEND in gmail["send"], "the config declares send (CL-LIVE-2's); this slice never requests it"
    assert GMAIL_SEND not in _requested(real().real_connector_plan(g.registry))["gmail"]


def test_CL_LIVE_1_every_token_the_adapters_ask_for_is_within_the_pinned_scopes():
    g = make_real_env()
    adapters = g.build()

    read_everything(adapters, g.env)

    assert g.spy.asked, "the reads asked the broker for tokens"
    allowed = set().union(*PINNED.values())
    for _user, connector, scopes in g.spy.asked:
        assert connector in PINNED
        assert set(scopes) <= PINNED[connector] <= allowed, (connector, scopes)
    assert GMAIL_SEND not in {s for _u, _c, scopes in g.spy.asked for s in scopes}


def test_CL_LIVE_1_real_module_names_no_wider_scope_in_code():
    """No scope widening in code: the module may name the pinned scopes and nothing wider."""
    assert REAL_PY.is_file()
    source = REAL_PY.read_text(encoding="utf-8")
    assert not [f for f in FORBIDDEN_FRAGMENTS if f in source]


# ---------------------------------------------------------------------------
# Privacy: mailbox, Drive and Calendar content goes nowhere but the caller


def test_CL_LIVE_1_read_content_reaches_no_event_log_stdout_or_file(tmp_path, monkeypatch, capsys, caplog):
    """The run's whole artifact surface after a full read: events, logs, stdout, stderr, repr, and every file under the
    working directory (with the record switch on, as a recorded live run would have it)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TILO_RECORD", "1")
    before = tree_files(tmp_path)
    caplog.set_level(logging.DEBUG)
    g = make_real_env()
    adapters = g.build()

    result = read_everything(adapters, g.env)
    g.transport.fail_next(429, {"error": {"message": g.markers.error_body}})
    g.transport.fail_next(400, {"error": {"message": g.markers.error_body}})
    with pytest.raises(Exception) as failed:  # noqa: PT011 - the type is the adapter's; its text is what matters
        adapters["gmail"].list_threads(OWNER, max_results=5)  # a 429 (an event), then a 400 whose body is planted
    errors = [str(failed.value), repr(failed.value)]

    assert result["threads"]["threads"], "the caller did get the content it asked for"
    captured = capsys.readouterr()
    log_text = "\n".join(r.getMessage() + repr(r.args) for r in caplog.records)
    surfaces = {
        "events": dump(g.emitted),
        "stdout": captured.out,
        "stderr": captured.err,
        "logs": log_text,
        "errors": "\n".join(errors),
        "adapters": repr(adapters) + "".join(repr(a) for a in adapters.values()),
    }
    needles = [*g.markers.all(), *g.issued_secrets()]
    for name, text in surfaces.items():
        assert not leaks(text, needles), f"{name} holds content or a token"
    after = tree_files(tmp_path)
    assert after == before, "a real read writes no recording, fixture or cache file"


def test_CL_LIVE_1_events_from_real_reads_carry_counts_and_ids_only(tmp_path):
    """A rate limit is an event (PRD 9.5); it carries the connector and a wait, never Google's words."""
    g = make_real_env()
    adapters = g.build()
    g.transport.fail_next(429, {"error": {"message": g.markers.error_body}})

    page = adapters["gmail"].list_threads(OWNER, max_results=5)

    assert page["threads"]
    limited = [e for e in g.emitted if e["type"] == "connection.rate_limited"]
    for event in g.emitted:
        assert not leaks(dump(event), [*g.markers.all(), *g.issued_secrets()])
    for event in limited:
        assert set(event["data"]) == {"connector", "retry_after_s"}


def test_CL_LIVE_1_the_adapters_do_not_wrap_the_transport_in_a_recorder(tmp_path, monkeypatch):
    """`recording.RecordingTransport` saves whole exchanges; a real mailbox must never be recorded (EFF-01, SEC-09)."""
    from tilo_connectors import recording

    created: list[object] = []
    original = recording.RecordingTransport.__init__

    def spy(self, *args, **kwargs):
        created.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(recording.RecordingTransport, "__init__", spy)
    g = make_real_env()

    read_everything(g.build(), g.env)

    assert created == []


@pytest.mark.parametrize("bad", ["abc", "ya29.FAKE", "x" * 5000], ids=["short", "token-shaped", "long"])
def test_CL_LIVE_1_a_bad_drive_id_is_refused_without_a_request_or_an_echo(bad):
    from tilo_connectors.adapters import AdapterError

    g = make_real_env()
    drive = g.build()["google_drive"]

    with pytest.raises(AdapterError) as info:
        drive.get_metadata(OWNER, bad)

    assert bad not in str(info.value)
    assert g.transport.requests == []
