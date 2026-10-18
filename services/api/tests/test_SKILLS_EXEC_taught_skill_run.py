"""SKILLS-EXEC: a taught skill stays executable from capture through a tagged run."""

from __future__ import annotations

import copy
import json

from _clint1_lib import FLOW_USER, build_router, seam
from _clint2_lib import wait_for
from _ppl11a_lib import STANDARD_PERSONS
from _skills4_lib import Scripted
from tilo_api import deps
from tilo_api.durable_store import _task_doc, _task_from
from tilo_api.skill_store import MemorySkillStore
from tilo_people.stores import PeopleStores


def test_SKILLS_EXEC_taught_skill_plan_drives_tagged_run_to_result(run_flow, repo_root):
    description = "Draft a supplier reply for me."
    model = Scripted()
    model.captures[description] = [
        "Read the supplier message",
        "Draft the supplier reply",
        "Send the supplier reply",
    ]
    model.versions[description] = {
        "steps": [
            {
                "text": "Draft the supplier reply",
                "tool": "writer",
                "action": "compose",
                "verb": "write",
            }
        ],
        "question": None,
    }
    skills = MemorySkillStore()
    people = PeopleStores.in_memory()
    person = copy.deepcopy(STANDARD_PERSONS["u_owner"])
    person["id"] = FLOW_USER
    person["org_id"] = deps.ORG_ID
    person["email"] = "flow@example.com"
    person["created_by"]["by"] = FLOW_USER
    person["memberships"] = []
    people.persons.create(person)
    overrides = run_flow.app.dependency_overrides
    overrides[deps.get_router] = lambda: build_router(repo_root, model)
    overrides[seam(deps, "get_skill_store")] = lambda: skills
    overrides[seam(deps, "get_people_stores")] = lambda: people
    desk = "w_desk_" + FLOW_USER[2:]
    overrides[seam(deps, "get_desk_worlds")] = lambda: type(
        "Desks",
        (),
        {
            "desk_world": staticmethod(lambda org, owner: desk),
            "desk_owner": staticmethod(lambda world: FLOW_USER if world == desk else None),
        },
    )()

    model.last_description = description
    client = run_flow.flow.client
    captured = client.post("/v1/skills/captures", json={"method": "describe", "text": description})
    assert captured.status_code == 201, captured.text
    proposed = client.post(f"/v1/skills/captures/{captured.json()['capture_id']}/version")
    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()
    saved = client.post(
        "/v1/skills",
        json={
            "name": "Supplier reply",
            "scope": {"kind": "just_me", "team": None},
            "trigger": {"kind": "on_demand"},
            "plan_steps": [
                {key: step[key] for key in ("text", "tool", "action", "verb")} for step in proposal["plan_steps"]
            ],
            "captured_steps": captured.json()["captured_steps"],
        },
    )
    assert saved.status_code == 201, saved.text
    skill = saved.json()
    overrides[deps.get_router] = lambda: run_flow.flow.router

    intake = client.post(
        "/intake",
        data={
            "text": "Reply to the supplier",
            "refs": json.dumps([{"kind": "taught_skill", "id": skill["id"]}]),
        },
    )
    assert intake.status_code == 201, intake.text
    approaches = run_flow.flow.approaches(intake.json()["task_id"])
    assert approaches.status_code == 200, approaches.text
    run_flow.task_id, run_flow.world_id = intake.json()["task_id"], intake.json()["world_id"]
    run_flow.as_member()

    started = run_flow.flow.approve(run_flow.task_id, approaches.json()["recommended"], 60)
    assert started.status_code == 200, started.text
    wait_for(lambda: run_flow.events("world.completed"), what="the taught skill result")

    executed = run_flow.store.runs[run_flow.world_id].plan
    assert [unit["title"] for unit in executed["units"]] == [
        "Draft the supplier reply",
        "Deliver the finished work",
    ]
    assert run_flow.runner.ran == ["U1", "U2"]
    assert run_flow.events("artifact.delivered")


def test_SKILLS_EXEC_taught_skill_plan_survives_task_store_round_trip():
    task = deps.TaskRecord("u_owner", "w_task", "r_task", {}, {}, [], 1)
    task.skill_plan = [{"text": "Read the page", "tool": "web", "action": "fetch_url", "verb": "read"}]

    restored = _task_from(_task_doc(task))

    assert restored.skill_plan == task.skill_plan
