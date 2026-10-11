"""SKILLS-2 (FR-SKL-04): the taught-skill store and routes in tilo-api. "A saved skill starts as Learning and appears in
the library" (PRD supplement 1.1; contracts/taught_skill.schema.json 1.0.0; taught_skill.rules.md TS-01, TS-02, TS-04,
TS-05; ADR-0034).

Pinned interface (the ticket's decided spec; the ambiguities resolved are listed at the end):

SEAM   `deps.get_skill_store()` returns a repository with exactly these methods (records are plain dicts that conform
       to taught_skill.schema.json; a store never mutates what it is handed and returns copies):
           put(record)                                   insert or replace by (org_id, id)
           get(org, skill_id)            -> dict | None
           list_for_owner(org, owner)    -> list[dict]
           list_visible(org, user, team_ids) -> list[dict]   the user's own skills plus every skill of the org whose
                                                              scope is `team` and whose scope.team is in team_ids
       Unwired (no override, not dev mode) = 503 {"detail": "not_configured"}. A store that raises NotImplementedError
       is the same 503; any other store error is 503 {"detail": "unavailable"}, the cause never in the body or headers.
       Every answer, refusals included, carries `Cache-Control: no-store` (the `_PeopleRoute` class). The caller is
       `Principal.user_id`, the org is `deps.ORG_ID`; no query, header or path selects another owner. A caller with no
       person record in the org gets the one 404 {"detail": "not_found"} (like /v1/people and /v1/plate) and nothing
       is stored. Team ids come from the caller's current person record (`memberships[].team`), re-read on every call
       (TS-01, ADR-0015). Not signed in = 401.

POST /v1/skills   JSON only (415 otherwise), body over 32768 bytes = 413 (the people routes' cap), closed JSON object
       {name, scope, trigger, plan_steps, captured_steps?, clarifying_question?} else 422:
         scope    {"kind": "just_me", "team": null} | {"kind": "team", "team": "tm_..."}  (the record's own shape)
         trigger  {"kind": "on_demand"}
                  | {"kind": "schedule", "schedule_id": "sched_<24 hex>"}
                  | {"kind": "event", "event_type": "family.verb", "filter": {slug: str}}   (filter optional, <= 3 keys)
         plan_steps       1..20 of {text, tool, action, verb, ask_first?}; the client cannot send must_ask
         captured_steps   0..20 of {text}  (the pinned artifact stays null in this slice)
         clarifying_question  {text, options[2..4]} (answer stored as null); absent = null
       Server-stamped: id `tsk_` + a 26-character ULID, org_id = deps.ORG_ID, owner = Principal.user_id only,
       status "learning", paused false, method "describe", version 1, good_runs 0, tool_access {} (everything off),
       created_at = updated_at = the clock (`deps.get_clock`), estimates computed by code (source "prior",
       asks_per_run = the plan's steps that are not `read`, TS-05). id, org_id, owner, status, paused, version,
       good_runs, tool_access, estimates, created_at and updated_at in the body are a 422.
       A step whose verb is send, post, pay, delete, share or book is stored with must_ask true and ask_first true; a
       client sending ask_first false for it is refused 422 (BQ-TAUGHT-1 default: refuse, never silently flip).
       A team scope naming a team the caller is not a member of is 403 {"detail": "forbidden"} (TS-02).
       Names, step and question texts pass `deps.get_redactor` before they are stored.
       201 returns the stored record (the whole TaughtSkill, no wrapper). The slice writes the store only: no event.
GET  /v1/skills        200 {"skills": [record, ...]} the caller's own skills plus team-scope skills of the caller's
                       current teams, sorted by (name, id).
GET  /v1/skills/{id}   200 the record; 404 {"detail": "not_found"} for an absent id, an id that does not match
                       ^tsk_[0-9A-Za-z_]{1,48}$, another org's, or another person's just_me skill (one body).
GET  /v1/learn         200 {"learning": [records with status learning that the caller may read, sorted as above],
                       "needs_rating": [], "helpers": null} (FR-SKL-05 and FR-SKL-07 are later slices).

Ambiguities resolved (also in the report): body trigger uses the spec's flat `event_type`; plan_steps is required
(the schema makes a saved skill's plan non-empty); tool_access is {} (the schema requires the key; absent = off);
team visibility is TS-01's (scope.team in the caller's current teams) not the shares-a-team-with-the-owner wording; a
foreign-team scope is 403; no TS-06/TS-07 config checks here (no config/skills.yaml exists yet).

No network, no model, no paid call, no cloud credentials; fake secrets are assembled at runtime.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest
from _clint1_lib import seam
from _ppl11a_lib import DEV, MEERA, NOW, ORG, OTHER_ORG, OWNER, PRIYA, SAM, STANDARD_PERSONS, Rig, conforms, fake_token
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SCHEMA = "taught_skill.schema.json"
PATH = "/v1/skills"
LEARN = "/v1/learn"
R_CREATE = ("POST", PATH)
R_LIST = ("GET", PATH)
R_ONE = ("GET", "/v1/skills/{skill_id}")
R_LEARN = ("GET", LEARN)
ULID_ID = re.compile(r"^tsk_[0-7][0-9A-HJKMNP-TV-Z]{25}$")
RECORD_KEYS = {
    "id",
    "org_id",
    "owner",
    "name",
    "scope",
    "status",
    "paused",
    "method",
    "captured",
    "plan",
    "question",
    "trigger",
    "estimates",
    "tool_access",
    "good_runs",
    "version",
    "created_at",
    "updated_at",
}
SERVER_OWNED = {
    "id": "tsk_" + "0" * 26,
    "org_id": ORG,
    "owner": PRIYA,
    "status": "trusted",
    "paused": True,
    "version": 7,
    "good_runs": 9,
    "tool_access": {"gmail": "read_only"},
    "estimates": {
        "credits_per_run": 1,
        "seconds_per_run": 1,
        "asks_per_run": 0,
        "source": "ledger",
        "prices_as_of": "2026-10-01",
    },
    "created_at": "2020-01-01T00:00:00.000Z",
    "updated_at": "2020-01-01T00:00:00.000Z",
}
MUST_ASK_VERBS = ("send", "post", "pay", "delete", "share", "book")
BODY_CAP = 32768
LAUNCH, OPS, ELSEWHERE = "tm_launch", "tm_ops", "tm_elsewhere"  # priya + dev + owner; sam + meera; nobody
SCHEDULE_ID = "sched_" + "0123456789abcdef01234567"


# -- the fake store behind the seam ---------------------------------------------------------------------------------


class MemorySkillStore:
    """The repository interface the ticket pins, in memory, with a call log and a failure switch."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail: BaseException | None = None

    def _hit(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if self.fail is not None:
            raise self.fail

    def put(self, record: dict[str, Any]) -> None:
        self._hit("put", record["org_id"], record["id"])
        self.rows[(record["org_id"], record["id"])] = copy.deepcopy(record)

    def get(self, org: str, skill_id: str) -> dict[str, Any] | None:
        self._hit("get", org, skill_id)
        found = self.rows.get((org, skill_id))
        return None if found is None else copy.deepcopy(found)

    def list_for_owner(self, org: str, owner: str) -> list[dict[str, Any]]:
        self._hit("list_for_owner", org, owner)
        return [copy.deepcopy(r) for (o, _), r in self.rows.items() if o == org and r["owner"] == owner]

    def list_visible(self, org: str, user: str, team_ids: Any) -> list[dict[str, Any]]:
        self._hit("list_visible", org, user, tuple(sorted(team_ids)))
        teams = set(team_ids)
        return [
            copy.deepcopy(r)
            for (o, _), r in self.rows.items()
            if o == org and (r["owner"] == user or (r["scope"]["kind"] == "team" and r["scope"]["team"] in teams))
        ]

    def writes(self) -> list[str]:
        return [name for name, _ in self.calls if name == "put"]


class Ctx:
    def __init__(self, rig: Rig, store: MemorySkillStore) -> None:
        self.rig, self.store = rig, store

    def post(self, user: str, body: Any = None, **kwargs: Any) -> Any:
        self.rig.require_route(R_CREATE)
        self.rig.as_user(user)
        return self.rig.post(PATH, body if body is not None else valid_body(), **kwargs)

    def get(self, user: str, path: str, **kwargs: Any) -> Any:
        self.rig.as_user(user)
        return self.rig.get(path, **kwargs)

    def listing(self, user: str, **kwargs: Any) -> Any:
        self.rig.require_route(R_LIST)
        return self.get(user, PATH, **kwargs)

    def one(self, user: str, skill_id: str) -> Any:
        self.rig.require_route(R_ONE)
        return self.get(user, f"/v1/skills/{skill_id}")

    def learn(self, user: str) -> Any:
        self.rig.require_route(R_LEARN)
        return self.get(user, LEARN)

    def ids(self, user: str) -> list[str]:
        response = self.listing(user)
        assert response.status_code == 200, response.text
        return [s["id"] for s in response.json()["skills"]]


@pytest.fixture()
def ctx(people_rig):
    rig = people_rig()
    rig.add_people(STANDARD_PERSONS.values())
    store = MemorySkillStore()
    rig.app.dependency_overrides[seam(rig.deps, "get_skill_store")] = lambda: store
    yield Ctx(rig, store)


# -- builders -------------------------------------------------------------------------------------------------------


def step(
    text: str = "Read the latest report email",
    tool: str = "gmail",
    action: str = "read_email",
    verb: str = "read",
    **kw: Any,
) -> dict[str, Any]:
    return {"text": text, "tool": tool, "action": action, "verb": verb, **kw}


def three_steps() -> list[dict[str, Any]]:
    return [
        step(),
        step("Write a reply draft", "gmail", "create_draft", "draft", ask_first=False),
        step("Send the reply", "gmail", "send_email", "send"),
    ]


def valid_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Weekly report",
        "scope": {"kind": "just_me", "team": None},
        "trigger": {"kind": "on_demand"},
        "plan_steps": three_steps(),
    }
    body.update(over)
    return body


