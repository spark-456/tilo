"""FT-SUP-2: approaches latency.
Intake returns without approaches work; the explicit GET requests it. This preserves
the web's visible progress while keeping each API request's effects inside that request.
"""

from __future__ import annotations


def test_LIVE25_FIX2_intake_does_not_prefetch_approaches_when_no_questions(clear_flow):
    intake = clear_flow.new_task()
    task_id = intake["task_id"]

    task = clear_flow.store.tasks[task_id]
    assert task.questions == []
    assert task.approaches_work == {}

    response = clear_flow.approaches(task_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task_id
    assert len(body["approaches"]) >= 2
    assert body["recommended"] in {a["id"] for a in body["approaches"]}
