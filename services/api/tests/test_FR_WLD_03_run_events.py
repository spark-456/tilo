"""CL-INT-2 / FR-WLD-03 and the single writer (PRD 9.3, 9.5, 15.3 "the harness is the only writer", 14.1; EV-01..EV-14;
PL-01): every event of a run, from `world.started` to `world.completed`, is a registered type, is schema-valid, and
passes the harness validator against the run's layout; `seq` stays strictly increasing and gap-free across the
CL-INT-1 events and the run's; all of them reach the stream through the one `EventWriter`; no model id appears in
any of them; and the budget is never exceeded. Sequence: API_CL_INT_2.md.
"""

from __future__ import annotations

import json

import pytest
import yaml
from _clint1_lib import registered_event_types
from _clint2_lib import REPO_ROOT, assert_stream_valid, only, wait_for

RUN_TYPES = {
    "world.started", "agent.spawned", "agent.assigned", "agent.working", "agent.handoff", "agent.retired",
    "skill.loaded", "artifact.created", "approval.requested", "approval.resolved", "data.transfer",
    "artifact.delivered", "world.completed",
}  # fmt: skip


def test_FR_WLD_03_every_event_a_run_emits_is_registered_schema_valid_and_strictly_increasing(run_flow, registry):
    run_flow.run_to_completion()

    events = assert_stream_valid(run_flow, registry)

    emitted = {e["type"] for e in events}
    assert RUN_TYPES <= emitted, RUN_TYPES - emitted  # the whole slice happened
    assert emitted <= registered_event_types(REPO_ROOT)
    owner_view = run_flow.flow.client.get(f"/worlds/{run_flow.world_id}/events")
    assert owner_view.status_code == 200
    assert [e["seq"] for e in owner_view.json()["events"]] == [e["seq"] for e in events]  # none dropped as malformed


def test_FR_WLD_03_the_run_writes_only_through_the_single_event_writer(run_flow):
    run_flow.run_to_completion()

    written = [call.part for call in run_flow.writer.calls]
    assert all(isinstance(part.get("id"), str) and part["id"] for part in written)  # each carries its idempotency key
    run_events = run_flow.after_grant()
    assert {e["id"] for e in run_events} <= {part["id"] for part in written}, "an event reached the stream directly"
    # the card layer (approval.resolved), the outbox (data.transfer) and the run all end at the same writer
    assert {"world.started", "approval.requested", "approval.resolved", "data.transfer", "world.completed"} <= {
        part["type"] for part in written
    }
    assert len({e["id"] for e in run_flow.stream()}) == len(run_flow.stream())


def test_CP2_no_event_of_a_run_carries_a_model_id(run_flow):
    """PL-01: model ids live in config/ and packages/providers only. The stream is user-visible and replayable."""
    run_flow.run_to_completion()
    ids: set[str] = set()
    for name in ("models.yaml", "models.nim.yaml", "models.gemini.yaml"):
        profiles = yaml.safe_load((REPO_ROOT / "config" / name).read_text(encoding="utf-8"))["profiles"]
        ids |= {str(profile["model"]) for profile in profiles.values()}
    assert ids, "expected model ids in config/"

    text = json.dumps(run_flow.stream())

    assert not [model for model in ids if model in text]


@pytest.mark.parametrize("cap", [1, 7.5, 500])
def test_CP2_the_budget_is_never_exceeded(run_flow, cap):
    run_flow.start()
    assert run_flow.approve(cap=cap).status_code == 200
    (started,) = wait_for(lambda: run_flow.events("world.started"), what="world.started")
    requested = wait_for(lambda: run_flow.events("approval.requested"), what="approval.requested")[0]
    card_id = requested["data"]["card_id"]
    assert run_flow.answer(card_id, "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    events = run_flow.stream()
    completed = only(events, "world.completed")
    assert started["data"]["budget_cap"] == cap
    spent = sum(e["credits"] for e in events)
    assert 0 <= spent <= cap and 0 <= completed["data"]["credits_used"] <= cap
    assert abs(completed["data"]["credits_used"] - spent) < 1e-9  # the meter is the sum of recorded events (HR-1)