def record(
    skill_id: str,
    owner: str = PRIYA,
    *,
    name: str = "Weekly report",
    scope: tuple[str, str | None] = ("just_me", None),
    status: str = "learning",
    org: str = ORG,
) -> dict[str, Any]:
    """A schema-valid stored skill, for seeding the store directly."""
    return {
        "id": skill_id,
        "org_id": org,
        "owner": owner,
        "name": name,
        "scope": {"kind": scope[0], "team": scope[1]},
        "status": status,
        "paused": False,
        "method": "describe",
        "captured": [],
        "plan": [
            {
                "text": "Read it",
                "tool": "gmail",
                "action": "read_email",
                "verb": "read",
                "ask_first": False,
                "must_ask": False,
            }
        ],
        "question": None,
        "trigger": {"kind": "on_demand", "schedule_id": None, "event": None},
        "estimates": {
            "credits_per_run": 2,
            "seconds_per_run": 30,
            "asks_per_run": 0,
            "source": "prior",
            "prices_as_of": "2026-10-01",
        },
        "tool_access": {},
        "good_runs": 0,
        "version": 1,
        "created_at": "2026-10-05T10:00:00.000Z",
        "updated_at": "2026-10-05T10:00:00.000Z",
    }


def seed(c: Ctx, *records: dict[str, Any]) -> None:
    for r in records:
        assert conforms(SCHEMA, r), f"test bug: seed record {r['id']} is not schema-valid"
        c.store.rows[(r["org_id"], r["id"])] = copy.deepcopy(r)
    c.store.calls.clear()


