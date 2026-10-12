"""FR-SKL-05, FR-SKL-06 (ADR-0037; taught_skill.rules.md TS-08, TS-09, TS-11, TS-15): the routes over the taught-skill
ledger. The caller is `Principal.user_id`; a run's version, plan and rater come from the stored run, never a body.

  POST /v1/skills/{id}/runs/{run_id}/rating   {thumb, wrong_step?, note?}   201 the rating; 200 for an identical retry
  POST /v1/skills/{id}/fixes                  {from_version, step, text, ask_first, rating?}   200 the new skill
  POST /v1/skills/{id}/state                  {change: paused|resumed|learning|trusted}        200 the skill
  GET  /v1/learn                              needs_rating = the caller's finished, unrated, recorded runs

One 404 body for every refusal to read; the events are ids, counts and enums only, in the acting person's Desk world.
No network, no model, no paid call.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from _api_lib import validate_event
from _clint1_lib import seam
from _ppl11a_lib import DEV, MEERA, ORG, PRIYA, SAM, STANDARD_PERSONS, conforms
from test_FR_SKL_04_SKILLS_2_skill_store import record
from tilo_api.skill_store import MemorySkillStore

SKILL, TEAM_SKILL = "tsk_01JB6Z0000000000000000AAA", "tsk_01JB6Z0000000000000000BBB"
T0, T1 = "2026-10-05T09:00:00.000Z", "2026-10-05T09:05:00.000Z"
PRIYA_DESK, SAM_DESK = "w_desk_priya", "w_desk_sam"
STEPS = [
    {"text": "Read it", "tool": "gmail", "action": "read_email", "verb": "read", "ask_first": False, "must_ask": False},
    {"text": "Send it", "tool": "gmail", "action": "send_email", "verb": "send", "ask_first": True, "must_ask": True},
]


class Ctx:
    def __init__(self, rig: Any, store: MemorySkillStore) -> None:
        self.rig, self.store = rig, store

    def skill(self, skill_id: str = SKILL, owner: str = PRIYA, **over: Any) -> dict[str, Any]:
        row = {**record(skill_id, owner), "plan": copy.deepcopy(STEPS), **over}
        self.store.put(row)
        return row

    def run(self, run_id: str = "r_one", by: str = PRIYA, outcome: str | None = "completed", skill_id: str = SKILL):
        teams = ("tm_launch", "tm_ops")
        self.store.start_real_run(ORG, skill_id, by=by, teams=teams, world_id="w_x", run_id=run_id, now=T0)
        if outcome:
            self.store.finish_real_run(ORG, skill_id, run_id, outcome=outcome, at=T1)

    def post(self, user: str, path: str, body: Any) -> Any:
        self.rig.as_user(user)
        return self.rig.post(path, body)

    def rate(self, user: str, run_id: str = "r_one", skill_id: str = SKILL, **body: Any) -> Any:
        return self.post(user, f"/v1/skills/{skill_id}/runs/{run_id}/rating", {"thumb": "up", **body})

    def fix(self, user: str = PRIYA, skill_id: str = SKILL, **body: Any) -> Any:
        sent = {"from_version": 1, "step": 1, "text": "Read it twice", "ask_first": False, **body}
        return self.post(user, f"/v1/skills/{skill_id}/fixes", sent)

    def state(self, user: str, change: str, skill_id: str = SKILL) -> Any:
        return self.post(user, f"/v1/skills/{skill_id}/state", {"change": change})

    def events(self, world: str = PRIYA_DESK) -> list[dict[str, Any]]:
        return list(self.rig.event_store.events.get(world, []))

    def learn(self, user: str) -> dict[str, Any]:
        self.rig.as_user(user)
        response = self.rig.get("/v1/learn")
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]


@pytest.fixture()
def ctx(people_rig):
    rig = people_rig()
    rig.add_people(STANDARD_PERSONS.values())
    store = MemorySkillStore()
    rig.app.dependency_overrides[seam(rig.deps, "get_skill_store")] = lambda: store
    return Ctx(rig, store)


# -- ratings -----------------------------------------------------------------------------------------------------


def test_FR_SKL_05_a_rating_is_the_callers_own_finished_run_and_names_its_pinned_version(ctx):
    ctx.skill()
    ctx.run()
    response = ctx.rate(PRIYA)
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["skill"], body["version"], body["run_id"], body["by"], body["thumb"]) == (
        SKILL,
        1,
        "r_one",
        PRIYA,
        "up",
    )
    assert conforms("taught_skill.schema.json#/$defs/rating", body)
    assert ctx.store.get(ORG, SKILL)["good_runs"] == 1
    (event,) = ctx.events()
    validate_event(dict(event))
    assert event["type"] == "skill.rated" and (event["actor"], event["target"], event["vis"]) == (PRIYA, PRIYA, [])
    assert event["data"] == {"skill": SKILL, "version": 1, "run_id": "r_one", "thumb": "up", "wrong_step": None}


def test_FR_SKL_05_a_note_is_kept_for_the_owner_and_never_in_the_event(ctx):
    ctx.skill()
    ctx.run()
    response = ctx.rate(PRIYA, thumb="down", wrong_step=2, note="It sent the wrong file")
    assert response.status_code == 201, response.text
    assert ctx.store.list_ratings(ORG, SKILL)[0]["note"] == "It sent the wrong file"
    assert "wrong file" not in json.dumps(ctx.events())


def test_FR_SKL_05_an_unknown_foreign_unfinished_or_not_own_run_is_the_one_404(ctx):
    ctx.skill(TEAM_SKILL, scope={"kind": "team", "team": "tm_launch"})
    ctx.skill()
    ctx.run("r_dev", by=DEV, skill_id=TEAM_SKILL)
    ctx.run("r_open", outcome=None)
    ctx.run("r_one")
    ctx.store.put({**record("tsk_draft", PRIYA, status="draft"), "plan": []})
    refusals = [
        ctx.rate(PRIYA, "r_dev", TEAM_SKILL),  # another person's run, even the owner's teammate's
        ctx.rate(PRIYA, "r_open"),  # not finished
        ctx.rate(PRIYA, "r_unknown"),
        ctx.rate(MEERA, "r_one"),  # not the owner or in a team of the skill
        ctx.rate(PRIYA, "r_one", "tsk_unknown"),
        ctx.rate(PRIYA, "r_one", "tsk_draft"),
    ]
    assert [r.status_code for r in refusals] == [404] * 6
    assert len({r.text for r in refusals}) == 1
    assert ctx.store.list_ratings(ORG, SKILL) == [] and ctx.events() == []
    ctx.rig.sign_out()
    assert ctx.rig.post(f"/v1/skills/{SKILL}/runs/r_one/rating", {"thumb": "up"}).status_code == 401


def test_FR_SKL_05_the_body_is_closed_and_a_down_may_name_only_a_step_of_the_pinned_plan(ctx):
    ctx.skill()
    ctx.run()
    for extra in ({"version": 2}, {"by": SAM}, {"id": "x"}, {"run_id": "r_one"}):
        assert ctx.rate(PRIYA, **extra).status_code == 422, extra
    assert ctx.rate(PRIYA, wrong_step=1).status_code == 422  # a thumbs up names no step
    assert ctx.rate(PRIYA, thumb="down", wrong_step=3).status_code == 422  # the plan has two steps
    assert ctx.store.list_ratings(ORG, SKILL) == []


def test_FR_SKL_05_a_failed_run_takes_a_thumbs_down_and_never_a_thumbs_up(ctx):
    ctx.skill()
    ctx.run(outcome="failed")
    assert ctx.rate(PRIYA, thumb="up").status_code == 422
    assert ctx.rate(PRIYA, thumb="down", wrong_step=1).status_code == 201
    assert ctx.store.get(ORG, SKILL)["good_runs"] == 0


def test_FR_SKL_05_a_run_takes_one_rating_and_an_identical_retry_only_repeats_its_event(ctx):
    ctx.skill()
    ctx.run()
    first = ctx.rate(PRIYA)
    assert ctx.rate(PRIYA, thumb="down", wrong_step=1).status_code == 409
    retry = ctx.rate(PRIYA)
    assert (retry.status_code, retry.json()["id"]) == (200, first.json()["id"])
    assert len(ctx.store.list_ratings(ORG, SKILL)) == 1 and len(ctx.events()) == 1
    assert ctx.store.get(ORG, SKILL)["good_runs"] == 1


def test_FR_SKL_05_a_failed_event_write_is_503_and_the_retry_writes_the_event(ctx):
    class Down:
        def append(self, *_: Any) -> None:
            raise RuntimeError("down")

    ctx.skill()
    ctx.run()
    ctx.rig.app.dependency_overrides[ctx.rig.deps.get_event_writer] = lambda: Down()
    failed = ctx.rate(PRIYA)
    assert failed.status_code == 503 and "down" not in failed.text
    ctx.rig.app.dependency_overrides[ctx.rig.deps.get_event_writer] = lambda: ctx.rig.events
    assert ctx.rate(PRIYA).status_code == 200 and len(ctx.events()) == 1


# -- fixes -------------------------------------------------------------------------------------------------------


def test_FR_SKL_05_the_owner_fixes_the_current_version_and_a_run_keeps_the_version_it_started_with(ctx):
    ctx.skill()
    ctx.run()
    response = ctx.fix()
    assert response.status_code == 200, response.text
    after = response.json()
    assert (after["version"], after["plan"][0]["text"], after["plan"][1]) == (2, "Read it twice", STEPS[1])
    assert ctx.store.get_real_run(ORG, SKILL, "r_one")["version"] == 1
    assert ctx.store.list_fixes(ORG, SKILL)[0]["rating"] is None
    (event,) = ctx.events()
    validate_event(dict(event))
    assert event["type"] == "skill.fixed" and "twice" not in json.dumps(event)
    assert event["data"] == {"skill": SKILL, "from_version": 1, "to_version": 2, "step": 1}
    again = ctx.fix()  # the same fix again: a retry, not a second fix
    assert (again.status_code, again.json()["version"]) == (200, 2) and len(ctx.events()) == 1


def test_FR_SKL_05_a_fix_by_anyone_but_the_owner_or_of_a_stale_or_unsafe_step_writes_nothing(ctx):
    ctx.skill(scope={"kind": "team", "team": "tm_launch"})
    assert [ctx.fix(who).status_code for who in (DEV, SAM, MEERA)] == [404, 404, 404]  # a teammate reads, never fixes
    assert ctx.fix(PRIYA, from_version=3).status_code == 409
    assert ctx.fix(PRIYA, step=2, ask_first=False).status_code == 422  # must_ask keeps ask_first
    assert ctx.fix(PRIYA, step=3).status_code == 422
    assert ctx.fix(PRIYA, rating="01JB6Z00000000000000RATXXX").status_code == 422
    assert ctx.store.get(ORG, SKILL)["version"] == 1 and ctx.store.list_fixes(ORG, SKILL) == []
    assert ctx.events() == []


# -- pause, resume, trust ------------------------------------------------------------------------------------------


def test_FR_SKL_06_only_the_owner_pauses_and_resumes_and_a_paused_skill_never_starts(ctx):
    ctx.skill(status="trusted")
    assert ctx.state(SAM, "paused").status_code == 404
    paused = ctx.state(PRIYA, "paused")
    assert (paused.status_code, paused.json()["paused"], paused.json()["status"]) == (200, True, "trusted")
    from tilo_api.skill_ledger import SkillRefused  # noqa: PLC0415

    with pytest.raises(SkillRefused):
        ctx.run("r_new", outcome=None)
    assert ctx.state(PRIYA, "paused").status_code == 200  # no change, no second event
    assert ctx.state(PRIYA, "resumed").json()["paused"] is False
    assert [e["data"]["change"] for e in ctx.events()] == ["paused", "resumed"]
    for event in ctx.events():
        validate_event(dict(event))
        assert event["type"] == "skill.state_changed" and event["data"]["threshold"] is None


def test_FR_SKL_06_trusted_needs_the_configured_number_of_verified_up_ratings(ctx):
    ctx.skill()
    for n in range(5):
        ctx.run(f"r_{n}")
    for n in range(4):
        assert ctx.rate(PRIYA, f"r_{n}").status_code == 201
    refused = ctx.state(PRIYA, "trusted")
    assert (refused.status_code, refused.json()["detail"]) == (409, "not_enough_good_runs")
    assert ctx.rate(PRIYA, "r_4").status_code == 201
    done = ctx.state(PRIYA, "trusted")
    assert (done.status_code, done.json()["status"], done.json()["good_runs"]) == (200, "trusted", 5)
    event = ctx.events()[-1]
    assert event["data"] == {"skill": SKILL, "version": 1, "change": "trusted", "good_runs": 5, "threshold": 5}
    assert ctx.state(PRIYA, "learning").json()["status"] == "learning"  # Keep learning is always allowed
    assert ctx.state(PRIYA, "sleeping").status_code == 422


# -- GET /v1/learn: recorded history only ---------------------------------------------------------------------


def test_FR_SKL_07_learn_lists_only_the_callers_recorded_finished_unrated_runs(ctx):
    ctx.skill(TEAM_SKILL, owner=PRIYA, scope={"kind": "team", "team": "tm_launch"})
    ctx.skill()
    empty = ctx.learn(PRIYA)
    assert (empty["needs_rating"], empty["helpers"]) == ([], None)  # no recorded run: nothing, never a zero bar
    ctx.run("r_one")
    ctx.run("r_open", outcome=None)
    ctx.run("r_dev", by=DEV, skill_id=TEAM_SKILL)
    ctx.run("r_two")
    ctx.rate(PRIYA, "r_two")
    rows = ctx.learn(PRIYA)["needs_rating"]
    assert rows == [
        {
            "skill": SKILL,
            "name": "Weekly report",
            "run_id": "r_one",
            "version": 1,
            "outcome": "completed",
            "finished_at": T1,
        }
    ]
    assert ctx.learn(DEV)["needs_rating"][0]["run_id"] == "r_dev"
    assert ctx.learn(SAM)["needs_rating"] == []
