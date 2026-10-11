"""PROD-WIRE slice 5a, security round 1.

1. An anonymous demo session stores nothing durable (DEMO-EPHEMERAL-1, BQ-DEMO-EPH-1): its billed Quick ask reaches its
   own in-memory ledger, never `orgs/org_tilo/ledger`, and its cost views read only that.
2. A slow ledger never holds a world's lock: the append runs after the event is committed and cached, outside the
   lock, so the world's next event (`world.paused` included, FR-WLD-07) is not delayed by it; the Firestore `create`
   carries a bounded `timeout` and a `retry`.
3. A stored document with negative credits, an unknown `kind` or another org's `org` field is skipped (logged by type).
4. Every credit-bearing event part gets a fresh random id (`events.new_part_id`): the invariant that makes the bare
   event id a collision-free ledger id across worlds.
5. The door's backoff marker is `_door_retry_at` (it serves the ledger as well as the access store).
"""

from __future__ import annotations

import ast
import dataclasses
import logging
import pathlib
import re
import threading
import time

import pytest
from _pw3_lib import DEMO, Builder
from _pw5_lib import SENTINEL, LedgerClient, Ref, doc_path, firestore_ledger, make_entry, stored_body
from test_PROD_WIRE_1a_world_writer_adapter import WORLD, _part
from test_PROD_WIRE_5a_cost_event_feed import _rig
from tilo_api import app, deps, events


@pytest.fixture(autouse=True)
def _fresh_demo_registry():
    from tilo_api import ephemeral

    ephemeral.configure()  # a demo's bundle is keyed by uid for the process: no test sees another's
    yield
    ephemeral.configure()


SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_api"


# -- 1. demo sessions never reach the durable ledger -----------------------------------------------------------------


def _deployed_quick(quick_rig, pw3, *, demo: bool):
    from _costfast1_lib import SIMPLE_TEXT

    client = LedgerClient()
    pw3.use(Builder(make=lambda: client))
    pw3.laptop(DEMO, TILO_API_STORE="firestore")
    for seam in (deps.get_ledger_writer, deps.get_ledger):
        app.dependency_overrides.pop(seam, None)  # the deployed seams, as a Cloud Run process has them
    if demo:
        quick_rig.flow.principal = dataclasses.replace(quick_rig.flow.principal, demo_session=True)
    return client, quick_rig.ask(SIMPLE_TEXT)


def test_PROD_WIRE_5a_DEMO_EPHEMERAL_1_a_demo_sessions_billed_quick_ask_leaves_the_firestore_ledger_empty(
    quick_rig, pw3
):
    client, answered = _deployed_quick(quick_rig, pw3, demo=True)
    assert answered.status_code == 200 and answered.json()["cost"]["credits"] > 0, "the ask was billed"
    assert client.ledger_docs() == {}, "a demo session wrote nothing durable"
    assert [op for op in client.ops if op[0] in {"create", "stream", "get"}] == [], "the Firestore door never opened"


def test_PROD_WIRE_5a_DEMO_EPHEMERAL_1_a_demos_cost_views_show_only_its_own_entries(quick_rig, pw3):
    client, answered = _deployed_quick(quick_rig, pw3, demo=True)
    owner = quick_rig.flow.principal.user_id
    firestore_ledger()(client).append(make_entry(run="r_pw5_durable", user=owner, credits=7.0), entry_id="durable_1")
    billed = answered.json()["cost"]["credits"]
    costs = quick_rig.client.get("/costs")
    assert costs.status_code == 200, costs.text
    assert costs.json()["totals"]["credits"] == pytest.approx(billed), "the demo's own entry, not the durable one"
    assert [op for op in client.ops if op[0] == "stream"] == [], "the Firestore ledger was not read for a demo"


def test_PROD_WIRE_5a_a_full_session_quick_ask_still_reaches_the_durable_ledger(quick_rig, pw3):
    client, answered = _deployed_quick(quick_rig, pw3, demo=False)
    assert answered.status_code == 200
    assert len(client.ledger_docs()) == 1


def test_PROD_WIRE_5a_a_demo_session_ledger_is_in_memory_and_gone_with_its_session(quick_rig, pw3):
    from tilo_api import ephemeral

    _client, answered = _deployed_quick(quick_rig, pw3, demo=True)
    session = ephemeral.for_request(_FakeRequest(quick_rig.flow.principal))
    assert session is not None and len(session.ledger.entries()) == 1
    session.clear()
    assert answered.status_code == 200 and list(session.ledger.entries()) == []


class _FakeRequest:
    """A request as `ephemeral.for_request` reads one: `state.principal`."""

    def __init__(self, principal) -> None:
        self.app, self.state = app, type("S", (), {})()
        self.state.principal = principal


# -- 2. a slow ledger does not hold the world's lock -----------------------------------------------------------------


class BlockingLedger:
    def __init__(self) -> None:
        self.release, self.entered, self.calls = threading.Event(), threading.Event(), 0

    def append(self, entry, *, entry_id):
        self.calls += 1
        self.entered.set()
        self.release.wait(5)


def test_PROD_WIRE_5a_FR_WLD_07_a_slow_ledger_does_not_delay_the_next_event_of_the_same_world():
    ledger = BlockingLedger()
    adapter, store, _backend = _rig(ledger)
    first = threading.Thread(target=adapter.append, args=(WORLD, _part(1, credits=2.5)))
    first.start()
    try:
        assert ledger.entered.wait(2), "the ledger was called"
        start = time.monotonic()
        adapter.append(WORLD, _part(2))  # a zero-credit event: no ledger call of its own
        waited = time.monotonic() - start
        assert waited < 0.2, f"the next event of the world waited {waited:.2f}s on the ledger"
        assert [e["id"] for e in store.events[WORLD]][:1] == [_part(1)["id"]], "the cost event was cached first"
    finally:
        ledger.release.set()
        first.join(5)