def created(c: Ctx, user: str = PRIYA, **over: Any) -> dict[str, Any]:
    response = c.post(user, valid_body(**over))
    assert response.status_code == 201, response.text
    return response.json()


# -- seam -----------------------------------------------------------------------------------------------------------


def test_FR_SKL_04_SKILLS_2_store_seam_exists_in_deps(ctx):
    assert hasattr(ctx.rig.deps, "get_skill_store"), "deps.get_skill_store (the taught-skill store seam) is missing"


def test_FR_SKL_04_SKILLS_2_unwired_seam_is_503_not_configured_on_every_route(ctx):
    ctx.rig.unwire("skill_store")
    for method, path in (("POST", PATH), ("GET", PATH), ("GET", "/v1/skills/tsk_" + "A" * 26), ("GET", LEARN)):
        ctx.rig.require_route((method, "/v1/skills/{skill_id}" if "tsk_" in path else path))
        ctx.rig.as_user(PRIYA)
        response = ctx.rig.post(path, valid_body()) if method == "POST" else ctx.rig.get(path)
        assert response.status_code == 503, (method, path, response.text)
        assert response.json() == {"detail": "not_configured"}
        assert response.headers["cache-control"] == "no-store"


# -- create: the happy path and what the server stamps --------------------------------------------------------------


def test_FR_SKL_04_SKILLS_2_save_starts_as_learning_and_is_the_stored_record(ctx):
    ctx.rig.set_now(NOW)
    response = ctx.post(PRIYA)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["status"] == "learning"
    assert ctx.store.rows[(ORG, saved["id"])] == saved  # 201 returns exactly what was stored
    assert response.headers["cache-control"] == "no-store"


def test_FR_SKL_04_SKILLS_2_stored_record_is_schema_valid_with_exactly_the_schema_keys(ctx):
    saved = created(ctx)
    assert conforms(SCHEMA, saved), saved
    assert set(saved) == RECORD_KEYS


def test_FR_SKL_04_SKILLS_2_server_stamps_id_owner_org_version_counts_and_times(ctx):
    ctx.rig.set_now(NOW)
    saved = created(ctx, PRIYA)
    assert ULID_ID.fullmatch(saved["id"]), saved["id"]
    assert saved["owner"] == PRIYA and saved["org_id"] == ORG
    assert (saved["status"], saved["paused"], saved["method"]) == ("learning", False, "describe")
    assert (saved["version"], saved["good_runs"]) == (1, 0)
    assert saved["tool_access"] == {}  # everything off until a later slice sets the least-privilege levels
    assert saved["created_at"] == saved["updated_at"] == NOW
    assert saved["question"] is None and saved["captured"] == []


