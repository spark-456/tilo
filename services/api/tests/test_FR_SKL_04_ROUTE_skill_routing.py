"""SKILL-ROUTE (FR-SKL-04, FR-AGT-03, EFF-04): the skills a person may use, and which one fits a task.

Pinned interface:
  * `GET /v1/skills/catalog` -> {skills: [{id, kind library|taught, scope library|mine|team, name, purpose, inputs,
    tools, version}]}: the library skills, the caller's own saved taught skills and the shared ones of their current
    teams (never a draft, never another person's). No model call.
  * The matcher embeds the task with the `embed` role against the entry descriptions (cached) and answers
    {id, kind, scope, name, version, score, source matched|picked|tagged} only when the cosine score reaches
    `config/skills.yaml` `route.min_score`. Within `route.tie_margin` of the second, one `assistant` call picks; if it
    fails the order is score then id. A tagged skill the caller may use always wins and no model is called.
  * `GET /tasks/{id}/approaches` also answers `skill` (the match or null) and keeps it on the task; the run pins a
    matched LIBRARY skill on its working units, and `skill.loaded` names the skill and version in its summary.
  * Quick: an answer carries `skill` when one fits (absent otherwise; a rules-decided offer costs nothing, so none);
    the answer prompt gets the
    caller's catalog as fenced data. No paid call anywhere.
"""

from __future__ import annotations

import json

import pytest
from _clint1_lib import RoleScriptedProvider, build_router
from _skills4_lib import PRIYA, SAM
from tilo_providers.interfaces import EmbedResponse, GenerateResponse

DIMS = 256


def vec(**parts: float) -> list[float]:
    """A vector with the named components (`i3=0.5` -> index 3), the rest zero."""
    out = [0.0] * DIMS
    for name, value in parts.items():
        out[int(name[1:])] = value
    return out


class Embedder(RoleScriptedProvider):
    """Scripted embeddings by keyword (first keyword found in the text wins) and a scripted tie-break answer."""

    def __init__(self, topics: dict[str, list[float]], pick: str | Exception = "a") -> None:
        super().__init__({}, {})
        self.topics, self.pick, self.embedded, self.picked = topics, pick, [], 0

    def embed(self, request):
        self.embedded.append((request.task, list(request.texts)))
        out = []
        for text in request.texts:
            found = next((v for k, v in self.topics.items() if k in text.lower()), None)
            out.append(found if found is not None else vec(i254=1.0) if request.task == "query" else vec(i255=1.0))
        return EmbedResponse(vectors=out, profile_id=self.profile_id)

    def generate(self, request):
        self.picked += 1
        if isinstance(self.pick, Exception):
            raise self.pick
        return GenerateResponse(text=json.dumps({"pick": self.pick}), profile_id=self.profile_id, usage={})


TOPICS = {"competitor scan": vec(i1=1.0, i5=0.3), "one page plan": vec(i1=1.0, i6=0.3)}


def context(repo_root, provider, taught=(), user=PRIYA):
    from tilo_api.skills_route import SkillContext  # noqa: PLC0415
    from tilo_harness.skills import SkillRegistry  # noqa: PLC0415

    return SkillContext(
        user, SkillRegistry(repo_root / "skills"), lambda: list(taught), build_router(repo_root, provider)
    )


def taught(skill_id, owner, name, scope=("just_me", None), status="learning"):
    step = {
        "text": "Read the mail",
        "tool": "gmail",
        "action": "read_email",
        "verb": "read",
        "ask_first": False,
        "must_ask": False,
    }
    return {
        "id": skill_id, "owner": owner, "name": name, "status": status, "version": 2, "plan": [step],
        "scope": {"kind": scope[0], "team": scope[1]}, "inputs": [],
    }  # fmt: skip


@pytest.fixture(autouse=True)
def fresh_cache():
    from tilo_api import skills_route  # noqa: PLC0415

    skills_route._cache.clear()
    yield
    skills_route._cache.clear()


