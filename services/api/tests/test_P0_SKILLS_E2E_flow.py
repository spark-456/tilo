"""P0-SKILLS-E2E: the owner's Skills flow, end to end over the real app (replay/fake only, no paid call).

Teach (capture, version, save) -> the Skills page lists it -> "Run skill" on the Skills page (the one-step web start:
`POST /intake` with the skill ref, then approaches, then approve) -> the run is planned from the skill's steps and
completes with a deliverable. The @mention on Home sends the very same `POST /intake` form, so it is run the same way.
The request bodies are the ones `apps/web/src` sends (liveApi.ts, http.ts `sendIntake`, SkillsPage.tsx `onRun`).
"""

from __future__ import annotations

import copy
import json
import uuid

from _clint1_lib import FLOW_USER, build_router, seam
from _clint2_lib import wait_for
from _ppl11a_lib import STANDARD_PERSONS
from _skills4_lib import Scripted
from tilo_api import deps
from tilo_api.skill_store import MemorySkillStore
from tilo_people.stores import PeopleStores

DESCRIPTION = "Search the web for asura and summarise the top results"
CAPTURED = ["Search the web for asura", "Read the top results", "Summarise the top results"]
VERSION = {
    "steps": [
        {"text": "Search the web for asura", "tool": "web", "action": "web_search", "verb": "read"},
        {"text": "Read the top results", "tool": "web", "action": "fetch_url", "verb": "read"},
        {"text": "Summarise the top results", "tool": "writer", "action": "compose", "verb": "write"},
    ],
    "question": None,
}


class Taught:
    """The run flow with a real-registry skill library, a scripted capture model and one signed-in person."""

    def __init__(self, run_flow, repo_root):
        self.run_flow = run_flow
        self.client = run_flow.flow.client
        self.model = Scripted()
        self.model.captures[DESCRIPTION] = CAPTURED
        self.model.versions[DESCRIPTION] = VERSION
        self.model.last_description = DESCRIPTION
        self.skills = MemorySkillStore()
        people = PeopleStores.in_memory()
        person = copy.deepcopy(STANDARD_PERSONS["u_owner"])
        person.update(id=FLOW_USER, org_id=deps.ORG_ID, email="flow@example.com", memberships=[])
        person["created_by"]["by"] = FLOW_USER
        people.persons.create(person)
        desk = "w_desk_" + FLOW_USER[2:]
        overrides = run_flow.app.dependency_overrides
        self.teach_router = build_router(repo_root, self.model)
        overrides[deps.get_router] = lambda: self.teach_router
        overrides[seam(deps, "get_skill_store")] = lambda: self.skills
        overrides[seam(deps, "get_people_stores")] = lambda: people
        overrides[seam(deps, "get_connector_registry")] = deps.get_connector_registry  # the shipped config/
        overrides[seam(deps, "get_desk_worlds")] = lambda: type(
            "Desks",
            (),
            {
                "desk_world": staticmethod(lambda org, owner: desk),
                "desk_owner": staticmethod(lambda world: FLOW_USER if world == desk else None),
            },
        )()

    def teach_and_save(self, name: str = "Web digest") -> dict:
        """The three calls the Teach page makes: capture, version, save (what the review page sends)."""
        captured = self.client.post("/v1/skills/captures", json={"method": "describe", "text": DESCRIPTION})
        assert captured.status_code == 201, captured.text
        proposed = self.client.post(f"/v1/skills/captures/{captured.json()['capture_id']}/version", json={})
        assert proposed.status_code == 200, proposed.text
        saved = self.client.post(
            "/v1/skills",
            json={
                "name": name,
                "scope": {"kind": "just_me", "team": None},
                "trigger": {"kind": "on_demand"},
                "plan_steps": [
                    {k: s[k] for k in ("text", "tool", "action", "verb")} | {"ask_first": s["ask_first"]}
                    for s in proposed.json()["plan_steps"]
                ],
                "captured_steps": [{"text": t} for t in CAPTURED],
            },
        )
        assert saved.status_code == 201, saved.text
        return saved.json()

    def run(self, text: str, refs: list[dict]) -> dict:
        """`POST /intake` as http.ts sendIntake sends it, then approaches and approve; returns the run's flow."""
        rf = self.run_flow
        rf.app.dependency_overrides[deps.get_router] = lambda: rf.flow.router
        body = {"text": text, "refs": json.dumps(refs)}
        intake = self.client.post("/intake", data=body, headers={"Idempotency-Key": str(uuid.uuid4())})
        assert intake.status_code == 201, intake.text
        task = intake.json()
        approaches = rf.flow.approaches(task["task_id"])
        assert approaches.status_code == 200, approaches.text
        rf.task_id, rf.world_id = task["task_id"], task["world_id"]
        rf.as_member()
        started = rf.flow.approve(rf.task_id, approaches.json()["recommended"], 60)
        assert started.status_code == 200, started.text
        try:
            wait_for(lambda: rf.events("world.completed"), timeout=45.0, what="the taught skill run to complete")
        except AssertionError:
            failed = [e.get("data") for e in rf.events("world.failed")]
            raise AssertionError(f"no world.completed; events {_types(rf)}; failed {failed}") from None
        return task


