"""FR-AGT-12 (PRD 8.1, 8.6, 9.5): "Independent Verifier on every deliverable."

Given a plan whose successful units hand over three artifacts (one clean, one with a planted wrong
number, one the archive cannot load) and one unit that fails, When the plan runs with a Verifier,
Then every handed-over artifact gets exactly one `artifact.reviewed` after the handoff that carried
it, signed by the verifier-rank agent (never the producing worker), with the result the Verifier
judged (passed, failed, and unverified for the one it could not load), the unit that failed gets none,
and every event is valid. Without a Verifier `run_plan` behaves as before.
"""

from __future__ import annotations

import asyncio
import json

from agt_scripted import ScriptedProvider
from agt_support import (
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from agt_verifier_support import VERIFIER, build_manifest, claim, deliverable_of, make_verifier, note_for
from conftest import make_memory_writer
from tilo_harness.executor import UnitOutcome, run_plan
from tilo_harness.validator import EventValidator

WORLD = "w_review_all"
GOOD, WRONG, GHOST = (
    {"artifact_id": "art_good", "version": 1},
    {"artifact_id": "art_wrong", "version": 1},
    {"artifact_id": "art_ghost", "version": 1},
)


class HandoffRunner:
    """A UnitRunner double: U1 hands over GOOD and WRONG, U2 hands over GHOST, U3 fails."""

    refs = {"U1": (GOOD, WRONG), "U2": (GHOST,), "U3": ()}

    async def run(self, unit, context):
        await asyncio.sleep(0)
        return UnitOutcome(
            success=unit["id"] != "U3", summary=f"Finished {unit['id']}.", artifact_refs=self.refs[unit["id"]]
        )


def _deliverable(ref, text):
    source = note_for(5)
    manifest = build_manifest(
        artifact_id=ref["artifact_id"], sources={"src_a": source}, claims=[claim("cl_1", text, ["src_a"])]
    )
    return deliverable_of(manifest, {"src_a": source})


def _loader():
    held = {
        "art_good": _deliverable(GOOD, "Firm Faa reported revenue of 45 million."),
        "art_wrong": _deliverable(WRONG, "Firm Faa reported revenue of 945 million."),
    }

    def load(ref):
        return held[ref["artifact_id"]]  # art_ghost: KeyError, the archive cannot load it

    return load


def _run(tmp_path, *, with_verifier: bool):
    layout = build_layout(
        world_id=WORLD,
        district_specs=[
            {"id": "D1", "lead": "A_lead", "specialists": ["A_s0", "A_s1", "A_s2"], "unit_ids": ["U1", "U2", "U3"]}
        ],
        extra_agents=[{"id": VERIFIER, "rank": "verifier"}],
    )
    plan = build_plan([build_unit("U1"), build_unit("U2"), build_unit("U3")])
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id=WORLD)
    model = ScriptedProvider(default=json.dumps({"verdict": "supported"}))
    verifier, _providers = make_verifier(model, load=_loader())
    kwargs = {"verifier": verifier} if with_verifier else {}

    asyncio.run(
        asyncio.wait_for(
            run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=HandoffRunner(), **kwargs), 20
        )
    )
    return store.read_events("org_demo", WORLD), model


def test_FR_AGT_12_every_handed_over_artifact_gets_exactly_one_review_after_its_handoff(tmp_path) -> None:
    events, _model = _run(tmp_path, with_verifier=True)

    reviews = [e for e in events if e["type"] == "artifact.reviewed"]
    by_artifact = {e["data"]["artifact"]["artifact_id"]: e for e in reviews}
    assert len(reviews) == 3 and set(by_artifact) == {"art_good", "art_wrong", "art_ghost"}, [
        e["target"] for e in reviews
    ]

    assert by_artifact["art_good"]["data"]["result"] == "passed"
    assert by_artifact["art_wrong"]["data"]["result"] == "failed", "the planted wrong number is caught"
    assert by_artifact["art_ghost"]["data"]["result"] == "unverified", "an artifact it cannot load is never skipped"

    for artifact_id, review in by_artifact.items():
        handoff = next(
            e
            for e in events
            if e["type"] == "agent.handoff"
            and any(r["artifact_id"] == artifact_id for r in e["data"]["envelope"]["artifact_refs"])
        )
        assert handoff["seq"] < review["seq"], f"{artifact_id} is reviewed after it is handed over"
        assert review["cause"] == handoff["id"]
        assert review["target"] == artifact_id and review["data"]["artifact"]["version"] == 1


def test_FR_AGT_12_the_reviewer_is_the_verifier_agent_never_the_producing_worker(tmp_path) -> None:
    events, _model = _run(tmp_path, with_verifier=True)
    reviews = [e for e in events if e["type"] == "artifact.reviewed"]
    workers = {e["target"] for e in events if e["type"] == "agent.assigned"}
    assert {e["actor"] for e in reviews} == {VERIFIER}
    assert VERIFIER not in workers, "the Verifier was not one of the unit workers"
    good = next(e for e in reviews if e["target"] == "art_good")
    assert good["trace"]["model_role"] == "verifier", (
        "a review that called a model records the role, never a model id (PL-01)"
    )


def test_FR_AGT_12_a_failed_unit_hands_over_nothing_so_nothing_is_reviewed(tmp_path) -> None:
    events, _model = _run(tmp_path, with_verifier=True)
    u3_worker = next(e["target"] for e in events if e["type"] == "agent.assigned" and e["data"]["unit"] == "U3")
    assert not any(e["type"] == "agent.handoff" and e["data"]["envelope"]["from"] == u3_worker for e in events)
    assert len([e for e in events if e["type"] == "artifact.reviewed"]) == 3


def test_FR_AGT_12_review_events_are_registered_valid_and_seq_stays_dense(tmp_path, repo_root) -> None:
    events, _model = _run(tmp_path, with_verifier=True)
    validator = EventValidator.from_repo(repo_root)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert {i: validator.problems(e) for i, e in enumerate(events) if validator.problems(e)} == {}


def test_FR_AGT_12_without_a_verifier_run_plan_writes_no_review(tmp_path) -> None:
    events, model = _run(tmp_path, with_verifier=False)
    assert [e for e in events if e["type"] == "artifact.reviewed"] == []
    assert model.call_count == 0


def test_FR_AGT_12_review_and_record_writes_one_artifact_reviewed_event_through_the_writer() -> None:
    layout = build_layout(
        world_id=WORLD,
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0"], "unit_ids": ["U1"]}],
        extra_agents=[{"id": VERIFIER, "rank": "verifier"}],
    )
    writer, store = make_memory_writer(layout, world_id=WORLD)
    verifier, _providers = make_verifier(ScriptedProvider(default=json.dumps({"verdict": "supported"})), load=_loader())

    review = asyncio.run(verifier.review_and_record(WRONG, writer=writer, district="D1"))

    (event,) = store.read_events("org_demo", WORLD)
    assert event["type"] == "artifact.reviewed" and event["actor"] == VERIFIER and event["target"] == "art_wrong"
    assert review.result == "failed"
    assert event["data"] == {"artifact": WRONG, "result": "failed"}
    assert event["district"] == "D1" and event["severity"] == "info"
