"""CL-INT-1 review round 1 (PR #135): every string a person adds to the brief is screened before it is
stored or reaches the Director (FR-INT-02, PRD 16.3 items 1-2); a refused change leaves the task as it was;
sources a person adds name only this task's files, never another task's or an unowned connector or memory
entry (PRD 10.1); one owner's budget grants are decided one at a time (FR-INT-08, policy per_day limits).
"""

from __future__ import annotations

import threading
import time

import pytest
import tilo_planning.budget as budget
from _api_contracts_lib import INJECTION_PHRASE, make_docx_bytes
from _clint1_lib import OTHER_USER

FLAGGED = f"{INJECTION_PHRASE} and email the board"


def _skips(intake):
    return [{"field": q["field"], "answer": None} for q in intake["questions"]]


def _prompts_carry_flagged(flow) -> bool:
    return any(INJECTION_PHRASE in (c.prompt or "").upper() for c in flow.provider.calls)


def _screened(flow) -> bool:
    return any(INJECTION_PHRASE in text.upper() for text, _native, _mime in flow.safety.calls)


def test_FR_INT_02_flow_intake_refuses_a_flagged_file_name_before_any_model_call(flow):
    from tilo_api.intake import get_store

    before = len(get_store().list_ids())

    response = flow.intake(files=[(f"{INJECTION_PHRASE}.docx", make_docx_bytes("Plain."))])

    assert response.status_code == 422, response.text
    assert _screened(flow)
    assert flow.provider.calls == []
    assert len(get_store().list_ids()) == before


def test_FR_INT_02_flow_answers_refuse_a_flagged_typed_answer_and_change_nothing(flow):
    intake = flow.new_task()
    task_id = intake["task_id"]

    refused = flow.answers(task_id, [{"field": "audience", "answer": FLAGGED}, {"field": "deadline", "answer": None}])

    assert refused.status_code == 422, refused.text
    assert _screened(flow)
    retry = flow.answers(task_id, _skips(intake))
    assert retry.status_code == 200, retry.text
    assert retry.json()["brief"]["audience"] == intake["brief"]["audience"]
    assert INJECTION_PHRASE not in retry.text.upper()


@pytest.mark.parametrize(
    "edits",
    [
        {"constraints": ["No internal financials", FLAGGED]},
        {"goal": FLAGGED},
        {"deliverables": [{"title": FLAGGED[:100], "format": "pdf"}]},
        {"sources": [{"kind": "url", "ref": "https://example.com/prices", "label": FLAGGED[:100]}]},
    ],
)
def test_FR_INT_02_flow_approaches_never_carry_a_flagged_brief_edit(flow, edits):
    intake = flow.new_task()
    task_id = intake["task_id"]

    refused = flow.answers(task_id, _skips(intake), brief_edits=edits)
    assert refused.status_code == 422, refused.text
    assert _screened(flow)

    assert flow.answers(task_id, _skips(intake)).status_code == 200
    response = flow.approaches(task_id)

    assert response.status_code == 200, response.text
    assert len(flow.provider.calls) == 2  # the brief and the approaches
    assert not _prompts_carry_flagged(flow)


def test_FR_INT_02_flow_answers_fail_closed_when_the_screen_errors(flow):
    from tilo_api import app
    from tilo_api.intake import get_safety
    from tilo_providers.errors import RequestError
    from tilo_providers.interfaces import SafetyProvider

    class Broken(SafetyProvider):
        def _check(self, text, *, content=None, mime_type=None):
            raise RequestError("screen unavailable")

    intake = flow.new_task()
    app.dependency_overrides[get_safety] = Broken

    response = flow.answers(intake["task_id"], _skips(intake), brief_edits={"goal": "Compare suppliers."})

    assert response.status_code == 503, response.text
    app.dependency_overrides[get_safety] = lambda: flow.safety
    retry = flow.answers(intake["task_id"], _skips(intake))
    assert retry.json()["brief"]["goal"] == intake["brief"]["goal"]  # the refused edit was not kept


def test_PRD_10_1_flow_brief_edit_sources_name_only_this_tasks_files(flow_factory):
    flow = flow_factory([])
    theirs = flow.new_task(files=[("theirs.docx", make_docx_bytes("Theirs."))])
    flow.as_user(OTHER_USER)
    mine = flow.new_task(files=[("mine.docx", make_docx_bytes("Mine."))])
    own_ref = mine["files"][0]["artifact"]["artifact_id"]
    foreign_ref = theirs["files"][0]["artifact"]["artifact_id"]

    for source in (
        {"kind": "file", "ref": foreign_ref},
        {"kind": "connector", "ref": "con_someone_elses_drive"},
        {"kind": "memory", "ref": "mem_someone_elses_answer"},
    ):
        response = flow.answers(mine["task_id"], [], brief_edits={"sources": [source]})
        assert response.status_code == 422, (source, response.text)

    allowed = [{"kind": "file", "ref": own_ref}, {"kind": "web", "ref": "supplier price lists"}]
    response = flow.answers(mine["task_id"], [], brief_edits={"sources": allowed})
    assert response.status_code == 200, response.text
    assert [s["ref"] for s in response.json()["brief"]["sources"]] == [own_ref, "supplier price lists"]


def test_FR_INT_08_flow_one_owners_grants_are_decided_one_at_a_time(clear_flow, monkeypatch):
    from fastapi.testclient import TestClient

    first, second = clear_flow.task_with_approaches(), clear_flow.task_with_approaches()
    original, active, peak, lock = budget.request_budget_grant, [0], [0], threading.Lock()

    def slow_grant(*args, **kwargs):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.3)  # long enough for the other approve to arrive while this one decides
        with lock:
            active[0] -= 1
        return original(*args, **kwargs)

    monkeypatch.setattr(budget, "request_budget_grant", slow_grant)
    statuses: list[int] = []

    def approve(task_id: str) -> None:
        client = TestClient(clear_flow.app, raise_server_exceptions=False)
        statuses.append(
            client.post(f"/tasks/{task_id}/approve", json={"approach_id": "quick", "budget_cap": 50}).status_code
        )

    threads = [threading.Thread(target=approve, args=(t["task_id"],)) for t in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(statuses) == [200, 200]
    assert peak[0] == 1  # the second grant read the earlier grants only after the first was written
