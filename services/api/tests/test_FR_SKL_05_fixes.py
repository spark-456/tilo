import copy

import pytest
from _ppl11a_lib import ORG, PRIYA, SAM, STANDARD_PERSONS
from test_FR_SKL_04_SKILLS_2_skill_store import record
from tilo_api.skill_store import MemorySkillStore


@pytest.fixture
def fixes(people_rig):
    rig = people_rig()
    rig.add_people(STANDARD_PERSONS.values())
    store = MemorySkillStore()
    rig.app.dependency_overrides[rig.deps.get_skill_store] = lambda: store
    store.put(record("tsk_fix"))
    rig.as_user(PRIYA)
    return rig, store


def body(**over):
    return {"from_version": 1, "step": 1, "text": "Read the invoice", "ask_first": True, **over}


def test_FR_SKL_05_fix_persists_version_log_and_private_event(fixes):
    rig, store = fixes
    before = store.get(ORG, "tsk_fix")
    response = rig.post("/v1/skills/tsk_fix/fixes", body())
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["version"] == 2 and after["plan"][0]["text"] == "Read the invoice"
    assert before["version"] == 1 and before["plan"][0]["text"] == "Read it"
    assert store.get(ORG, "tsk_fix") == after
    log = store.list_fixes(ORG, "tsk_fix")
    assert len(log) == 1 and log[0]["rating"] is None and log[0]["by"] == PRIYA
    event = rig.events.calls[-1].part
    assert event["type"] == "skill.fixed" and event["vis"] == []
    assert event["data"] == {"skill": "tsk_fix", "from_version": 1, "to_version": 2, "step": 1}
    assert "Read the invoice" not in str(event)
    assert rig.post("/v1/skills/tsk_fix/fixes", body()).status_code == 409
    assert len(store.list_fixes(ORG, "tsk_fix")) == 1


@pytest.mark.parametrize("change", [{"step": 2}, {"ask_first": False}, {"tool": "gmail"}])
def test_FR_SKL_05_fix_preserves_must_ask_and_action(fixes, change):
    rig, store = fixes
    before = store.get(ORG, "tsk_fix")
    before["plan"][0]["must_ask"] = before["plan"][0]["ask_first"] = True
    store.put(before)
    assert rig.post("/v1/skills/tsk_fix/fixes", body(**change)).status_code == 422
    assert store.get(ORG, "tsk_fix") == before
    assert store.list_fixes(ORG, "tsk_fix") == []


def test_FR_SKL_05_fix_owner_only_same_absent_response(fixes):
    rig, store = fixes
    rig.as_user(SAM)
    other = rig.post("/v1/skills/tsk_fix/fixes", body())
    missing = rig.post("/v1/skills/tsk_unknown/fixes", body())
    assert other.status_code == missing.status_code == 404 and other.json() == missing.json()
    assert store.get(ORG, "tsk_fix")["version"] == 1


def test_FR_SKL_05_fix_event_failure_undoes_only_its_own_change(fixes, monkeypatch):
    rig, store = fixes
    before = copy.deepcopy(store.get(ORG, "tsk_fix"))
    monkeypatch.setattr(rig.events, "append", lambda *_: (_ for _ in ()).throw(RuntimeError("down")))
    assert rig.post("/v1/skills/tsk_fix/fixes", body()).status_code == 503
    assert store.get(ORG, "tsk_fix") == before and store.list_fixes(ORG, "tsk_fix") == []
