"""TS-19 (taught_skill.rules.md): "A required input left empty stops the run before any model call with a needs-you
card." Fixture models only: no network, no paid call, no live switch.

Pinned interface:
  * `POST /intake` takes an optional `inputs` form field with a taught skill's ref: the run form's values, a JSON
    object of slot name -> text (at most 8, contract slot names, text of at most 300 characters; anything else is the
    422 `{"error": "The inputs are not valid."}`). A required slot with no value, or a run that sent no values at all
    (an @mention), is left empty; the task keeps their labels (`TaskRecord.skill_missing`).
  * The run's first unit (one that waits for nothing) does no work and no model call until the person answers one
    needs-you card: "This run needs <labels>. Type it below to go on." A typed value runs the work and is told to every
    later unit as one of the run's answers; "Go on without it" runs it as it is; Stop, or nobody answering by the
    deadline (its safe default), holds it.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from typing import Any

import pytest
import test_RUN_FAIL_1_tool_unit_after_answer as rig
from _clint2_lib import wait_for
from test_SKILLS_E2E_teach_and_run import GMAIL_PLAN, INVOICE_STEPS, INVOICES, _production, _save, _taught
from tilo_api import deps
from tilo_providers.safety import FakeSafetyProvider

SUPPLIER = {"name": "supplier", "label": "Supplier", "kind": "text", "required": True}
NOTE = {"name": "note", "label": "Anything else", "kind": "text", "required": False}
VERSION = {
    "steps": [
        {"text": "Search Gmail for invoices from the supplier", "tool": "gmail", "action": "search_email",
         "verb": "read"},
        {"text": "List each invoice's amount and due date", "tool": "none", "action": "none", "verb": "write"},
    ],
    "question": None,
    "inputs": [SUPPLIER, NOTE],
}  # fmt: skip
QUESTION = "This run needs Supplier. Type it below to go on."


def _skill(run_flow, repo_root) -> tuple[Any, dict[str, Any]]:
    t = _taught(run_flow, repo_root, INVOICES, INVOICE_STEPS, VERSION)
    captured = t.client.post("/v1/skills/captures", json={"method": "describe", "text": INVOICES}).json()
    proposal = t.client.post(f"/v1/skills/captures/{captured['capture_id']}/version", json={}).json()
    assert proposal["inputs"] == [SUPPLIER, NOTE]
    return t, _save(t, proposal, captured["captured_steps"], "Invoice digest")


def _intake(t: Any, skill: dict[str, Any], text: str, inputs: Any = None) -> Any:
    rf = t.run_flow
    rf.app.dependency_overrides[deps.get_router] = lambda: rf.flow.router  # the Director's fixture, after teaching
    body = {"text": text, "refs": json.dumps([{"kind": "taught_skill", "id": skill["id"]}])}
    if inputs is not None:
        body["inputs"] = inputs if isinstance(inputs, str) else json.dumps(inputs)
    return t.client.post("/intake", data=body, headers={"Idempotency-Key": str(uuid.uuid4())})


def _start(run_flow, t: Any, skill: dict[str, Any], text: str, inputs: Any = None) -> dict[str, Any]:
    made = _intake(t, skill, text, inputs)
    assert made.status_code == 201, made.text
    task = made.json()
    approaches = run_flow.flow.approaches(task["task_id"])
    assert approaches.status_code == 200, approaches.text
    run_flow.task_id, run_flow.world_id = task["task_id"], task["world_id"]
    run_flow.as_member()
    assert run_flow.flow.approve(run_flow.task_id, approaches.json()["recommended"], 60).status_code == 200
    return task


def _contexts(run_flow) -> list[Any]:
    seen: list[Any] = []
    original = run_flow.runner.run

    async def run(unit: Any, context: Any) -> Any:
        seen.append((unit["id"], context))
        return await original(unit, context)

    run_flow.runner.run = run
    return seen


@pytest.mark.parametrize(
    ("inputs", "missing"),
    [
        ({"supplier": "Globex"}, None),
        ({"supplier": "Globex", "note": ""}, None),  # an optional slot left empty asks nothing
        ({"supplier": "   ", "note": "only the new ones"}, ["Supplier"]),
        (None, ["Supplier"]),  # an @mention sends no values: a required slot is empty
    ],
)
def test_TS_19_intake_keeps_the_labels_of_the_required_inputs_left_empty(run_flow, repo_root, inputs, missing):
    t, skill = _skill(run_flow, repo_root)
    made = _intake(t, skill, "Run the Invoice digest skill.", inputs)
    assert made.status_code == 201, made.text
    assert run_flow.store.tasks[made.json()["task_id"]].skill_missing == missing


@pytest.mark.parametrize(
    "bad",
    [
        '{"Bad Name": "x"}',
        "[1]",
        '{"supplier": 7}',
        '{"supplier": "' + "x" * 301 + '"}',
        "{not json",
        json.dumps({f"slot_{i}": "x" for i in range(9)}),
    ],
)
def test_TS_19_inputs_that_are_not_a_run_forms_values_are_one_422_and_store_nothing(run_flow, repo_root, bad):
    t, skill = _skill(run_flow, repo_root)
    before = len(run_flow.store.tasks)
    made = _intake(t, skill, "Run the Invoice digest skill.", bad)
    assert made.status_code == 422 and made.json() == {"error": "The inputs are not valid."}
    assert len(run_flow.store.tasks) == before


def test_TS_19_an_empty_required_input_stops_the_run_on_one_card_and_the_typed_value_resumes_it(run_flow, repo_root):
    t, skill = _skill(run_flow, repo_root)
    seen = _contexts(run_flow)
    _start(run_flow, t, skill, "Run the Invoice digest skill.", {"supplier": ""})
    (routed,) = wait_for(lambda: run_flow.events("question.routed"), timeout=20, what="the missing-input card")
    assert run_flow.runner.ran == []  # nothing ran before the person answered
    cards = run_flow.flow.client.get(f"/worlds/{run_flow.world_id}/cards").json()
    (card,) = [c for c in cards if c["id"] == routed["data"]["card_id"]]
    assert card["what_happened"] == QUESTION and card["kind"] == "needs_you"
    assert [o["label"] for o in card["options"]] == ["Stop this run", "Go on without it"]
    assert card["safe_default"] == "o1"
    escalated = run_flow.events("agent.escalated")
    assert escalated and escalated[-1]["data"] == {"reason": "ambiguous_brief"}

    answered = run_flow.flow.client.post(
        f"/worlds/{run_flow.world_id}/cards/{card['id']}/answer", json={"text": "Globex"}
    )
    assert answered.status_code == 200, answered.text
    wait_for(lambda: run_flow.events("world.completed"), timeout=45, what="the resumed run to finish")
    assert run_flow.runner.ran[:2] == ["U1", "U2"]
    told = {unit: [a for _q, a in context.intake_answers] for unit, context in seen}
    assert "Globex" in told["U1"] and "Globex" in told["U2"]  # the value belongs to the whole run
    assert run_flow.events("artifact.delivered")
    assert len(run_flow.events("question.routed")) == 1  # one card, not one per step


def test_TS_19_stop_on_the_card_holds_the_run_and_nothing_runs(run_flow, repo_root):
    t, skill = _skill(run_flow, repo_root)
    _start(run_flow, t, skill, "only the new ones")  # an @mention: no values sent
    (routed,) = wait_for(lambda: run_flow.events("question.routed"), timeout=20, what="the missing-input card")
    stopped = run_flow.answer(routed["data"]["card_id"], "o1")
    assert stopped.status_code == 200, stopped.text
    wait_for(lambda: run_flow.events("world.failed"), timeout=30, what="the held run to stop")
    assert run_flow.runner.ran == [] and not run_flow.events("artifact.delivered")


def test_TS_19_go_on_without_it_runs_the_saved_steps_as_they_are(run_flow, repo_root):
    t, skill = _skill(run_flow, repo_root)
    _start(run_flow, t, skill, "Run the Invoice digest skill.", {})
    (routed,) = wait_for(lambda: run_flow.events("question.routed"), timeout=20, what="the missing-input card")
    assert run_flow.answer(routed["data"]["card_id"], "o2").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), timeout=45, what="the run to finish")
    assert run_flow.runner.ran[:2] == ["U1", "U2"]


def test_TS_19_a_run_with_its_required_inputs_given_asks_nothing(run_flow, repo_root):
    t, skill = _skill(run_flow, repo_root)
    _start(run_flow, t, skill, "Run the Invoice digest skill.\nSupplier: Globex", {"supplier": "Globex"})
    wait_for(lambda: run_flow.events("world.completed"), timeout=45, what="the run to finish")
    assert run_flow.events("question.routed") == []


def test_TS_19_the_missing_labels_survive_the_durable_task_store():
    from tilo_api.durable_store import _task_doc, _task_from

    task = deps.TaskRecord("u_owner", "w_task", "r_task", {}, {}, [], 1)
    task.skill_plan, task.skill_missing = [dict(GMAIL_PLAN[0])], ["Supplier"]
    assert _task_from(_task_doc(task)).skill_missing == ["Supplier"]


class Recording(rig.FakeModels):
    """The rig's fake SDK, also keeping what each call was sent."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.sent.append(f"{getattr(config, 'system_instruction', '')}\n{contents}")
        return super().generate_content(model=model, contents=contents, config=config)


