"""Supervisor 03:00 ruling: strict caller-owned context, no teammate identities."""

import json

import pytest
from _api_lib import make_world
from _ppl11a_lib import CONTRACTS, DEV, ORG, OWNER, PRIYA, own_item
from _ppl11c_lib import meeting_rig
from tilo_api import deps
from tilo_api.skill_store import MemorySkillStore


def seed_context(people_rig, store):
    rig = meeting_rig(people_rig)
    skills = MemorySkillStore()
    rig.app.dependency_overrides[deps.get_store] = lambda: store
    rig.app.dependency_overrides[deps.get_skill_store] = lambda: skills
    skill = json.loads((CONTRACTS / "fixtures/taught_skill/valid/trusted_paused_event_trigger_upload.json").read_text())
    skills.put(skill)
    skill.update(id="tsk_context_own", owner=OWNER, name="Own recorded skill")
    skills.put(skill)
    store.worlds["w_context_own"] = make_world(owner=OWNER)
    store.worlds["w_context_other"] = make_world(owner=PRIYA)
    private = json.loads((CONTRACTS / "fixtures/pinboard_item/valid/personal_note.json").read_text())
    private.update(id="pb_context_private", set_up_by=OWNER, scope={"kind": "personal", "user": OWNER})
    private["created_by"]["ref"] = OWNER
    rig.add("pins", private)
    team = json.loads((CONTRACTS / "fixtures/pinboard_item/valid/team_entry_by_person.json").read_text())
    rig.add("pins", team)
    world_pin = dict(
        team, id="pb_context_world", owner=None, source={"kind": "request", "ref": "w_context_own", "evidence": []}
    )
    rig.add("pins", world_pin)
    rig.add("work_items", own_item("wi_context_own", OWNER))
    rig.add("work_items", own_item("wi_context_other", PRIYA))
    return rig


def test_CONTEXT_P2_second_person_never_sees_first_person_data_or_teammate_visible_pin(people_rig, store):
    rig = seed_context(people_rig, store)
    for actor in (OWNER, DEV):
        rig.as_user(actor)
        before = rig.snapshot()
        response = rig.get("/v1/context", params={"user": PRIYA, "org_id": "org_else"})
        assert response.status_code == 200
        body = response.json()
        assert body["workspace"]["org_id"] == ORG
        assert set(body["workspace"]) == {"org_id", "role", "connectors", "skills"}
        assert "pb_launch_date" not in json.dumps(body)
        assert "wi_context_other" not in json.dumps(body)
        assert "w_context_other" not in json.dumps(body)
        assert "Log supplier invoices" not in json.dumps(body)
        assert response.headers["cache-control"] == "no-store"
        if actor == OWNER:
            assert "pb_context_private" in json.dumps(body)
            assert "wi_context_own" in json.dumps(body)
            assert "mt_q4_plan" in json.dumps(body)
            assert "pb_context_world" in json.dumps(body)
            assert "Own recorded skill" in json.dumps(body)
        else:
            assert "pb_context_private" not in json.dumps(body)
            assert "wi_context_own" not in json.dumps(body)
            assert "mt_q4_plan" not in json.dumps(body)
            assert "pb_context_world" not in json.dumps(body)
            assert "Own recorded skill" not in json.dumps(body)
        assert rig.snapshot() == before
        assert "attendees" not in json.dumps(body)
        assert "email" not in body["workspace"] and "people" not in body["workspace"]
        assert not any(kind == "person" and method == "list" for kind, method, _ in rig.store_calls)


def test_CONTEXT_P2_created_items_preserve_existing_status_only_oracle(people_rig, store):
    rig = seed_context(people_rig, store)
    item = own_item("wi_created_for_other", PRIYA)
    item["created_by"]["ref"] = OWNER
    item["assigned_by"] = {"by": OWNER, "at": item["created_at"]}
    rig.add("work_items", item)
    rig.as_user(OWNER)
    body = rig.get("/v1/context").json()
    got = next(row for row in body["work_items"]["items"] if row["id"] == item["id"])
    assert "title" not in got and got["status"] == "open"


def test_CONTEXT_P2_shared_world_uses_existing_verified_session_scope(people_rig, store):
    rig = seed_context(people_rig, store)
    rig.as_user(DEV, role="viewer", world_id="w_context_other")
    body = rig.get("/v1/context").json()
    assert [row["world_id"] for row in body["worlds"]["worlds"]] == ["w_context_other"]
    assert body["pins"]["items"] == []


def test_CONTEXT_P2_connection_views_receive_only_the_caller(people_rig, store):
    rig = seed_context(people_rig, store)
    called = []

    class Views:
        def view(self, owner, connector):
            called.append(owner)
            return "connected", [], None

    rig.app.dependency_overrides[deps.get_connection_views] = lambda: Views()
    body = rig.get("/v1/context").json()
    assert called and set(called) == {OWNER}
    assert all(set(row) == {"id", "state", "state_known"} for row in body["workspace"]["connectors"])


@pytest.mark.parametrize("failure", ["missing", "store"])
def test_CONTEXT_P2_missing_person_or_failed_source_returns_no_partial_context(people_rig, store, failure):
    rig = seed_context(people_rig, store)
    if failure == "missing":
        rig.as_user("u_missing")
    else:

        class FailedSkills(MemorySkillStore):
            def list_for_owner(self, org, owner):
                raise RuntimeError("private source failure")

        rig.app.dependency_overrides[deps.get_skill_store] = lambda: FailedSkills()
    response = rig.get("/v1/context")
    assert response.status_code == (404 if failure == "missing" else 503)
    assert "worlds" not in response.json() and "private" not in response.text
