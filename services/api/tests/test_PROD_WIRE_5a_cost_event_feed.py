"""PROD-WIRE slice 5a (unit): the durable ledger is fed from committed cost events, as dev mode feeds its own.

Commit point chosen (read the code): `world_writer.WorldWriterAdapter.append`
(services/api/src/tilo_api/world_writer.py, `append`, right after `committed = self._emit(...)`). Every deployed
event is committed there and nowhere else: `deps.get_event_writer()` is `durable_store.deployed()[1]`, the adapter,
and `DurableStore.drain`/`save` hand each queued part to `writer.append`
(tests/repo/test_PROD_WIRE_1a_one_writer_path.py pins that one path). It is reached by a new event and by an
idempotent resend of one already committed, which is why a failed ledger append is repaired by a resend. The
alternative, `DurableStore.drain`, sees only queued parts and not a direct `append`, so it is not the single point.

Pinned names (see `_pw5_lib.py`): `tilo_api.cost_entries.entry_from_cost_event(event, owner, *, org=deps.ORG_ID,
usage=None)`; `WorldWriterAdapter(..., ledger=<object with append(entry, *, entry_id)>)`; `durable_store.deployed()`
gives the adapter a `prod.FirestoreLedger` on `opened.client`.

Ambiguity resolved (brief: "the same entry is appended"): dev mode's entry carries `usage=dev_run.UNIT_USAGE`, a
fixed fake `dev-unit` profile. The deployed event records no usage, and Tilo does not invent one, so the shared
function takes `usage` as a keyword (default None) and dev passes `UNIT_USAGE`; the deployed writer passes nothing.
Every other field is the one function's, so dev and prod cannot drift on them."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from _pw3_lib import PROJECT
from _pw5_lib import SENTINEL, LedgerClient, RecordingLedger, doc_path, entry_from_cost_event, import_attr
from hypothesis import given, settings
from hypothesis import strategies as st
from test_PROD_WIRE_1a_world_writer_adapter import OWNER, RUN, WORLD, _Clock, _part
from tilo_api import deps
from tilo_api.durable_store import DurableStore, MemoryBackend
from tilo_api.world_writer import WorldWriterAdapter
from tilo_harness.store import MemoryStore
from tilo_metering import LedgerEntry

DEV_OWNER = "u_dev_owner"
RUN_X = "r_pw5_1"
T = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)


def _unit_usage():
    from tilo_api.dev_run import UNIT_USAGE

    return UNIT_USAGE


def _event(**over):
    return {"id": "01JB5VQ0000000000000000001", "run_id": RUN_X, "ts": "2026-10-07T01:00:00.000Z", "credits": 2.5,
            "item": None, "type": "agent.working"} | over  # fmt: skip


def _commit(credits, step=None, at=T, run=RUN_X, user=DEV_OWNER, usage=None):
    return LedgerEntry("commit", run, user, "org_tilo", at, step=step, credits=credits, usage=usage)


# (event overrides, the entry dev mode produced for it before this slice): pinned from DevLedger.record as it stood.
PINNED = {
    "float-credits": ({"credits": 2.5}, _commit(2.5)),
    "int-credits-become-float": ({"credits": 3}, _commit(3.0)),
    "tiny": ({"credits": 1e-06}, _commit(1e-06)),
    "item-is-the-step": ({"credits": 1.5, "item": "U1"}, _commit(1.5, step="U1")),
    "non-string-item-is-no-step": ({"credits": 1.5, "item": 5}, _commit(1.5)),
    "offset-ts-is-the-same-instant": (
        {"credits": 1.0, "ts": "2026-10-07T06:30:00.000+05:30"},
        _commit(1.0, at=datetime(2026, 10, 7, 1, 0, tzinfo=UTC)),
    ),  # fmt: skip
    "another-run": ({"credits": 4.0, "run_id": "r_other_9"}, _commit(4.0, run="r_other_9")),
}
NOT_A_COST = {
    "zero": {"credits": 0},
    "zero-float": {"credits": 0.0},
    "negative": {"credits": -1.0},
    "bool": {"credits": True},
    "string": {"credits": "3"},
    "null": {"credits": None},
    "list": {"credits": [3]},
    "missing": {"credits": ...},
}


def _with(event, over):
    merged = event | over
    return {k: v for k, v in merged.items() if v is not ...}


@pytest.fixture()
def dev_safe(monkeypatch):
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)


# -- the shared conversion; dev's current output pinned --------------------------------------------------------------


def test_PROD_WIRE_5a_dev_ledger_output_is_pinned_before_the_extraction(dev_safe):
    """Characterisation: passes today and must keep passing, so the extraction cannot change dev's entries."""
    from tilo_api.dev import DevLedger

    for name, (over, expected) in PINNED.items():
        ledger = DevLedger()
        ledger.record(_event(**over), DEV_OWNER)
        assert ledger.entries() == (replace(expected, usage=_unit_usage()),), name