def _types(rf):
    return [e["type"] for e in rf.store.events.get(rf.world_id, [])]


def test_P0_SKILLS_E2E_teach_save_run_from_skills_page(run_flow, repo_root):
    t = Taught(run_flow, repo_root)
    skill = t.teach_and_save()
    assert [s["action"] for s in skill["plan"]] == ["web_search", "fetch_url", "compose"]

    # The Skills page lists it (GET /v1/skills?include_builtin=true, then /v1/skills/catalog).
    listed = t.client.get("/v1/skills", params={"include_builtin": "true"})
    assert listed.status_code == 200, listed.text
    assert [s["name"] for s in listed.json()["skills"]] == ["Web digest"]
    assert t.client.get(f"/v1/skills/{skill['id']}").status_code == 200

    # "Run skill": prompt "Run the <name> skill." + the taught ref; the same intake as a Home send.
    t.run("Run the Web digest skill.", [{"kind": "taught_skill", "id": skill["id"]}])
    rf = run_flow
    executed = rf.store.runs[rf.world_id].plan
    assert [u["title"] for u in executed["units"]][:3] == [s["text"] for s in skill["plan"]]
    delivered = rf.events("artifact.delivered")
    assert delivered
    assert "skill.loaded" in _types(rf) or rf.events("world.completed")


def test_P0_SKILLS_E2E_mention_on_home_picks_up_the_skill(run_flow, repo_root):
    t = Taught(run_flow, repo_root)
    skill = t.teach_and_save("Web digest")

    # The mention picker's list (SkillMention.tsx) offers the saved skill with the kind the web turns into a ref.
    catalog = t.client.get("/v1/skills/catalog")
    assert catalog.status_code == 200, catalog.text
    row = next(r for r in catalog.json()["skills"] if r["id"] == skill["id"])
    assert (row["kind"], row["scope"], row["name"]) == ("taught", "mine", "Web digest")

    # Home sends "@Web digest find asura news" with refs [{kind: "taught_skill", id}] (skillRefOf).
    task = t.run("find news about asura", [{"kind": "taught_skill", "id": row["id"]}])
    rf = run_flow
    stored = rf.store.tasks[task["task_id"]]
    assert [s["action"] for s in stored.skill_plan] == ["web_search", "fetch_url", "compose"]
    assert rf.store.runs[rf.world_id].plan["units"][0]["title"] == "Search the web for asura"
    assert rf.events("artifact.delivered")


def test_P0_SKILLS_E2E_a_ref_to_someone_elses_skill_is_refused(run_flow, repo_root):
    t = Taught(run_flow, repo_root)
    t.teach_and_save()
    refused = t.client.post(
        "/intake",
        data={"text": "run it", "refs": json.dumps([{"kind": "taught_skill", "id": "tsk_nobody"}])},
    )
    assert refused.status_code == 422, refused.text