def test_FR_SKL_04_SKILLS_2_owner_is_the_principal_whoever_the_body_names(ctx):
    for user in (PRIYA, SAM):
        assert created(ctx, user)["owner"] == user


@pytest.mark.parametrize("field", sorted(SERVER_OWNED))
def test_FR_SKL_04_SKILLS_2_body_cannot_set_server_owned_field(ctx, field):
    response = ctx.post(PRIYA, valid_body(**{field: SERVER_OWNED[field]}))
    assert response.status_code == 422, response.text
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_plan_steps_stored_in_order_with_the_schema_plan_shape(ctx):
    saved = created(ctx)
    assert [s["text"] for s in saved["plan"]] == [s["text"] for s in three_steps()]
    assert [s["verb"] for s in saved["plan"]] == ["read", "draft", "send"]
    for s in saved["plan"]:
        assert set(s) == {"text", "tool", "action", "verb", "ask_first", "must_ask"}
    assert (
        saved["plan"][0]["ask_first"] is False
    )  # a read the client left unasked stays unasked (TS-05 asks at run time)


def test_FR_SKL_04_SKILLS_2_estimates_are_computed_by_code_and_count_the_stops_to_ask(ctx):
    saved = created(ctx)  # read, draft, send: while learning every step that is not a read asks (TS-05)
    estimates = saved["estimates"]
    assert estimates["source"] == "prior"
    assert estimates["asks_per_run"] == 2
    assert estimates["credits_per_run"] >= 0 and estimates["seconds_per_run"] >= 0


@pytest.mark.parametrize("verb", MUST_ASK_VERBS)
def test_FR_SKL_04_SKILLS_2_must_ask_verbs_are_stored_with_must_ask_and_ask_first(ctx, verb):
    saved = created(ctx, plan_steps=[step("Do it", "gmail", "send_email", verb)])
    stored = saved["plan"][0]
    assert stored["must_ask"] is True and stored["ask_first"] is True
    assert conforms(SCHEMA, saved)


@pytest.mark.parametrize("verb", MUST_ASK_VERBS)
def test_FR_SKL_04_SKILLS_2_client_ask_first_false_on_a_must_ask_verb_is_refused(ctx, verb):
    response = ctx.post(PRIYA, valid_body(plan_steps=[step("Do it", "gmail", "send_email", verb, ask_first=False)]))
    assert response.status_code == 422, response.text
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_client_cannot_send_must_ask(ctx):
    response = ctx.post(PRIYA, valid_body(plan_steps=[step(must_ask=False)]))
    assert response.status_code == 422
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_unknown_connector_action_is_refused_422(ctx):
    response = ctx.post(PRIYA, valid_body(plan_steps=[step("Read", "nosuchtool", "read_things")]))
    assert response.status_code == 422  # TS-06: tool and action are an action of a configured connector
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_triggers_on_demand_schedule_and_event_are_stored_in_record_shape(ctx):
    cases = [
        ({"kind": "on_demand"}, {"kind": "on_demand", "schedule_id": None, "event": None}),
        (
            {"kind": "schedule", "schedule_id": SCHEDULE_ID},
            {"kind": "schedule", "schedule_id": SCHEDULE_ID, "event": None},
        ),
        (
            {"kind": "event", "event_type": "work_item.created", "filter": {"status": "open"}},
            {
                "kind": "event",
                "schedule_id": None,
                "event": {"type": "work_item.created", "filter": {"status": "open"}},
            },
        ),
        (
            {"kind": "event", "event_type": "work_item.created"},
            {"kind": "event", "schedule_id": None, "event": {"type": "work_item.created", "filter": {}}},
        ),
    ]
    for given_trigger, stored_trigger in cases:
        saved = created(ctx, trigger=given_trigger)
        assert saved["trigger"] == stored_trigger
        assert conforms(SCHEMA, saved)


@pytest.mark.parametrize(
    "trigger",
    [
        {"kind": "weekly"},
        {"kind": "schedule"},
        {"kind": "schedule", "schedule_id": "not-a-schedule"},
        {"kind": "on_demand", "schedule_id": SCHEDULE_ID},
        {"kind": "event"},
        {"kind": "event", "event_type": "Not An Event"},
        {"kind": "event", "event_type": "work_item.created", "filter": {"a": "1", "b": "2", "c": "3", "d": "4"}},
        {"kind": "event", "event_type": "work_item.created", "filter": {"status": "free text with spaces"}},
        {"kind": "on_demand", "extra": 1},
    ],
)
def test_FR_SKL_04_SKILLS_2_bad_trigger_is_422(ctx, trigger):
    assert ctx.post(PRIYA, valid_body(trigger=trigger)).status_code == 422
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_captured_steps_and_clarifying_question_are_stored(ctx):
    saved = created(
        ctx,
        captured_steps=[{"text": "Opened the sales sheet"}, {"text": "Copied the totals"}],
        clarifying_question={"text": "Which sheet is the right one?", "options": ["This month", "Last month"]},
    )
    assert saved["captured"] == [
        {"text": "Opened the sales sheet", "artifact": None},
        {"text": "Copied the totals", "artifact": None},
    ]
    assert saved["question"] == {
        "text": "Which sheet is the right one?",
        "options": ["This month", "Last month"],
        "answer": None,
    }
    assert conforms(SCHEMA, saved)


