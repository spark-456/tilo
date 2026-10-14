"""FR-INT-01..06 / SIMPLE-RUN: all skips reach a real run, or an unavailable store refuses loudly."""

from datetime import date

import pytest
from _clint2_lib import build_run_flow, wait_for
from tilo_api import deps, tasks


@pytest.mark.parametrize("stores_configured", [True, False])
def test_FR_INT_01_06_SIMPLE_RUN_all_skips_to_recommended_run(repo_root, monkeypatch, stores_configured):
    rig = build_run_flow(repo_root, ambiguous=["deadline", "audience", "constraints"], covered=True)
    flow = rig.flow
    flow.provider.brief["questions"] = [
        {
            "label": "Deadline",
            "text": "When do you need the supplier summary?",
            "suggested_answers": ["Today", "Tomorrow"],
            "expected_change": 0.9,
        },
        {
            "label": "Delivery date",
            "text": "What date should the supplier summary be ready?",
            "suggested_answers": ["Today", "Friday"],
            "expected_change": 0.8,
        },
        {
            "label": "Audience",
            "text": "Who will read the supplier summary?",
            "suggested_answers": ["Operations lead", "Finance team"],
            "expected_change": 0.7,
        },
    ]
    flow.app.dependency_overrides[deps.get_today] = lambda: lambda: date(2026, 10, 14)
    # Exercise the deployed refusal rule without replacing any HTTP handler or run starter.
    monkeypatch.setattr(tasks, "_loud", lambda: True)
    if not stores_configured:

        def unavailable_outbox():
            raise RuntimeError("run outbox store is not configured")

        flow.app.dependency_overrides[deps.get_outbox_store] = unavailable_outbox
    try:
        intake = flow.new_task(text="Prepare a weekly supplier-price summary for the operations lead.")
        rig.task_id, rig.world_id = intake["task_id"], intake["world_id"]
        questions = intake["questions"]
        assert 1 <= len(questions) <= 3
        assert len({q["field"] for q in questions}) == len(questions)
        assert sum(q["field"] == "deadline" for q in questions) == 1
        answers = flow.answers(rig.task_id, [{"field": q["field"], "answer": None} for q in questions])
        assert answers.status_code == 200, answers.text
        approaches = flow.approaches(rig.task_id)
        assert approaches.status_code == 200, approaches.text
        choices = approaches.json()
        assert choices["recommended"] in {a["id"] for a in choices["approaches"]}
        approved = flow.approve(rig.task_id, choices["recommended"], 60)
        if not stores_configured:
            assert approved.status_code == 503, approved.text
            assert "nothing was charged" in approved.json()["detail"]
            assert "Start again" in approved.json()["detail"]
            assert not rig.events("budget.granted")
            assert not rig.events("world.started")
            assert not rig.store.tasks[rig.task_id].granted
            return
        assert approved.status_code == 200, approved.text
        assert approved.json() == {"world_id": rig.world_id}
        (started,) = wait_for(lambda: rig.events("world.started"), what="recommended run to start")
        assert started["world_id"] == rig.world_id
        (grant,) = rig.events("budget.granted")
        assert grant["data"] == {"granted": 60, "cap": 60}
        assert rig.compile_calls[0]["approach"]["id"] == choices["recommended"]
        assert not rig.adapter.sent
    finally:
        rig.close()