def test_FR_SKL_04_ROUTE_a_task_above_the_threshold_matches_one_library_skill_and_below_it_none(repo_root):
    topics = {"competitor scan": vec(i1=1.0), "zq-rivals": vec(i1=0.9, i2=0.1), "zq-weather": vec(i7=1.0)}
    ctx = context(repo_root, Embedder(topics))
    found = ctx.match("Look at what our zq-rivals are doing")
    assert found["id"] == "competitor-scan" and found["kind"] == "library" and found["source"] == "matched"
    assert 0.75 <= found["score"] <= 1.0 and set(found) == {"id", "kind", "scope", "name", "version", "score", "source"}
    assert context(repo_root, Embedder(topics)).match("What is the zq-weather like?") is None  # a different topic


def test_FR_SKL_04_ROUTE_the_threshold_and_margin_are_config_and_a_missing_config_falls_back(repo_root, tmp_path):
    from tilo_api.skills_route import RouteConfig, load_route_config  # noqa: PLC0415

    assert load_route_config(repo_root / "config") == RouteConfig(0.75, 0.02, 256)
    assert load_route_config(tmp_path) == RouteConfig(0.78, 0.02, 256)


def test_FR_SKL_04_ROUTE_a_near_tie_asks_the_assistant_once_and_a_clear_win_never_does(repo_root):
    provider = Embedder({**TOPICS, "zq-plan": vec(i1=1.0, i5=0.15, i6=0.14)}, pick="b")
    found = context(repo_root, provider).match("zq-plan")
    assert provider.picked == 1 and found["source"] == "picked" and found["id"] == "one-page-plan"  # b = the second
    clear = Embedder({**TOPICS, "zq-scan": vec(i1=1.0, i5=0.3)}, pick="b")
    assert context(repo_root, clear).match("zq-scan")["id"] == "competitor-scan" and clear.picked == 0


def test_FR_SKL_04_ROUTE_a_failed_or_empty_tie_break_keeps_the_deterministic_order_or_says_none(repo_root):
    topics = {**TOPICS, "zq-plan": vec(i1=1.0, i5=0.15, i6=0.14)}
    failed = context(repo_root, Embedder(topics, pick=RuntimeError("down"))).match("zq-plan")
    assert failed["id"] == "competitor-scan" and failed["source"] == "matched"  # the higher score
    assert context(repo_root, Embedder(topics, pick="none")).match("zq-plan") is None
    equal = {"competitor scan": vec(i1=1.0), "one page plan": vec(i1=1.0), "zq-tied": vec(i1=1.0)}
    assert context(repo_root, Embedder(equal, pick=RuntimeError("down"))).match("zq-tied")["id"] == "competitor-scan"


def test_FR_SKL_04_ROUTE_an_explicit_tag_always_wins_and_calls_no_model(repo_root):
    provider = Embedder({"competitor scan": vec(i1=1.0), "one page plan": vec(i2=1.0), "zq-rivals": vec(i1=1.0)})
    ctx = context(repo_root, provider)
    found = ctx.match("Look at our zq-rivals", tagged="one-page-plan")
    assert found["id"] == "one-page-plan" and found["source"] == "tagged" and found["score"] == 1.0
    assert provider.embedded == [] and provider.picked == 0
    assert (
        ctx.match("Look at our zq-rivals", tagged="tsk_not_yours") is None
    )  # a tag the caller may not use matches nothing


def test_FR_SKL_04_ROUTE_another_persons_or_an_unshared_taught_skill_is_never_in_the_catalog_or_matched(repo_root):
    from tilo_api.skills_routes import _readable  # noqa: PLC0415,F401

    sams = taught("tsk_sams", SAM, "Sam secret zq-digest")
    mine = taught("tsk_mine", PRIYA, "Priya zq-digest")
    provider = Embedder({"zq-digest": vec(i9=1.0), "look at the zq-digest": vec(i9=1.0)})
    ctx = context(repo_root, provider, taught=[mine])  # the store read already narrowed to Priya's view
    names = [e["name"] for e in ctx.catalog()]
    assert "Priya zq-digest" in names and not any("Sam" in n for n in names)
    assert ctx.match("Look at the zq-digest")["id"] == "tsk_mine"
    assert "secret" not in json.dumps(provider.embedded) and sams["id"] not in json.dumps(ctx.catalog())


