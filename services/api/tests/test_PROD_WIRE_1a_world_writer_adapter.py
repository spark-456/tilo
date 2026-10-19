"""PROD-WIRE slice 1a, ADR-0026 decision 4: the `EventWriter` adapter over the harness `WorldWriter`.

Pinned names: `tilo_api.world_writer.WorldWriterAdapter(store, backend, *, org_id=deps.ORG_ID, clock=None,
lease_s=30.0)`, where `store` is the `deps.Store` (it holds the world records and `store.events`) and `backend` is a
harness store (`MemoryStore` here; `FirestoreStore` under the emulator, not run in this slice). It has `append(world_id,
part)` and `reopen()`. Over `MemoryStore` throughout: no emulator, no network. `run_id` and the layout come from the
world record (`WorldRecord.run_id`, and `WorldRecord.layout`, None until the run builds it), never from the part.
"""

from __future__ import annotations

import importlib
import json
import pathlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_api import deps
from tilo_harness.store import MemoryStore
from tilo_harness.validator import EventRejected as HarnessEventRejected
from tilo_harness.writer import WorldWriter

REPO = pathlib.Path(__file__).resolve().parents[3]
VILLAGE = json.loads((REPO / "contracts/fixtures/layout/valid/village_basic.json").read_text(encoding="utf-8"))
OWNER, WORLD, OTHER_WORLD, RUN = "u_pw1_owner", "w_village_basic", "w_pw1_other", "r_pw1_1"
PREPLAN = {"semantic": {"levels": [], "islands": [], "gates": [], "agents": [{"id": "A_director", "rank": "director"}]}}
NULL_TRACE = dict.fromkeys(("model_role", "profile", "tokens_in", "tokens_out", "tool", "latency_ms", "archive_ref"))


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 1, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _part(n: int, **over: Any) -> dict[str, Any]:
    """An agent.idle part as tilo-api builds one: its own id, plus a stale seq, ts and run_id the writer replaces."""
    part = {
        "id": f"01JB5VQ0000000000000{n:06d}", "type": "agent.idle", "actor": "A_director", "target": "A_director",
        "level": None, "district": None, "item": None, "severity": "info", "credits": 0, "cause": None, "vis": "all",
        "authz": None, "summary": "The Director is waiting.", "data": {},
        "seq": 99, "ts": "2001-01-01T00:00:00.000Z", "run_id": "r_stale_9", "world_id": WORLD,
    }  # fmt: skip
    return part | over


def _requested(n: int) -> dict[str, Any]:
    data = {"title": "Do some work", "channel": "web", "destination": None}
    return _part(n, type="world.requested", actor=OWNER, target=WORLD, summary="You asked Tilo.", data=data)


def _rig(clock: _Clock | None = None, worlds: tuple[str, ...] = (WORLD,)) -> tuple[Any, deps.Store, MemoryStore]:
    store = deps.Store(worlds={w: deps.WorldRecord(owner=OWNER, districts={}, run_id=RUN) for w in worlds})
    backend = MemoryStore()
    adapter = importlib.import_module("tilo_api.world_writer").WorldWriterAdapter(store, backend, clock=clock)
    return adapter, store, backend


def _lease(backend: MemoryStore, world: str = WORLD) -> Any:
    return backend.read_head(deps.ORG_ID, world)["lease"]


def test_PROD_WIRE_1a_the_adapter_assigns_seq_from_1_and_stamps_what_the_writer_owns() -> None:
    clock = _Clock()
    adapter, store, backend = _rig(clock)
    first = adapter.append(WORLD, _requested(1))
    second = adapter.append(WORLD, _part(2))
    assert (first["seq"], second["seq"]) == (1, 2), "the part's own seq (99) is ignored"
    assert first["v"] == "1.0" and first["world_id"] == WORLD and first["trace"] == NULL_TRACE
    assert first["run_id"] == RUN, "run_id comes from the world record, never the part"
    assert first["ts"] == "2026-10-07T01:00:00.000Z", "ts is the writer's clock, never the part's"
    assert [e["seq"] for e in backend.read_events(deps.ORG_ID, WORLD)] == [1, 2]
    assert store.events[WORLD] == [first, second], "the committed event joins store.events, once"


def test_PROD_WIRE_1a_a_same_id_same_content_resend_returns_the_committed_event_unchanged() -> None:
    clock = _Clock()
    adapter, store, backend = _rig(clock)
    committed = adapter.append(WORLD, _part(1))
    clock.advance(5)
    assert adapter.append(WORLD, _part(1)) == committed
    assert len(backend.read_events(deps.ORG_ID, WORLD)) == 1
    assert [e["id"] for e in store.events[WORLD]] == [committed["id"]]


def test_PROD_WIRE_1a_different_content_under_one_id_raises_the_api_event_rejected_not_the_harness_one() -> None:
    adapter, store, backend = _rig()
    adapter.append(WORLD, _part(1))
    with pytest.raises(deps.EventRejected) as refused:
        adapter.append(WORLD, _part(1, summary="Something else entirely."))
    assert not isinstance(refused.value, HarnessEventRejected)
    assert len(backend.read_events(deps.ORG_ID, WORLD)) == 1 and len(store.events[WORLD]) == 1