def test_PROD_WIRE_5a_the_shared_function_maps_an_event_to_exactly_the_entry_dev_mode_made(dev_safe):
    from tilo_api.dev import DevLedger

    function = entry_from_cost_event()
    for name, (over, expected) in PINNED.items():
        produced = function(_event(**over), DEV_OWNER, usage=_unit_usage())
        assert produced == replace(expected, usage=_unit_usage()), name
        dev = DevLedger()
        dev.record(_event(**over), DEV_OWNER)
        assert dev.entries() == (produced,), f"{name}: dev's ledger and the shared function agree"
        assert isinstance(produced.credits, float) and produced.at.tzinfo is not None, name
        assert (produced.kind, produced.org, produced.price_effective_date, produced.price_source, produced.day) == (
            "commit", deps.ORG_ID, None, None, None,
        ), name  # fmt: skip
    plain = function(_event(), "u_x")
    assert plain.usage is None and plain.org == deps.ORG_ID == "org_tilo" and plain.user == "u_x", (
        "no usage is invented"
    )
    assert function(_event(), "u_x", org="org_other").org == "org_other"
    assert replace(function(_event(), "u_x", usage=_unit_usage()), usage=None) == plain, "usage is the only difference"


def test_PROD_WIRE_5a_an_event_with_no_positive_credits_is_not_an_entry_in_dev_or_in_the_function(dev_safe):
    from tilo_api.dev import DevLedger

    for name, change in NOT_A_COST.items():
        event = _with(_event(), change)
        assert entry_from_cost_event()(event, DEV_OWNER) is None, name
        dev = DevLedger()
        dev.record(event, DEV_OWNER)
        assert dev.entries() == (), name


# -- the adapter feeds the ledger from committed cost events -----------------------------------------------------------


def _rig(ledger, *, owner=OWNER, clock=None, run=RUN):
    store = deps.Store(worlds={WORLD: deps.WorldRecord(owner=owner, districts={}, run_id=run)})
    backend = MemoryStore()
    adapter = WorldWriterAdapter(store, backend, clock=clock if clock is not None else _Clock(), ledger=ledger)
    return adapter, store, backend


def test_PROD_WIRE_5a_FR_MTR_10_a_committed_cost_event_appends_its_commit_entry_under_the_event_id():
    ledger = RecordingLedger()
    adapter, _store, backend = _rig(ledger)
    ledger.probe = lambda: [e["id"] for e in backend.read_events(deps.ORG_ID, WORLD)]
    part = _part(1, credits=2.5)
    committed = adapter.append(WORLD, part)
    assert ledger.seen_at_append == [[part["id"]]], "appended only after the event was committed"
    expected = LedgerEntry("commit", RUN, OWNER, "org_tilo", T, step=None, credits=2.5)
    assert ledger.calls == [(part["id"], expected)], "entry_id is the event id; the entry is the world owner's commit"
    assert committed["id"] == part["id"]
    assert ledger.calls[0][1] == entry_from_cost_event()(committed, OWNER), "the same function dev mode uses"
    assert ledger.calls[0][1].usage is None, "no usage is invented for a deployed event"
    theirs = RecordingLedger()
    other, _store2, _backend2 = _rig(theirs, owner="u_pw5_someone", run="r_pw5_own_run")
    other.append(WORLD, _part(1, credits=4.0, run_id="r_stale_9"))
    [(_entry_id, entry)] = theirs.calls
    assert (entry.user, entry.run, entry.org) == ("u_pw5_someone", "r_pw5_own_run", "org_tilo"), (
        "the world's, not the event's"
    )


