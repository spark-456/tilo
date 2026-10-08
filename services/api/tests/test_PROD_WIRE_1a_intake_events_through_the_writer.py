"""PROD-WIRE slice 1a, ADR-0026 decision 4: intake to approve commits every event through `EventWriter.append`.

Drives the CP2 / FR-INT flow (`_clint1_lib.Flow`, the `flow` fixture) for a task that names a scenario and has two
questions: `world.requested`, the questions, the approaches, `budget.granted` and the scenario's `policy.changed`
events. With a recording writer (and with the adapter over a harness `MemoryStore`), each of them must reach the
writer, and the stream it commits has strictly increasing `seq` with no gaps. Today `tasks._append` extends
`store.events` itself, so the writer is never called.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from _api_lib import FakeEventWriter
from tilo_api import deps
from tilo_harness.store import MemoryStore

EXPECTED = {"world.requested", "plan.questions_asked", "plan.approaches_proposed", "budget.granted", "policy.changed"}


class _Spy:
    """Wraps a writer and records every part it is handed, in order."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.appended = inner, []

    def append(self, world_id: str, event: dict) -> dict:
        committed = self.inner.append(world_id, event)
        self.appended.append((world_id, event.get("type"), committed))
        return committed


def _drive(flow: Any, writer: _Spy) -> str:
    flow.app.dependency_overrides[deps.get_event_writer] = lambda: writer
    made = flow.client.post("/intake", data={"text": "Compare competitor pricing.", "scenario": "SC-01"})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["questions"], "the flow's Director marks two fields ambiguous"
    skipped = [{"field": q["field"], "answer": None} for q in body["questions"]]
    assert flow.answers(body["task_id"], skipped).status_code == 200
    assert flow.approaches(body["task_id"]).status_code == 200
    approved = flow.approve(body["task_id"], "quick", 50)
    assert approved.status_code == 200, approved.text
    return body["world_id"]


def _assert_through_the_writer(flow: Any, spy: _Spy, world: str) -> list[dict]:
    stream = list(flow.store.events.get(world, []))
    assert EXPECTED <= {e["type"] for e in stream}, [e["type"] for e in stream]
    sent = [committed["id"] for w, _type, committed in spy.appended if w == world]
    assert sent, "no event of the flow went through EventWriter.append"
    assert sorted(sent) == sorted({e["id"] for e in stream}), "an event reached store.events around the writer"
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1)), "seq strictly increasing, no gaps"
    return stream


def test_PROD_WIRE_1a_every_event_of_intake_to_approve_is_appended_through_the_writer(flow: Any) -> None:
    spy = _Spy(FakeEventWriter(flow.store))
    _assert_through_the_writer(flow, spy, _drive(flow, spy))


def test_PROD_WIRE_1a_the_adapter_over_a_memory_store_commits_the_whole_flow_with_dense_seq(flow: Any) -> None:
    backend = MemoryStore()
    adapter = importlib.import_module("tilo_api.world_writer").WorldWriterAdapter(flow.store, backend)
    spy = _Spy(adapter)
    world = _drive(flow, spy)
    stream = _assert_through_the_writer(flow, spy, world)
    assert backend.read_events(deps.ORG_ID, world) == stream, "the cache holds exactly what the writer committed"
    assert {e["run_id"] for e in stream} == {flow.store.worlds[world].run_id}
    types = [e["type"] for e in stream]
    assert types.index("world.requested") == 0 and types.index("budget.granted") > types.index(
        "plan.approaches_proposed"
    )
    with pytest.raises(deps.EventRejected):  # the conflict path is the writer's, not tilo-api's
        adapter.append(world, {**stream[0], "summary": "A different summary under the same id."})