# -- create: scope --------------------------------------------------------------------------------------------------


def test_FR_SKL_04_SKILLS_2_team_scope_names_a_team_the_owner_belongs_to(ctx):
    saved = created(ctx, PRIYA, scope={"kind": "team", "team": LAUNCH})
    assert saved["scope"] == {"kind": "team", "team": LAUNCH}
    assert conforms(SCHEMA, saved)


def test_FR_SKL_04_SKILLS_2_team_scope_for_a_team_the_owner_is_not_in_is_403(ctx):
    for team in (OPS, ELSEWHERE):
        response = ctx.post(PRIYA, valid_body(scope={"kind": "team", "team": team}))
        assert response.status_code == 403, response.text
        assert response.json() == {"detail": "forbidden"}
    assert ctx.store.writes() == []


@pytest.mark.parametrize(
    "scope",
    [
        {"kind": "team", "team": None},
        {"kind": "just_me", "team": LAUNCH},
        {"kind": "everyone", "team": None},
        {"kind": "team"},
        {"kind": "just_me", "team": None, "extra": 1},
        "just_me",
    ],
)
def test_FR_SKL_04_SKILLS_2_bad_scope_is_422(ctx, scope):
    assert ctx.post(PRIYA, valid_body(scope=scope)).status_code == 422
    assert ctx.store.writes() == []


# -- create: shape, size, content type, redaction -------------------------------------------------------------------


def test_FR_SKL_04_SKILLS_2_closed_body_unknown_key_is_422(ctx):
    assert ctx.post(PRIYA, valid_body(colour="red")).status_code == 422
    assert ctx.store.writes() == []


@pytest.mark.parametrize(
    "over",
    [
        {"name": ""},
        {"name": "x" * 81},
        {"name": "two\nlines"},
        {"name": 7},
        {"plan_steps": []},
        {"plan_steps": [step()] * 21},
        {"plan_steps": [step("t" * 201)]},
        {"plan_steps": [step("two\nlines")]},
        {"plan_steps": [step(verb="steal")]},
        {"captured_steps": [{"text": "x"}] * 21},
        {"clarifying_question": {"text": "Which?", "options": ["only one"]}},
        {"clarifying_question": {"text": "Which?", "options": ["a", "b", "c", "d", "e"]}},
    ],
)
def test_FR_SKL_04_SKILLS_2_out_of_range_fields_are_422(ctx, over):
    assert ctx.post(PRIYA, valid_body(**over)).status_code == 422
    assert ctx.store.writes() == []


@pytest.mark.parametrize("missing", ["name", "scope", "trigger", "plan_steps"])
def test_FR_SKL_04_SKILLS_2_missing_required_field_is_422(ctx, missing):
    body = valid_body()
    del body[missing]
    assert ctx.post(PRIYA, body).status_code == 422
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_body_that_is_not_an_object_or_not_json_is_422(ctx):
    ctx.rig.require_route(R_CREATE)
    ctx.rig.as_user(PRIYA)
    headers = {"content-type": "application/json"}
    for raw in (b"[1,2]", b"null", b'"text"', b"{not json"):
        assert ctx.rig.client.post(PATH, content=raw, headers=headers).status_code == 422, raw
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_only_json_is_read_415(ctx):
    ctx.rig.require_route(R_CREATE)
    ctx.rig.as_user(PRIYA)
    for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
        response = ctx.rig.client.post(PATH, content=json.dumps(valid_body()), headers={"content-type": content_type})
        assert response.status_code == 415, (content_type, response.text)
        assert response.headers["cache-control"] == "no-store"
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_body_over_32768_bytes_is_413_and_stores_nothing(ctx):
    ctx.rig.require_route(R_CREATE)
    ctx.rig.as_user(PRIYA)
    big = json.dumps(valid_body(captured_steps=[{"text": "y" * 150}] * 20, pad="z" * BODY_CAP))
    assert len(big.encode()) > BODY_CAP
    response = ctx.rig.client.post(PATH, content=big, headers={"content-type": "application/json"})
    assert response.status_code == 413, response.text
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_name_and_step_text_pass_the_redactor_before_storage(ctx):
    secret = fake_token()
    saved = created(ctx, name=f"Report {secret}", plan_steps=[step(f"Read the mail {secret}")])
    assert secret not in json.dumps(saved) and secret not in json.dumps(list(ctx.store.rows.values()))
    assert any(secret in call for call in ctx.rig.redactor.calls)