def test_PROD_WIRE_5a_an_event_that_costs_nothing_makes_no_ledger_call():
    ledger = RecordingLedger()
    adapter, _store, _backend = _rig(ledger)
    adapter.append(WORLD, _part(1, credits=0))
    adapter.append(WORLD, _part(2, credits=0.0))
    adapter.append(WORLD, _part(3))  # the default part carries credits 0
    assert ledger.calls == [] and ledger.docs == {}


def test_PROD_WIRE_5a_a_duplicate_commit_an_idempotent_resend_appends_nothing_new():
    ledger = RecordingLedger()
    clock = _Clock()
    adapter, store, backend = _rig(ledger, clock=clock)
    part = _part(1, credits=2.5)
    adapter.append(WORLD, part)
    stored = dict(ledger.docs)
    clock.advance(30)
    adapter.append(WORLD, part)
    adapter.append(WORLD, dict(part))
    assert ledger.docs == stored and len(ledger.docs) == 1, "the same entry under the same id"
    assert all(entry_id == part["id"] and entry == stored[part["id"]] for entry_id, entry in ledger.calls)
    assert len(backend.read_events(deps.ORG_ID, WORLD)) == 1 and len(store.events[WORLD]) == 1
    with pytest.raises(deps.EventRejected):  # an event the writer refuses appends nothing
        adapter.append(WORLD, _part(1, credits=9.0, summary="Different content under the same id."))
    with pytest.raises(deps.EventRejected):
        adapter.append(WORLD, _part(2, credits=9.0, vis=None))
    assert list(ledger.docs) == [part["id"]] and ledger.docs[part["id"]].credits == 2.5


FAILURES = {
    "plain": lambda: RuntimeError(SENTINEL),
    "unavailable": lambda: import_attr("tilo_api.prod", "FirestoreUnavailable")(),
    "conflict": lambda: import_attr("tilo_api.prod", "LedgerConflict")(SENTINEL),
    "value": lambda: ValueError(SENTINEL),
}


def test_PROD_WIRE_5a_a_ledger_failure_never_fails_or_undoes_the_event_write_and_a_later_resend_repairs_it(caplog):
    for name, make_error in FAILURES.items():
        ledger = RecordingLedger()
        ledger.fail = make_error()
        adapter, store, backend = _rig(ledger)
        part = _part(1, credits=2.5)
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            committed = adapter.append(WORLD, part)  # no exception
        assert committed["id"] == part["id"] and committed["seq"] == 1, name
        assert [e["id"] for e in backend.read_events(deps.ORG_ID, WORLD)] == [part["id"]], f"{name}: still committed"
        assert [e["id"] for e in store.events[WORLD]] == [part["id"]], name
        assert type(ledger.fail).__name__ in caplog.text, f"{name}: logged by type"
        assert SENTINEL not in caplog.text, f"{name}: never the message"
        assert adapter.append(WORLD, _part(2, credits=1.0))["seq"] == 2, f"{name}: and the writer goes on"
        assert ledger.docs == {}
        ledger.fail = None  # the ledger is back: the resend of the same event appends it
        assert adapter.append(WORLD, part) == committed, "an idempotent resend returns the committed event"
        assert ledger.docs[part["id"]].credits == 2.5, name
        assert len(backend.read_events(deps.ORG_ID, WORLD)) == 2, f"{name}: no event was added by the resend"


def test_PROD_WIRE_5a_the_drain_of_the_durable_queue_goes_through_the_same_point():
    ledger = RecordingLedger()
    records, events = MemoryBackend(), MemoryStore()
    store = DurableStore(records, events)
    adapter = WorldWriterAdapter(store, events, clock=_Clock(), ledger=ledger)
    store.writer = adapter
    store.commit(worlds={WORLD: deps.WorldRecord(owner=OWNER, districts={}, run_id=RUN)}, create=[("worlds", WORLD)])
    part = _part(1, credits=2.5)
    store.save(adapter, parts={WORLD: [part]})
    assert list(ledger.docs) == [part["id"]] and store.pending_events.get(WORLD, []) == []


