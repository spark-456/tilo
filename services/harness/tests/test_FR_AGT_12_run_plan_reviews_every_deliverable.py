"""FR-AGT-12 (PRD 8.1, 8.6, 9.5): "Independent Verifier on every deliverable."

Given a plan whose successful units hand over three artifacts (one clean, one with a planted wrong
number, one the archive cannot load) and one unit that fails, When the plan runs with a Verifier,
Then every handed-over artifact gets exactly one `artifact.reviewed` after the handoff that carried
it, signed by the verifier-rank agent (never the producing worker), with the result the Verifier
judged (passed, failed, and unverified for the one it could not load), the unit that failed gets none,
and every event is valid. Without a Verifier `run_plan` behaves as before.

T3 (ADR-0018 s5, EV-15): the artifacts are now outputs the executor stores and announces (`artifact.created`), so a
review always names a version the world recorded. The ids are the store's: the tests tell the three apart by content.
"""

from __future__ import annotations

import asyncio
import json

from agt_output_support import make_rig, outcome, run_units, unit_output
from agt_scripted import ScriptedProvider
from agt_support import build_layout
from agt_verifier_support import VERIFIER, build_manifest, claim, deliverable_of, make_verifier, note_for
from conftest import make_memory_writer
from tilo_harness.validator import EventValidator

WORLD = "w_review_all"
CONTENT = {"good": b"good", "wrong": b"wrong", "ghost": b"ghost"}
WRONG = {"artifact_id": "art_wrong", "version": 1}


class HandoffRunner:
    """A UnitRunner double: U1 outputs "good" and "wrong", U2 outputs "ghost", U3 fails."""

    outputs = {"U1": ("good", "wrong"), "U2": ("ghost",), "U3": ()}

    async def run(self, unit, context):
        await asyncio.sleep(0)
        outputs = [unit_output(CONTENT[name]) for name in self.outputs[unit["id"]]]
        return outcome(outputs, success=unit["id"] != "U3", summary=f"Finished {unit['id']}.")


def _deliverable(ref, text):
    source = note_for(5)
    manifest = build_manifest(
        artifact_id=ref["artifact_id"], sources={"src_a": source}, claims=[claim("cl_1", text, ["src_a"])]
    )
    return deliverable_of(manifest, {"src_a": source})


def _loader(rig):
    held = {
        CONTENT["good"]: "Firm Faa reported revenue of 45 million.",
        CONTENT["wrong"]: "Firm Faa reported revenue of 945 million.",
    }

    def load(ref):
        return _deliverable(ref, held[rig.store.read(rig.scope, ref)])  # "ghost": KeyError, the archive cannot load it

    return load


def _run(tmp_path, *, with_verifier: bool):
    rig = make_rig(world_id=WORLD)
    model = ScriptedProvider(default=json.dumps({"verdict": "supported"}))
    verifier, _providers = make_verifier(model, load=_loader(rig))
    ran = run_units(
        tmp_path,
        {"U1": None, "U2": None, "U3": None},
        rig=rig,
        world_id=WORLD,
        runner=HandoffRunner(),
        verifier=verifier if with_verifier else None,
    )
    return ran.events, model, rig


def _names(events, rig):
    """artifact id -> "good" | "wrong" | "ghost", from what the store holds for each `artifact.created`."""
    by_content = {content: name for name, content in CONTENT.items()}
    return {
        e["data"]["artifact"]["artifact_id"]: by_content[rig.store.read(rig.scope, e["data"]["artifact"])]
        for e in events
        if e["type"] == "artifact.created"
    }


def test_FR_AGT_12_every_handed_over_artifact_gets_exactly_one_review_after_its_handoff(tmp_path) -> None:
    events, _model, rig = _run(tmp_path, with_verifier=True)
    names = _names(events, rig)

    reviews = [e for e in events if e["type"] == "artifact.reviewed"]
    by_name = {names[e["data"]["artifact"]["artifact_id"]]: e for e in reviews}
    assert len(reviews) == 3 and set(by_name) == {"good", "wrong", "ghost"}, [e["target"] for e in reviews]

    assert by_name["good"]["data"]["result"] == "passed"
    assert by_name["wrong"]["data"]["result"] == "failed", "the planted wrong number is caught"
    assert by_name["ghost"]["data"]["result"] == "unverified", "an artifact it cannot load is never skipped"

    for review in reviews:
        artifact_id = review["data"]["artifact"]["artifact_id"]
        handoff = next(
            e
            for e in events
            if e["type"] == "agent.handoff"
            and any(r["artifact_id"] == artifact_id for r in e["data"]["envelope"]["artifact_refs"])
        )
        created = next(e for e in events if e["type"] == "artifact.created" and e["target"] == artifact_id)
        assert created["seq"] < handoff["seq"] < review["seq"], f"{artifact_id} is reviewed after it is handed over"
        assert review["cause"] == handoff["id"]
        assert review["target"] == artifact_id and review["data"]["artifact"]["version"] == 1


