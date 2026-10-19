"""GEN-06: peer handoffs carry the stored design/review note."""

import asyncio

from agt_output_support import make_rig
from test_FR_AGT_08_typed_handoffs_only import ORG, _setup
from tilo_harness.executor import UnitOutcome, run_plan
from tilo_harness.outputs import UnitOutput


def test_GEN_06_design_review_revisions_and_writer_exchange_real_notes(tmp_path):
    specs = [
        ("U1", "D1", []),
        ("U2", "D1", []),
        ("U3", "D1", ["U1", "U2"]),
        ("U4", "D1", ["U3"]),
        ("U5", "D1", ["U3"]),
        ("U6", "D1", ["U4", "U5"]),
    ]
    outcomes = {
        uid: UnitOutcome(
            success=True,
            summary="Finished.",
            outputs=(UnitOutput(media_type="text/markdown", content=f"Actual note {uid}".encode()),),
        )
        for uid, _, _ in specs
    }
    plan, layout, config, skills, (writer, store), runner = _setup(tmp_path, "w_design_peers", specs, outcomes)
    types = [
        "design_layout",
        "design_content",
        "design_review",
        "design_revise_layout",
        "design_revise_content",
        "deliver",
    ]
    for unit, kind in zip(plan["units"], types):
        unit["unit_type"] = kind
    rig = make_rig(world_id="w_design_peers")
    result = asyncio.run(
        run_plan(
            plan,
            layout,
            writer=writer,
            config=config,
            skills=skills,
            runner=runner,
            artifacts=rig.store,
            scope=rig.scope,
            redact=rig.redactor,
        )
    )
    assert result.failed == []
    events = store.read_events(ORG, "w_design_peers")
    peers = [e for e in events if e["type"] == "agent.handoff" and e["target"] != "A_lead1"]
    expected = [(dep, uid) for uid, _, deps in specs for dep in deps]
    assert {(e["actor"], e["target"]) for e in peers} == {(runner.workers[a], runner.workers[b]) for a, b in expected}
    for event in peers:
        source = next(uid for uid, worker in runner.workers.items() if worker == event["actor"])
        assert event["data"]["envelope"]["summary"] == f"Actual note {source}"