def test_FR_SKL_04_SKILLS_2_save_by_a_person_with_no_record_is_404_and_stores_nothing(ctx):
    response = ctx.post("u_stranger", valid_body())
    assert response.status_code == 404 and response.json() == {"detail": "not_found"}
    assert ctx.store.writes() == []


def test_FR_SKL_04_SKILLS_2_two_saves_make_two_distinct_skills(ctx):
    first, second = created(ctx), created(ctx)
    assert first["id"] != second["id"]
    assert ids_of(ctx, PRIYA) == sorted([first["id"], second["id"]], key=lambda i: ("Weekly report", i))
    assert len(ctx.store.rows) == 2


def ids_of(c: Ctx, user: str) -> list[str]:
    return c.ids(user)


def test_FR_SKL_04_SKILLS_2_save_writes_the_store_once_and_emits_no_event(ctx):
    created(ctx)
    assert ctx.store.writes() == ["put"]
    assert ctx.rig.events.calls == []  # events are the next slice


def test_FR_SKL_04_SKILLS_2_saved_skill_appears_in_the_library_and_in_learning(ctx):
    saved = created(ctx)
    assert ctx.ids(PRIYA) == [saved["id"]]
    learn = ctx.learn(PRIYA).json()
    assert [s["id"] for s in learn["learning"]] == [saved["id"]]


# -- read: visibility -----------------------------------------------------------------------------------------------


def test_FR_SKL_04_SKILLS_2_empty_library_is_an_empty_list(ctx):
    response = ctx.listing(PRIYA)
    assert response.status_code == 200 and response.json() == {"skills": []}
    assert response.headers["cache-control"] == "no-store"


def test_FR_SKL_04_SKILLS_2_just_me_skill_is_seen_by_nobody_else(ctx):
    mine = created(ctx, PRIYA)
    for other in (DEV, SAM, MEERA, OWNER):  # a teammate, other team, an org owner of another team, the org owner
        assert ctx.ids(other) == [], other
        denied = ctx.one(other, mine["id"])
        assert denied.status_code == 404 and denied.json() == {"detail": "not_found"}
    assert ctx.one(PRIYA, mine["id"]).json() == mine


def test_FR_SKL_04_SKILLS_2_team_skill_is_seen_by_the_team_and_not_by_an_outsider(ctx):
    shared = created(ctx, PRIYA, scope={"kind": "team", "team": LAUNCH})
    for mate in (PRIYA, DEV, OWNER):  # tm_launch
        assert ctx.ids(mate) == [shared["id"]], mate
        assert ctx.one(mate, shared["id"]).json() == shared
    for outsider in (SAM, MEERA):  # tm_ops, even an org owner (TS-01: nobody else)
        assert ctx.ids(outsider) == [], outsider
        assert ctx.one(outsider, shared["id"]).status_code == 404


def test_FR_SKL_04_SKILLS_2_membership_is_re_read_on_every_call(ctx):
    shared = created(ctx, PRIYA, scope={"kind": "team", "team": LAUNCH})
    assert ctx.ids(DEV) == [shared["id"]]
    stored = ctx.rig.real.persons.get(ORG, DEV)
    moved = copy.deepcopy(dict(stored.record))
    moved["memberships"] = [m | {"team": OPS} for m in moved["memberships"]]
    ctx.rig.real.persons.replace(moved, expected_version=stored.version)
    assert ctx.ids(DEV) == []
    assert ctx.one(DEV, shared["id"]).status_code == 404


def test_FR_SKL_04_SKILLS_2_unknown_absent_and_malformed_ids_share_one_404_body(ctx):
    mine = created(ctx, PRIYA)
    absent = ctx.one(PRIYA, "tsk_" + "Z" * 26)
    foreign = ctx.one(SAM, mine["id"])
    malformed = ctx.one(PRIYA, "not-a-skill-id")
    assert absent.status_code == foreign.status_code == malformed.status_code == 404
    assert absent.json() == foreign.json() == malformed.json() == {"detail": "not_found"}
    assert absent.headers["cache-control"] == "no-store"


def test_FR_SKL_04_SKILLS_2_another_orgs_skill_never_appears(ctx):
    seed(
        ctx,
        record("tsk_OTHERORG", SAM, org=OTHER_ORG),
        record("tsk_SAMETEAMOTHERORG", DEV, scope=("team", LAUNCH), org=OTHER_ORG),
    )
    for user in (PRIYA, DEV, SAM):
        assert ctx.ids(user) == []
        assert ctx.learn(user).json()["learning"] == []
    assert ctx.one(SAM, "tsk_OTHERORG").status_code == 404
    assert ctx.one(DEV, "tsk_SAMETEAMOTHERORG").status_code == 404