def test_TS_19_on_the_production_runner_no_model_is_called_before_the_answer(tmp_path, monkeypatch):
    run, state, models = _production(tmp_path, monkeypatch, models_cls=Recording)
    run.skill_plan = copy.deepcopy(GMAIL_PLAN)
    run.skill_missing = ["Supplier"]
    asking = run.seams.must_ask_providers["specialist"]

    async def go() -> None:
        work = asyncio.ensure_future(run._execute())
        for _ in range(3000):
            routed = [e for e in state.events.get(rig.WORLD, []) if e["type"] == "question.routed"]
            if routed or work.done():
                break
            await asyncio.sleep(0.01)
        assert routed, "the run must ask for the empty input first"
        assert models.sent == [] and asking.prompts == []  # no unit and no must-ask model call yet
        card = run.cards.get(rig.WORLD, routed[0]["data"]["card_id"])
        assert card is not None and card["what_happened"] == QUESTION
        principal = deps.Principal(rig.OWNER, "owner", rig.WORLD)
        done = await asyncio.to_thread(
            run.cards.answer, rig.WORLD, card["id"], text="Globex", channel="web", principal=principal,
            safety=FakeSafetyProvider(),  # the route passes its own screen; the rig's store has none
        )  # fmt: skip
        assert done.outcome == "answered", done
        await asyncio.wait_for(work, timeout=60)

    asyncio.run(go())
    events = state.events[rig.WORLD]
    assert [e for e in events if e["type"] == "world.failed"] == []
    assert events[-1]["type"] == "world.completed"
    assert len(models.sent) >= 2 and all("Globex" in sent for sent in models.sent)  # every unit was told the value