def test_PROD_WIRE_5a_the_ledger_is_called_after_the_event_is_cached():
    seen = []
    ledger = BlockingLedger()
    adapter, store, _backend = _rig(ledger)
    ledger.release.set()
    original = ledger.append
    ledger.append = lambda entry, *, entry_id: (
        seen.append([e["id"] for e in store.events.get(WORLD, [])]),
        original(entry, entry_id=entry_id),
    )[1]  # noqa: E501
    part = _part(1, credits=2.5)
    adapter.append(WORLD, part)
    assert seen == [[part["id"]]], "the event is in the cache when the ledger is called"


def test_PROD_WIRE_5a_a_failing_ledger_still_returns_the_committed_event(caplog):
    class Failing:
        def append(self, entry, *, entry_id):
            raise RuntimeError(SENTINEL)

    adapter, store, _backend = _rig(Failing())
    with caplog.at_level(logging.DEBUG):
        committed = adapter.append(WORLD, _part(1, credits=2.5))
    assert committed["id"] == _part(1)["id"] and len(store.events[WORLD]) == 1
    assert "RuntimeError" in caplog.text and SENTINEL not in caplog.text


def test_PROD_WIRE_5a_the_firestore_create_has_a_bounded_timeout_and_a_retry(monkeypatch):
    calls = []
    real = Ref.create

    def spy(self, data, *args, **kwargs):
        calls.append(kwargs)
        return real(self, data, *args, **kwargs)

    monkeypatch.setattr(Ref, "create", spy)
    client = LedgerClient()
    firestore_ledger()(client).append(make_entry(), entry_id="timed_1")
    [kwargs] = calls
    assert kwargs.get("retry") is not None, "a retry policy is passed"
    assert 0 < kwargs.get("timeout", 0) <= 5.0, "a timeout of about 5 s at most"


# -- 3. a stored document that is not a valid entry is skipped -------------------------------------------------------

BAD_DOCUMENTS = {
    "negative-credits": {"credits": -1.0},
    "kind-outside-the-set": {"kind": f"{SENTINEL}-refund"},
    "another-orgs-document": {"org": "org_other"},
}


@pytest.mark.parametrize("name", sorted(BAD_DOCUMENTS))
def test_PROD_WIRE_5a_a_document_with_an_invalid_field_is_skipped_and_logged_by_type_only(name, caplog):
    client = LedgerClient()
    ledger = firestore_ledger()(client)
    good = make_entry(run="r_good")
    ledger.append(good, entry_id="good_1")
    client.docs[doc_path("bad_1")] = dict(stored_body(make_entry(run="r_bad"))) | BAD_DOCUMENTS[name]
    with caplog.at_level(logging.DEBUG):
        assert list(ledger.entries()) == [good]
    assert caplog.records and "ValueError" in caplog.text and SENTINEL not in caplog.text


@pytest.mark.parametrize("kind", ["reserve", "commit", "release", "grant", "usage"])
def test_PROD_WIRE_5a_every_kind_of_the_set_still_decodes(kind):
    client = LedgerClient()
    ledger = firestore_ledger()(client)
    entry = make_entry(kind=kind, credits=0.0)
    ledger.append(entry, entry_id="k_1")
    assert list(ledger.entries()) == [entry]


def test_PROD_WIRE_5a_zero_credits_and_null_credits_still_decode():
    client = LedgerClient()
    ledger = firestore_ledger()(client)
    zero, none = make_entry(credits=0.0, run="r_zero"), make_entry(credits=None, run="r_none")
    ledger.append(zero, entry_id="z_1")
    ledger.append(none, entry_id="n_1")
    assert {e.run for e in ledger.entries()} == {"r_zero", "r_none"}


# -- 4. credit-bearing event parts get a fresh random id ---------------------------------------------------------------


def test_PROD_WIRE_5a_new_part_id_is_fresh_and_random_not_derived_from_any_input():
    ids = {events.new_part_id() for _ in range(2000)}
    assert len(ids) == 2000, "no collision"
    assert all(re.fullmatch(r"0[0-9A-HJKMNP-TV-Z]{25}", i) for i in ids)
    assert events.stable_part_id("w", "r") == events.stable_part_id("w", "r"), "the contrast: this one is derived"


def test_PROD_WIRE_5a_the_only_derived_event_id_belongs_to_a_zero_credit_event():
    """`stable_part_id` is called in one place, for `world.failed`, which costs nothing. A credit-bearing part's id is
    `new_part_id()` (or one a caller took from it), so the bare event id cannot collide across worlds."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        for func in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(func, ast.FunctionDef):
                continue
            for node in ast.walk(func):
                name = getattr(node.func, "id", getattr(node.func, "attr", "")) if isinstance(node, ast.Call) else ""
                if name == "stable_part_id":
                    found.append((path.name, func.name))
    assert found == [("events.py", "world_failed_part")], found
    failed = events.world_failed_part("w_pw5", "reason", "r_pw5")
    assert failed["type"] == "world.failed" and failed["credits"] == 0


# -- 5. the door's backoff marker -----------------------------------------------------------------------------------


def test_PROD_WIRE_5a_the_door_backoff_marker_is_named_for_the_door_not_the_access_store():
    assert hasattr(deps, "_door_retry_at") and not hasattr(deps, "_access_retry_at")