def test_FR_SKL_04_SKILLS_2_nothing_in_the_request_selects_another_owner(ctx):
    theirs = created(ctx, PRIYA)
    ctx.rig.as_user(SAM)
    for kwargs in (
        {"params": {"owner": PRIYA, "user": PRIYA, "user_id": PRIYA, "org": ORG}},
        {"headers": {"X-Owner": PRIYA, "X-User-Id": PRIYA, "X-Tilo-Owner": PRIYA}},
    ):
        response = ctx.rig.get(PATH, **kwargs)
        assert response.status_code == 200 and response.json() == {"skills": []}
        assert theirs["id"] not in response.text


def test_FR_SKL_04_SKILLS_2_library_is_sorted_by_name_then_id(ctx):
    seed(
        ctx,
        record("tsk_B", PRIYA, name="Zeta"),
        record("tsk_C", PRIYA, name="Alpha"),
        record("tsk_A", PRIYA, name="Alpha"),
        record("tsk_D", DEV, name="Beta", scope=("team", LAUNCH)),
    )
    assert ctx.ids(PRIYA) == ["tsk_A", "tsk_C", "tsk_D", "tsk_B"]
    assert [s["id"] for s in ctx.learn(PRIYA).json()["learning"]] == ["tsk_A", "tsk_C", "tsk_D", "tsk_B"]


def test_FR_SKL_04_SKILLS_2_learn_lists_only_learning_skills_the_caller_may_read(ctx):
    seed(
        ctx,
        record("tsk_L1", PRIYA, name="A", status="learning"),
        record("tsk_T1", PRIYA, name="B", status="trusted"),
        record("tsk_L2", DEV, name="C", status="learning", scope=("team", LAUNCH)),
        record("tsk_L3", DEV, name="D", status="learning"),
        record("tsk_L4", SAM, name="E", status="learning", scope=("team", OPS)),
    )
    learn = ctx.learn(PRIYA)
    assert learn.status_code == 200
    assert set(learn.json()) == {"learning", "needs_rating", "helpers"}
    assert [s["id"] for s in learn.json()["learning"]] == ["tsk_L1", "tsk_L2"]
    assert learn.json()["needs_rating"] == [] and learn.json()["helpers"] is None
    assert ctx.ids(PRIYA) == ["tsk_L1", "tsk_T1", "tsk_L2"]


def test_FR_SKL_04_SKILLS_2_learn_for_a_person_with_no_record_is_404(ctx):
    response = ctx.learn("u_stranger")
    assert response.status_code == 404 and response.json() == {"detail": "not_found"}
    assert ctx.listing("u_stranger").status_code == 404
    assert ctx.one("u_stranger", "tsk_L1").status_code == 404


def test_FR_SKL_04_SKILLS_2_reads_write_nothing(ctx):
    seed(ctx, record("tsk_R1", PRIYA))
    before = copy.deepcopy(ctx.store.rows)
    ctx.listing(PRIYA)
    ctx.one(PRIYA, "tsk_R1")
    ctx.learn(PRIYA)
    assert ctx.store.writes() == [] and ctx.store.rows == before
    assert ctx.rig.events.calls == []


# -- errors and auth ------------------------------------------------------------------------------------------------

ROUTES = [("POST", PATH), ("GET", PATH), ("GET", "/v1/skills/tsk_ABC"), ("GET", LEARN)]


