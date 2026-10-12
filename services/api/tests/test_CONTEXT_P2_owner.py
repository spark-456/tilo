"""CONTEXT-P2: current team pins, personal isolation and existing oracle views."""

import copy
import json

import pytest
from _api_lib import make_world
from _ppl11a_lib import CONTRACTS, DEV, ORG, OWNER, PRIYA, SAM, own_item
from _ppl11c_lib import confirmed_item, meeting_rig
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


def test_CONTEXT_P2_second_person_never_sees_first_person_personal_data(people_rig, store):
    rig = seed_context(people_rig, store)
    for actor in (OWNER, DEV):
        rig.as_user(actor)
        before = rig.snapshot()
        response = rig.get("/v1/context", params={"user": PRIYA, "org_id": "org_else"})
        assert response.status_code == 200
        body = response.json()
        assert body["workspace"]["org_id"] == ORG
        assert set(body["workspace"]) == {"org_id", "role", "connectors", "skills"}
        assert "pb_launch_date" in json.dumps(body)
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
            assert "pb_context_world" in json.dumps(body)
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
    assert "pb_context_private" not in json.dumps(body)
    assert "pb_launch_date" in json.dumps(body)


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


def test_CONTEXT_P2_demo_reads_no_durable_sources(people_rig, store):
    rig = seed_context(people_rig, store)
    principal = deps.Principal(user_id=OWNER, role="owner", world_id=None, channel="web", demo_session=True)
    rig.app.dependency_overrides[deps.get_current_principal] = lambda: principal

    def forbidden():
        pytest.fail("demo context resolved a durable source")

    for source in (deps.get_skill_store, deps.get_connector_registry, deps.get_connection_views):
        rig.app.dependency_overrides[source] = forbidden
    before = len(rig.store_calls)
    response = rig.get("/v1/context")
    assert response.status_code == 200
    body = response.json()
    assert body["worlds"] == {"worlds": [], "truncated": False}
    assert all(body[key] == {"items": [], "truncated": False} for key in ("pins", "meetings", "work_items"))
    assert body["workspace"]["skills"] == [] and body["workspace"]["connectors"] == []
    assert len(rig.store_calls) == before


def test_CONTEXT_P2_world_reads_never_settle_and_cursor_is_not_exposed(people_rig, store):
    rig = seed_context(people_rig, store)
    called = []

    def load_owner(actor, *, settle=True):
        called.append((actor, settle))
        assert settle is False

    store.load_owner = load_owner
    response = rig.get("/v1/context")
    assert response.status_code == 200
    assert called == [(OWNER, False)]
    assert set(response.json()["worlds"]) == {"worlds", "truncated"}


def test_CONTEXT_P2_flags_skills_cap_and_malformed_record_isolated(people_rig, store):
    rig = seed_context(people_rig, store)
    item_store = rig.stores.work_items._inner
    item_store._rows[(ORG, "wi_context_own")][1]["flagged"] = True
    item_store._rows[(ORG, "wi_malformed")] = (
        1,
        {"id": "wi_malformed", "owner": OWNER, "org_id": ORG, "created_by": 4},
    )
    pin_store = rig.stores.pins._inner
    pin_store._rows[(ORG, "pb_context_private")][1]["flagged"] = True
    skills = MemorySkillStore()
    for i in range(205):
        skills.put(
            {
                "id": f"tsk_cap_{i}",
                "org_id": ORG,
                "owner": OWNER,
                "name": "Recorded",
                "status": "trusted",
                "paused": False,
            }
        )
    rig.app.dependency_overrides[deps.get_skill_store] = lambda: skills
    response = rig.get("/v1/context")
    assert response.status_code == 200
    body = response.json()
    assert next(row for row in body["work_items"]["items"] if row["id"] == "wi_context_own")["flagged"] is True
    assert next(row for row in body["pins"]["items"] if row["id"] == "pb_context_private")["flagged"] is True
    assert "wi_malformed" not in response.text
    assert len(body["workspace"]["skills"]) == 200


def test_CONTEXT_P2_team_pin_membership_revocation_and_personal_isolation(people_rig, store):
    rig = seed_context(people_rig, store)
    private = json.loads((CONTRACTS / "fixtures/pinboard_item/valid/personal_note.json").read_text())
    private.update(id="pb_teammate_private", set_up_by=PRIYA, scope={"kind": "personal", "user": PRIYA})
    private["created_by"]["ref"] = PRIYA
    rig.add("pins", private)
    for actor, visible in ((DEV, True), (SAM, False)):
        rig.as_user(actor)
        response = rig.get("/v1/context")
        assert response.status_code == 200
        body = response.json()
        assert ("pb_launch_date" in json.dumps(body)) is visible
        assert "pb_teammate_private" not in json.dumps(body)
        assert "wi_context_other" not in json.dumps(body)  # never bypass the current owner/assigner oracle
    person = rig.stores.persons.get(ORG, DEV)
    revoked = copy.deepcopy(person.record)
    revoked["memberships"] = []
    rig.stores.persons.replace(revoked, expected_version=person.version)
    rig.as_user(DEV)
    assert "pb_launch_date" not in rig.get("/v1/context").text