def test_FR_AGT_12_the_reviewer_is_the_verifier_agent_never_the_producing_worker(tmp_path) -> None:
    events, _model, rig = _run(tmp_path, with_verifier=True)
    names = _names(events, rig)
    reviews = [e for e in events if e["type"] == "artifact.reviewed"]
    workers = {e["target"] for e in events if e["type"] == "agent.assigned"}
    assert {e["actor"] for e in reviews} == {VERIFIER}
    assert VERIFIER not in workers, "the Verifier was not one of the unit workers"
    good = next(e for e in reviews if names[e["target"]] == "good")
    assert good["trace"]["model_role"] == "verifier", (
        "a review that called a model records the role, never a model id (PL-01)"
    )


def test_FR_AGT_12_a_failed_unit_hands_over_nothing_so_nothing_is_reviewed(tmp_path) -> None:
    events, _model, _rig = _run(tmp_path, with_verifier=True)
    u3_worker = next(e["target"] for e in events if e["type"] == "agent.assigned" and e["data"]["unit"] == "U3")
    assert not any(e["type"] == "agent.handoff" and e["data"]["envelope"]["from"] == u3_worker for e in events)
    assert len([e for e in events if e["type"] == "artifact.reviewed"]) == 3


def test_FR_AGT_12_review_events_are_registered_valid_and_seq_stays_dense(tmp_path, repo_root) -> None:
    events, _model, _rig = _run(tmp_path, with_verifier=True)
    validator = EventValidator.from_repo(repo_root)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert {i: validator.problems(e) for i, e in enumerate(events) if validator.problems(e)} == {}


def test_FR_AGT_12_without_a_verifier_run_plan_writes_no_review(tmp_path) -> None:
    events, model, _rig = _run(tmp_path, with_verifier=False)
    assert [e for e in events if e["type"] == "artifact.reviewed"] == []
    assert model.call_count == 0


def test_FR_AGT_12_review_and_record_writes_one_artifact_reviewed_event_through_the_writer() -> None:
    layout = build_layout(
        world_id=WORLD,
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0"], "unit_ids": ["U1"]}],
        extra_agents=[{"id": VERIFIER, "rank": "verifier"}],
    )
    writer, store = make_memory_writer(layout, world_id=WORLD)
    rig = make_rig(world_id=WORLD)
    wrong = rig.store.put(rig.scope, _new_version(CONTENT["wrong"])).ref
    verifier, _providers = make_verifier(
        ScriptedProvider(default=json.dumps({"verdict": "supported"})), load=_loader(rig)
    )
    # EV-15: a review names a version the world recorded, so the world records it first.
    writer.emit(
        type="artifact.created",
        actor="A_s0",
        target=wrong["artifact_id"],
        level="L1",
        district="D1",
        summary="The agent made an item.",
        data={"artifact": wrong},
    )

    review = asyncio.run(verifier.review_and_record(wrong, writer=writer, district="D1"))

    _created, event = store.read_events("org_demo", WORLD)
    assert (
        event["type"] == "artifact.reviewed" and event["actor"] == VERIFIER and event["target"] == wrong["artifact_id"]
    )
    assert review.result == "failed"
    assert event["data"] == {"artifact": wrong, "result": "failed"}
    assert event["district"] == "D1" and event["severity"] == "info"


def _new_version(content: bytes):
    from agt_output_support import RUN
    from tilo_memory.artifacts import NewVersion, Origin

    return NewVersion(
        media_type="text/markdown",
        content=content,
        run_id=RUN,
        origin=Origin(kind="unit", unit="U1", agent="A_s0"),
        idempotency_key=f"{RUN}:U1:1:0",
    )