def _call(c: Ctx, method: str, path: str, user: str = PRIYA) -> Any:
    c.rig.require_route((method, "/v1/skills/{skill_id}" if path.startswith("/v1/skills/") else path))
    c.rig.as_user(user)
    return c.rig.post(path, valid_body()) if method == "POST" else c.rig.get(path)


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_FR_SKL_04_SKILLS_2_store_not_implemented_is_503_not_configured(ctx, method, path):
    ctx.store.fail = NotImplementedError("no firestore here")
    response = _call(ctx, method, path)
    assert response.status_code == 503 and response.json() == {"detail": "not_configured"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_FR_SKL_04_SKILLS_2_store_error_is_503_unavailable_without_the_cause(ctx, method, path):
    cause = "backend exploded " + fake_token()
    ctx.store.fail = RuntimeError(cause)
    response = _call(ctx, method, path)
    assert response.status_code == 503 and response.json() == {"detail": "unavailable"}
    assert cause not in response.text and "exploded" not in str(response.headers)
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_FR_SKL_04_SKILLS_2_signed_out_is_401_and_touches_no_store(ctx, method, path):
    ctx.rig.sign_out()
    ctx.rig.require_route((method, "/v1/skills/{skill_id}" if path.startswith("/v1/skills/") else path))
    response = ctx.rig.post(path, valid_body()) if method == "POST" else ctx.rig.get(path)
    assert response.status_code == 401
    assert ctx.store.calls == []


# -- properties -----------------------------------------------------------------------------------------------------

_text = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), max_codepoint=0x024F), min_size=1, max_size=30
)
_connector = st.sampled_from(
    [
        ("gmail", "read_email", "read"),
        ("gmail", "create_draft", "draft"),
        ("google_drive", "save_file", "write"),
        ("gmail", "send_email", "send"),
        ("gmail", "send_email", "delete"),
        ("gmail", "send_email", "book"),
    ]
)
_steps = st.lists(
    st.builds(
        lambda t, c, a: step(t, c[0], c[1], c[2], **({} if a is None else {"ask_first": a})),
        _text,
        _connector,
        st.one_of(st.none(), st.just(True)),
    ),
    min_size=1,
    max_size=6,
)
_triggers = st.one_of(
    st.just({"kind": "on_demand"}),
    st.just({"kind": "schedule", "schedule_id": SCHEDULE_ID}),
    st.fixed_dictionaries({"kind": st.just("event"), "event_type": st.just("work_item.created")}),
)
_scopes = st.sampled_from([{"kind": "just_me", "team": None}, {"kind": "team", "team": LAUNCH}])
_questions = st.one_of(
    st.none(),
    st.builds(lambda t, o: {"text": t, "options": o}, _text, st.lists(_text, min_size=2, max_size=4)),
)


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(name=_text, steps=_steps, trigger=_triggers, scope=_scopes, question=_questions)
def test_FR_SKL_04_SKILLS_2_property_every_stored_and_returned_record_is_schema_valid(
    ctx, name, steps, trigger, scope, question
):
    body = valid_body(name=name, plan_steps=steps, trigger=trigger, scope=scope)
    if question is not None:
        body["clarifying_question"] = question
    response = ctx.post(PRIYA, body)
    assert response.status_code == 201, response.text
    saved = response.json()
    assert conforms(SCHEMA, saved), saved
    assert set(saved) == RECORD_KEYS  # nothing outside the schema, nothing missing
    assert saved["owner"] == PRIYA and saved["status"] == "learning" and saved["version"] == 1
    assert ctx.store.rows[(ORG, saved["id"])] == saved
    for given_step, stored_step in zip(steps, saved["plan"], strict=True):
        if given_step["verb"] in MUST_ASK_VERBS:
            assert stored_step["must_ask"] is True and stored_step["ask_first"] is True
    assert saved["estimates"]["asks_per_run"] == sum(1 for s in steps if s["verb"] != "read")
    assert conforms(SCHEMA, ctx.one(PRIYA, saved["id"]).json())  # 30 examples stay under the 60 saves a minute limit


_USERS = [PRIYA, DEV, SAM, MEERA, OWNER]
_TEAMS_OF = {PRIYA: {LAUNCH}, DEV: {LAUNCH}, OWNER: {LAUNCH}, SAM: {OPS}, MEERA: {OPS}}
_seeded = st.lists(
    st.tuples(
        st.sampled_from(_USERS),
        st.sampled_from([("just_me", None), ("team", LAUNCH), ("team", OPS), ("team", ELSEWHERE)]),
        st.sampled_from(["learning", "trusted"]),
        st.sampled_from([ORG, OTHER_ORG]),
        st.sampled_from(["Alpha", "Beta", "Gamma"]),
    ),
    max_size=12,
)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(rows=_seeded)
def test_FR_SKL_04_SKILLS_2_property_visibility_is_own_plus_current_team_in_this_org_only(ctx, rows):
    ctx.store.rows.clear()
    records = [
        record(f"tsk_P{i:02d}", owner, name=name, scope=scope, status=status, org=org)
        for i, (owner, scope, status, org, name) in enumerate(rows)
    ]
    seed(ctx, *records)
    for user in _USERS:
        expected = sorted(
            (
                r
                for r in records
                if r["org_id"] == ORG
                and (r["owner"] == user or (r["scope"]["kind"] == "team" and r["scope"]["team"] in _TEAMS_OF[user]))
            ),
            key=lambda r: (r["name"], r["id"]),
        )
        listing = ctx.listing(user)
        assert [s["id"] for s in listing.json()["skills"]] == [r["id"] for r in expected], user
        assert all(conforms(SCHEMA, s) for s in listing.json()["skills"])
        learning = ctx.learn(user).json()["learning"]
        assert [s["id"] for s in learning] == [r["id"] for r in expected if r["status"] == "learning"], user
        for r in records:
            visible = r in expected
            assert ctx.one(user, r["id"]).status_code == (200 if visible else 404), (user, r["id"])
    assert ctx.store.writes() == []