def test_FR_SKL_04_ROUTE_the_catalog_route_lists_library_own_and_team_skills_never_drafts_or_strangers(skills4):
    def save(user, name, scope):
        skills4.rig.as_user(user)
        body = {
            "name": name, "scope": scope, "trigger": {"kind": "on_demand"},
            "plan_steps": [{"text": "Read the mail", "tool": "gmail", "action": "read_email", "verb": "read"}],
            "inputs": [{"name": "topic", "label": "Topic", "kind": "text", "required": False}],
        }  # fmt: skip
        response = skills4.rig.post("/v1/skills", body)
        assert response.status_code == 201, response.text

    save(PRIYA, "Priya private", {"kind": "just_me", "team": None})
    save(PRIYA, "Launch shared", {"kind": "team", "team": "tm_launch"})
    save(SAM, "Sam private", {"kind": "just_me", "team": None})
    draft = skills4.made()  # an unfinished capture is not a skill
    calls = len(skills4.model.calls)
    skills4.rig.as_user("u_dev")  # in tm_launch
    names = {e["name"]: e for e in skills4.rig.get("/v1/skills/catalog").json()["skills"]}
    assert "Launch shared" in names and "Priya private" not in names and "Sam private" not in names
    assert names["Launch shared"]["scope"] == "team" and names["Launch shared"]["tools"] == ["gmail"]
    assert names["Launch shared"]["inputs"][0]["name"] == "topic" and names["Launch shared"]["version"] == 1
    skills4.rig.as_user(PRIYA)
    mine = {e["name"]: e for e in skills4.rig.get("/v1/skills/catalog").json()["skills"]}
    assert mine["Priya private"]["scope"] == "mine" and "Sam private" not in mine and draft not in json.dumps(mine)
    library = [e for e in mine.values() if e["kind"] == "library"]
    assert len(library) >= 10 and all(e["scope"] == "library" and e["purpose"] and "inputs" in e for e in library)
    assert all(e["id"] != "agent-self-report" for e in library)  # Tilo's own machinery is not offered
    assert len(skills4.model.calls) == calls  # no model call for the catalog


def test_FR_SKL_04_ROUTE_catalog_is_a_path_not_a_skill_id_and_a_signed_out_caller_gets_nothing(skills4):
    skills4.rig.as_user(PRIYA)
    assert skills4.rig.get("/v1/skills/tsk_nothing").status_code == 404
    assert skills4.rig.get("/v1/skills/catalog").status_code == 200


def test_FR_SKL_04_ROUTE_the_approaches_answer_names_the_matched_skill_and_the_run_pins_and_names_it(run_flow):
    goal = run_flow.flow.provider.brief["goal"].lower()
    embedder = Embedder({"exec_summary": vec(i1=1.0), goal: vec(i1=1.0)})
    run_flow.flow.provider.embed = embedder.embed
    requested, _card = run_flow.run_to_gate()
    answer = run_flow.flow.approaches(run_flow.task_id).json()
    assert answer["skill"]["id"] == "exec_summary" and answer["skill"]["kind"] == "library"
    assert run_flow.store.tasks[run_flow.task_id].skill["id"] == "exec_summary"
    loaded = [e for e in run_flow.events("skill.loaded")]
    units = {e["data"]["skill"] for e in loaded}
    assert "exec_summary" in units and len([e for e in loaded if e["data"]["skill"] == "exec_summary"]) >= 3
    named = next(e for e in loaded if e["data"]["skill"] == "exec_summary")
    assert "exec_summary" in named["summary"] and named["data"]["version"] in named["summary"]
    assert requested["seq"] > loaded[0]["seq"]


