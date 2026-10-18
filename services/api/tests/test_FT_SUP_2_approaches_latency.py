"""FT-SUP-2: approaches latency.
When intake creates a task with no clarifying questions, approaches prefetch is queued
immediately so GET /tasks/{task_id}/approaches returns without waiting for prefetch scheduling.
"""

from __future__ import annotations


def test_FT_SUP_2_create_task_prefetches_approaches_when_no_questions(clear_flow):
    intake = clear_flow.new_task()
    task_id = intake["task_id"]

    task = clear_flow.store.tasks[task_id]
    assert task.questions == []
    # Prefetch was queued during intake (FT-SUP-2)
    assert task.approaches_work.get("future") is not None

    response = clear_flow.approaches(task_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task_id
    assert len(body["approaches"]) >= 2
    assert body["recommended"] in {a["id"] for a in body["approaches"]}