def test_PROD_WIRE_1a_a_lapsed_own_lease_reopens_once_and_resends(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    adapter, _store, backend = _rig(clock)
    opens: list[int] = []
    real_open = WorldWriter.open
    monkeypatch.setattr(WorldWriter, "open", lambda self: (opens.append(1), real_open(self))[1])
    adapter.append(WORLD, _part(1))
    clock.advance(31)  # past the 30 s lease while idle
    assert adapter.append(WORLD, _part(2))["seq"] == 2
    assert len(opens) == 2, "one open for the first append, exactly one reopen for the lapsed lease"
    assert [e["seq"] for e in backend.read_events(deps.ORG_ID, WORLD)] == [1, 2]


def test_PROD_WIRE_1a_a_second_writer_busy_is_raised_after_one_reopen(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    adapter, _store, backend = _rig(clock)
    adapter.append(WORLD, _part(1))
    clock.advance(31)
    rival = WorldWriter(
        backend, org_id=deps.ORG_ID, world_id=WORLD, run_id=RUN, layout=PREPLAN, writer_id="rival", clock=clock
    )
    rival.open()  # takes the lapsed lease; it is live now
    opens: list[int] = []
    real_open = WorldWriter.open
    monkeypatch.setattr(WorldWriter, "open", lambda self: (opens.append(1), real_open(self))[1])
    with pytest.raises(Exception) as busy:
        adapter.append(WORLD, _part(2))
    assert type(busy.value).__name__ == "WriterBusy", "matched by class name, as dispatch does"
    assert len(opens) == 1, "one reopen and resend, then the second WriterBusy is raised, not retried"
    assert len(backend.read_events(deps.ORG_ID, WORLD)) == 1


def test_PROD_WIRE_1a_a_world_leased_elsewhere_raises_writer_busy_and_writes_nothing() -> None:
    clock = _Clock()
    adapter, store, backend = _rig(clock)
    WorldWriter(
        backend, org_id=deps.ORG_ID, world_id=WORLD, run_id=RUN, layout=PREPLAN, writer_id="rival", clock=clock
    ).open()
    with pytest.raises(Exception) as busy:
        adapter.append(WORLD, _part(1))
    assert type(busy.value).__name__ == "WriterBusy"
    assert backend.read_events(deps.ORG_ID, WORLD) == [] and store.events == {}


def test_PROD_WIRE_1a_reopen_closes_every_open_writer_and_releases_its_lease() -> None:
    adapter, _store, backend = _rig(worlds=(WORLD, OTHER_WORLD))
    adapter.append(WORLD, _part(1))
    adapter.append(OTHER_WORLD, _part(2, world_id=OTHER_WORLD))
    assert _lease(backend, WORLD) is not None and _lease(backend, OTHER_WORLD) is not None
    adapter.reopen()
    assert _lease(backend, WORLD) is None and _lease(backend, OTHER_WORLD) is None
    assert adapter.append(WORLD, _part(3))["seq"] == 2, "each writer reopens on its next append and continues"


def test_PROD_WIRE_1a_the_pre_plan_layout_accepts_the_director_and_nothing_else_until_the_layout_is_built() -> None:
    adapter, store, backend = _rig()
    assert adapter.append(WORLD, _requested(1))["seq"] == 1  # a person actor and a world target are not layout ids
    assert adapter.append(WORLD, _part(2))["seq"] == 2  # A_director is the one agent of the pre-plan layout
    built = _part(3, actor="A_v1", target="B3", level="L1", district="D1")
    with pytest.raises(deps.EventRejected):
        adapter.append(WORLD, built)  # EV-12: L1, D1, B3 and A_v1 are not in the pre-plan layout
    assert len(store.events[WORLD]) == 2
    store.worlds[WORLD].layout = VILLAGE  # the run built its layout and stored it on the world record
    committed = adapter.append(WORLD, built)
    assert committed["seq"] == 3, "the adapter reopened the writer with the built layout; no seq was spent"
    assert [e["seq"] for e in backend.read_view(deps.ORG_ID, WORLD, "D1")] == [1], "district views start at the layout"
    assert [e["seq"] for e in backend.read_view(deps.ORG_ID, WORLD, "shared")] == [1, 2, 3]


def test_PROD_WIRE_1a_a_changed_run_id_on_the_world_record_is_stamped_on_the_next_event() -> None:
    adapter, store, _backend = _rig()
    assert adapter.append(WORLD, _part(1))["run_id"] == RUN
    store.worlds[WORLD].run_id = "r_pw1_2"
    assert adapter.append(WORLD, _part(2))["run_id"] == "r_pw1_2"


@settings(max_examples=25, deadline=None)
@given(order=st.lists(st.integers(min_value=1, max_value=6), min_size=1, max_size=14))
def test_PROD_WIRE_1a_property_seq_is_dense_and_a_resend_never_adds_an_event(order: list[int]) -> None:
    adapter, store, backend = _rig()
    first_seen: dict[int, dict[str, Any]] = {}
    for n in order:
        committed = adapter.append(WORLD, _part(n))
        assert first_seen.setdefault(n, committed) == committed
    stream = backend.read_events(deps.ORG_ID, WORLD)
    assert [e["seq"] for e in stream] == list(range(1, len(first_seen) + 1))
    assert store.events[WORLD] == stream
    assert [e["id"] for e in stream] == [_part(n)["id"] for n in dict.fromkeys(order)]