def test_R_RUN_a_skill_tagged_start_leaves_scheduled_and_finishes(run_flow):
    from _clint2_lib import wait_for  # noqa: PLC0415
    from test_FR_PA_11_SKILL_TAG_intake_refs import post  # noqa: PLC0415

    response = post(run_flow.flow, [{"kind": "skill", "id": "web_research"}])
    assert response.status_code == 201, response.text
    intake = response.json()
    run_flow.task_id, run_flow.world_id = intake["task_id"], intake["world_id"]
    run_flow.as_member()
    approaches = run_flow.flow.approaches(run_flow.task_id).json()

    started = run_flow.flow.approve(run_flow.task_id, approaches["recommended"], 80)
    assert started.status_code == 200, started.text
    wait_for(lambda: run_flow.events("world.started"), what="skill-tagged world.started")
    cards = wait_for(lambda: run_flow.cards().json(), what="skill-tagged run gate")
    gate = next(card for card in cards if card["kind"] == "gate")
    assert run_flow.answer(gate["id"], "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="skill-tagged world.completed")


def test_FR_SKL_04_ROUTE_no_match_leaves_the_approaches_and_the_plan_as_they_were(run_flow):
    run_flow.flow.provider.embed = Embedder({}).embed  # every text embeds to the same place: no skill clears the bar
    run_flow.start()
    assert run_flow.flow.approaches(run_flow.task_id).json()["skill"] is None
    assert run_flow.store.tasks[run_flow.task_id].skill is None


def test_FR_SKL_04_ROUTE_quick_answers_carry_the_skill_and_the_catalog_as_fenced_data(quick_rig, monkeypatch):
    import _costfast1_lib  # noqa: PLC0415

    embedder = Embedder({"competitor scan": vec(i1=1.0), "zq-rivals": vec(i1=1.0)})
    monkeypatch.setattr(_costfast1_lib.QuickProvider, "embed", lambda self, request: embedder.embed(request))
    answer = quick_rig.ask("What is the capital of France? zq-rivals")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (
        body["outcome"] == "answered"
        and body["skill"]["id"] == "competitor-scan"
        and body["skill"]["kind"] == "library"
    )
    prompt = quick_rig.provider_requests[-1].prompt
    assert "<<<SKILLS" in prompt and "competitor scan:" in prompt and "SKILLS>>>" in prompt
    assert "skill" not in quick_rig.ask("What is the capital of France?").json()  # nothing fits: the key is absent
    quick_rig.reset()
    offer = quick_rig.ask("Please send an email to my whole team zq-rivals").json()
    assert offer["outcome"] == "switch_to_thinking" and "skill" not in offer  # a rules-decided offer costs nothing
    assert quick_rig.provider_requests == []


def test_FR_SKL_04_ROUTE_pinning_adds_a_matched_library_skill_to_working_units_only():
    from tilo_api.skills_route import pin_matched_skill  # noqa: PLC0415
    from tilo_planning.compiler import DELIVER  # noqa: PLC0415

    def unit(unit_id, role, kind="work", skills=()):
        return {"id": unit_id, "role": role, "unit_type": kind, "skills": list(skills)}

    plan = {
        "units": [
            unit("U1", "specialist"),
            unit("U2", "writer", skills=["x"]),
            unit("U3", "verifier"),
            unit("U4", "writer", DELIVER),
        ]
    }
    match = {"id": "competitor-scan", "kind": "library"}
    out = pin_matched_skill(plan, match, {"competitor-scan", "x"})
    assert [u["skills"] for u in out["units"]] == [["competitor-scan"], ["x", "competitor-scan"], [], []]
    assert pin_matched_skill(out, match, {"competitor-scan"})["units"][0]["skills"] == ["competitor-scan"]  # once
    for other in (None, {"id": "tsk_a", "kind": "taught"}, {"id": "unknown", "kind": "library"}):
        fresh = {"units": [unit("U1", "specialist")]}
        assert pin_matched_skill(fresh, other, {"competitor-scan"})["units"][0]["skills"] == []
    full = {"units": [unit("U1", "specialist", skills=[f"s{i}" for i in range(10)])]}
    assert len(pin_matched_skill(full, match, {"competitor-scan"})["units"][0]["skills"]) == 10