def test_CONTEXT_P2_untrusted_team_assignment_cannot_grant_visibility(people_rig, store):
    rig = seed_context(people_rig, store)
    person = rig.stores.persons.get(ORG, SAM)
    invalid = copy.deepcopy(person.record)
    invalid["memberships"] = [{"team": "tm_launch", "assigned_by": {"by": PRIYA, "at": "2026-10-01T10:00:00.000Z"}}]
    rig.stores.persons.replace(invalid, expected_version=person.version)
    rig.as_user(SAM)
    response = rig.get("/v1/context")
    assert response.status_code == 200
    assert "pb_launch_date" not in response.text


def test_CONTEXT_P2_candidates_use_indexed_bounded_reads(people_rig, store):
    rig = seed_context(people_rig, store)
    calls = []
    for name in ("pins", "work_items", "meetings"):
        wrapped = getattr(rig.stores, name)
        original = wrapped._inner.list_bounded

        def bounded(org, field, value, *, limit, original=original, name=name):
            calls.append((name, field, value, limit))
            assert field is not None and limit <= 201
            return original(org, field, value, limit=limit)

        wrapped.list_bounded = bounded

        def forbidden(*args, **kwargs):
            pytest.fail("context queried an unbounded candidate store")

        wrapped.list = forbidden
    response = rig.get("/v1/context")
    assert response.status_code == 200
    assert calls
    assert ("work_items", "assigned_by.by", OWNER, 201) in calls


def test_CONTEXT_P2_personal_scope_wins_over_setup_and_world_source(people_rig, store):
    rig = seed_context(people_rig, store)
    private = json.loads((CONTRACTS / "fixtures/pinboard_item/valid/personal_note.json").read_text())
    private.update(
        id="pb_private_for_other",
        set_up_by=OWNER,
        scope={"kind": "personal", "user": PRIYA},
        source={"kind": "request", "ref": "w_context_own", "evidence": []},
    )
    private["created_by"]["ref"] = OWNER
    rig.add("pins", private)
    response = rig.get("/v1/context")
    assert response.status_code == 200
    assert "pb_private_for_other" not in response.text


def test_CONTEXT_P2_record_limit_reports_truncation(people_rig, store):
    rig = seed_context(people_rig, store)
    for i in range(202):
        rig.add("work_items", own_item(f"wi_cap_{i}", OWNER))
    response = rig.get("/v1/context")
    assert response.status_code == 200
    assert len(response.json()["work_items"]["items"]) == 200
    assert response.json()["work_items"]["truncated"] is True


def test_CONTEXT_P2_bounded_firestore_query_skips_corrupt_document():
    from tilo_api.people_firestore import FirestoreRecordStore

    calls = []

    class Snap:
        def __init__(self, data):
            self.data = data

        def to_dict(self):
            return self.data

    class Query:
        def where(self, *, filter):
            calls.append((filter.field_path, filter.value))
            return self

        def limit(self, count):
            calls.append(count)
            return self

        def stream(self):
            return iter((Snap({}), Snap({"record": own_item("wi_valid", OWNER), "version": 1})))

    class Client:
        def collection(self, path):
            return Query()

    rows = FirestoreRecordStore(Client(), "work_item").list_bounded(ORG, "owner", OWNER, limit=201)
    assert calls == [("record.owner", OWNER), 201]
    assert [row.record["id"] for row in rows] == ["wi_valid"]


def test_CONTEXT_P2_cap_history_before_oracle_and_store_failure_is_503(people_rig, store, monkeypatch):
    import tilo_api.context_panel as context

    rig = seed_context(people_rig, store)
    item = rig.stores.work_items._inner._rows[(ORG, "wi_context_own")][1]
    item["history"] = [{}] * 201
    original = context.read

    def read(request, directory):
        assert request.record["id"] != "wi_context_own"
        return original(request, directory)

    monkeypatch.setattr(context, "read", read)
    response = rig.get("/v1/context")
    assert response.status_code == 200 and "wi_context_own" not in response.text

    def failed(*args, **kwargs):
        raise RuntimeError("private store failure")

    rig.stores.pins.list_bounded = failed
    response = rig.get("/v1/context")
    assert response.status_code == 503 and "private" not in response.text


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


def test_CONTEXT_P2_assigner_status_does_not_require_creator_identity(people_rig, store):
    rig = seed_context(people_rig, store)
    item = confirmed_item()
    item["id"] = "wi_assigned_not_created"
    assert item["created_by"]["by"] == "tilo" and item["assigned_by"]["by"] == OWNER
    rig.add("work_items", item)
    rig.as_user(OWNER)
    response = rig.get("/v1/context")
    assert response.status_code == 200
    got = next(row for row in response.json()["work_items"]["items"] if row["id"] == item["id"])
    assert got == {"id": item["id"], "status": "open"}
    assert "title" not in got and "due" not in got
    rig.as_user(DEV)
    assert item["id"] not in rig.get("/v1/context").text


def test_CONTEXT_P2_teammate_never_gets_work_item_personal_pin_or_plate_in_accessible_world(people_rig, store):
    rig = seed_context(people_rig, store)
    item = own_item("wi_teammate_shared_source", PRIYA)
    item["source"] = {"kind": "request", "ref": "w_context_other", "evidence": []}
    rig.add("work_items", item)
    rig.as_user(DEV, role="viewer", world_id="w_context_other")

    def forbidden():
        pytest.fail("context resolved another person's plate")

    rig.app.dependency_overrides[deps.get_plate_sources] = forbidden
    response = rig.get("/v1/context")
    assert response.status_code == 200
    assert "pb_launch_date" in response.text
    assert item["id"] not in response.text
    assert "wi_context_other" not in response.text
    assert "pb_context_private" not in response.text
    assert "plate" not in response.json()