def test_PROD_WIRE_5a_deployed_every_event_passes_the_adapter_and_lands_in_the_firestore_ledger(pw3, monkeypatch):
    from tilo_api import durable_store, store_door

    client = LedgerClient()
    opened = SimpleNamespace(project=PROJECT, client=client, records=MemoryBackend(), events=MemoryStore())
    monkeypatch.setattr(store_door, "open_api_store", lambda *args, **kwargs: opened)
    pw3.deployed(PROJECT, api=True)
    store, _writer = durable_store.deployed()
    store.commit(worlds={WORLD: deps.WorldRecord(owner=OWNER, districts={}, run_id=RUN)}, create=[("worlds", WORLD)])
    writer = deps.get_event_writer()
    part = _part(1, credits=2.5)
    committed = writer.append(WORLD, part)
    docs = client.ledger_docs()
    assert list(docs) == [part["id"]], "orgs/org_tilo/ledger/{event id} on the door's client"
    doc = docs[part["id"]]
    assert (doc["kind"], doc["run"], doc["user"], doc["credits"]) == ("commit", RUN, OWNER, 2.5)
    assert datetime.fromisoformat(docs[part["id"]]["at"]) == datetime.fromisoformat(committed["ts"])
    before = dict(client.docs)
    writer.append(WORLD, part)
    assert client.docs == before and client.writes() == [], "an idempotent resend creates nothing new"
    writer.append(WORLD, _part(2))
    assert client.docs == before, "an event with no cost is not an entry"


def test_PROD_WIRE_5a_deployed_a_firestore_outage_on_the_ledger_leaves_the_event_and_a_resend_repairs_it(
    pw3, monkeypatch
):
    from google.api_core import exceptions as gexc
    from tilo_api import durable_store, store_door

    client = LedgerClient()
    opened = SimpleNamespace(project=PROJECT, client=client, records=MemoryBackend(), events=MemoryStore())
    monkeypatch.setattr(store_door, "open_api_store", lambda *args, **kwargs: opened)
    pw3.deployed(PROJECT, api=True)
    store, writer = durable_store.deployed()
    store.commit(worlds={WORLD: deps.WorldRecord(owner=OWNER, districts={}, run_id=RUN)}, create=[("worlds", WORLD)])
    part = _part(1, credits=2.5)
    client.fail("create", lambda: gexc.ServiceUnavailable(SENTINEL))
    committed = writer.append(WORLD, part)  # the event write is not failed by the ledger
    assert committed["id"] == part["id"] and client.ledger_docs() == {}
    assert [e["id"] for e in opened.events.read_events(deps.ORG_ID, WORLD)] == [part["id"]]
    client.fail("create", None)
    assert writer.append(WORLD, part) == committed
    assert list(client.ledger_docs()) == [part["id"]]
    assert doc_path(part["id"]) in client.docs


# -- property: the ledger is exactly the committed cost events, once each ---------------------------------------------

_credits = st.sampled_from([0, 0.0, 0.5, 1, 2.25, 40, 1e-3, 12.5])


@settings(max_examples=40, deadline=None)
@given(st.lists(_credits, min_size=1, max_size=8), st.data())
def test_PROD_WIRE_5a_property_the_ledger_holds_each_committed_cost_event_once_and_their_sum_is_the_spend(costs, data):
    ledger = RecordingLedger()
    adapter, _store, _backend = _rig(ledger)
    parts = [_part(n, credits=c) for n, c in enumerate(costs, start=1)]
    for part in parts:
        adapter.append(WORLD, part)
    resent = data.draw(st.lists(st.sampled_from(parts), max_size=8))
    for part in resent:  # idempotent resends in any order
        adapter.append(WORLD, part)
    paid = {p["id"]: p["credits"] for p in parts if p["credits"] > 0}
    assert set(ledger.docs) == set(paid), "exactly the events that cost something, under their ids"
    assert {i: e.credits for i, e in ledger.docs.items()} == {i: float(c) for i, c in paid.items()}
    assert sum(e.credits for e in ledger.docs.values()) == pytest.approx(sum(paid.values()))
