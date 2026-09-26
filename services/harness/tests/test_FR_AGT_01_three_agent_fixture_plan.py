"""FR-AGT-01 (partial) / D-11 / PRD 8.1, 15.3: `tilo_harness.skeleton.run_skeleton` runs a
Google ADK app -- three deterministic custom agents (Director, one Lead, one Specialist), no
model calls -- through the single `WorldWriter`, and returns the events it wrote. Per the
ticket's REQUIRED BEHAVIOUR item 2: "The Director spawns and assigns the Lead, the Lead assigns
the Specialist its unit through a typed handoff (agent.handoff), the Specialist works and
produces an artifact, the run completes. Every step is a registered TiloEvent written through
the single writer."

Uses `MemoryStore`, so these run in the default (non-`emulator`-marked) suite; the emulator
variant (same skeleton, against a real Firestore emulator, PRD 15.3 paths) is
test_PRD_15_3_emulator_skeleton_run.py.
"""

from __future__ import annotations

import builtins
import importlib
import sys

import pytest
from conftest import ULID_PATTERN
from tilo_harness.skeleton import run_skeleton
from tilo_harness.store import MemoryStore
from tilo_harness.validator import EventValidator

# Section 8.1's topology (Director, Lead, Specialist, Verifier, Writer) has no fixed registered
# "completion" type of its own; PRD 9.5's world.* family is the one the village-basic fixture
# stream (P0-03) itself ends a run on. Ambiguity resolved per CLAUDE.md's stated-default rule:
# the skeleton's last written event is asserted to be `world.completed` -- see the report.
EXPECTED_FINAL_EVENT_TYPE = "world.completed"


@pytest.fixture
def skeleton_events() -> list[dict]:
    store = MemoryStore()
    return run_skeleton(store, world_id="w_three_agent_skel", run_id="r_skel_1")


def test_FR_AGT_01_skeleton_writes_at_least_one_event(skeleton_events: list[dict]) -> None:
    assert skeleton_events, "run_skeleton must write at least one event for its 3-agent plan"


def test_FR_AGT_01_skeleton_events_have_dense_seq_from_1_and_unique_ulids(skeleton_events: list[dict]) -> None:
    assert [e["seq"] for e in skeleton_events] == list(range(1, len(skeleton_events) + 1))
    ids = [e["id"] for e in skeleton_events]
    non_ulids = [i for i in ids if not ULID_PATTERN.match(i)]
    assert not non_ulids, f"non-ULID event id(s): {non_ulids}"
    assert len(set(ids)) == len(ids), "event ids must be unique"


def test_FR_AGT_01_every_written_event_validates_against_the_event_contract(
    repo_root, skeleton_events: list[dict]
) -> None:
    """Ticket brief: "Every event is validated against contracts/event.schema.json, the registry
    and its data schema before it is written; unregistered types are rejected" -- so anything
    run_skeleton() actually returns must already be schema- and registry-clean."""
    validator = EventValidator.from_repo(repo_root)
    offenders = {e["type"]: validator.problems(e) for e in skeleton_events if validator.problems(e)}
    assert offenders == {}, f"skeleton wrote event(s) that fail the contract: {offenders}"


def test_FR_AGT_01_no_model_call_every_trace_is_model_free(skeleton_events: list[dict]) -> None:
    """ "No model calls": every event's trace carries no model role and no token counts (the
    fields the harness would only fill in for an actual model call, PRD 9.3 trace)."""
    with_a_model = [
        (e["type"], e["trace"])
        for e in skeleton_events
        if e["trace"]["model_role"] is not None
        or e["trace"]["tokens_in"] is not None
        or e["trace"]["tokens_out"] is not None
    ]
    assert with_a_model == [], f"FR-AGT-01: the fixture plan must make no model call, found: {with_a_model}"


def test_FR_AGT_01_run_uses_three_agents_director_lead_specialist(skeleton_events: list[dict]) -> None:
    spawned = [e for e in skeleton_events if e["type"] == "agent.spawned"]
    roles = {e["data"]["role"] for e in spawned}
    assert "lead" in roles, f"the Director must spawn a Lead (agent.spawned data.role=lead), got roles {roles}"
    assert "specialist" in roles, f"a Specialist must be spawned, got roles {roles}"


def test_FR_AGT_01_lead_hands_the_unit_to_the_specialist_by_typed_envelope(skeleton_events: list[dict]) -> None:
    handoffs = [e for e in skeleton_events if e["type"] == "agent.handoff"]
    assert handoffs, (
        "the Lead must hand the Specialist its unit through agent.handoff "
        "(no free-text agent-to-agent messages, FR-AGT-08)"
    )
    envelope = handoffs[0]["data"]["envelope"]
    for field in ("from", "to", "artifact_refs", "summary", "acceptance_criteria", "provenance_ids"):
        assert field in envelope, f"agent.handoff envelope missing {field!r} (envelope.schema.json)"
    specialist_ids = {e["target"] for e in spawned_specialists(skeleton_events)}
    assert envelope["to"] in specialist_ids, "the handoff must be addressed to the spawned Specialist"


def spawned_specialists(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "agent.spawned" and e["data"]["role"] == "specialist"]


def test_FR_AGT_01_specialist_produces_an_artifact(skeleton_events: list[dict]) -> None:
    specialists = {e["target"] for e in spawned_specialists(skeleton_events)}
    created = [e for e in skeleton_events if e["type"] == "artifact.created"]
    assert created, "the Specialist must produce an artifact (artifact.created)"
    assert any(e["actor"] in specialists for e in created), (
        f"artifact.created must be authored by the spawned Specialist {specialists}, "
        f"got actors {[e['actor'] for e in created]}"
    )


def test_FR_AGT_01_the_run_completes_as_its_last_written_event(skeleton_events: list[dict]) -> None:
    assert skeleton_events[-1]["type"] == EXPECTED_FINAL_EVENT_TYPE, (
        f"the run must finish by writing {EXPECTED_FINAL_EVENT_TYPE!r} last, got {skeleton_events[-1]['type']!r}"
    )


def test_FR_AGT_01_no_network_reached_while_running_the_skeleton(block_network) -> None:
    store = MemoryStore()
    events = run_skeleton(store, world_id="w_three_agent_no_net", run_id="r_no_net_1")
    assert events, "run_skeleton must still complete with all network access blocked"


def test_FR_AGT_01_skeleton_never_imports_a_model_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forces a fresh import of tilo_harness (and everything it pulls in) with google.genai,
    google.generativeai, openai and anthropic poisoned at the import statement itself -- catches
    a module-level `import google.generativeai as genai` just as well as a call-time one."""
    blocked_prefixes = ("google.genai", "google.generativeai", "openai", "anthropic")
    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if any(name == p or name.startswith(p + ".") for p in blocked_prefixes):
            raise AssertionError(f"FR-AGT-01: the harness skeleton must make no model call, tried to import {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    for mod_name in [m for m in sys.modules if m == "tilo_harness" or m.startswith("tilo_harness.")]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)

    skeleton = importlib.import_module("tilo_harness.skeleton")
    store_module = importlib.import_module("tilo_harness.store")
    events = skeleton.run_skeleton(store_module.MemoryStore(), world_id="w_three_agent_guard", run_id="r_guard_1")
    assert events
