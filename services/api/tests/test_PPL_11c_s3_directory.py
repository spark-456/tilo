"""PPL-11c slice 3: the directory (PE-17, PE-19, PE-20; API_PPL_11c.md section 4). Only an org owner changes it, the
first person of an org is minted by tilo-api as its owner, an email is a validated address that belongs to one person
of the org, and a principal is bound to exactly one person record.

* `POST /v1/people/first`: the signed-in principal becomes the org's first person and its owner (`deps.ORG_ID`, never
  the request's); refused (403) once the org has any person or the principal has a record; one winner when two race.
* `POST /v1/people` and `/first` validate `email` (ASCII address, no control, format or invisible character) and keep
  it unique in the org (409 `email_taken`, case-insensitive; one winner when callers race).
* `POST /v1/people/{id}/memberships` (+ `/remove`) and `POST /v1/people/{id}/role`: an org owner only; the stamp is the
  owner and the server clock; a refused change is the one 404; roles are only ever promoted.
"""

from __future__ import annotations

import pytest
from _ppl11a_lib import DEV, MEERA, NOW, OTHER_ORG, OWNER, PRIYA, SAM, conforms, pl, run_threads, u
from _ppl11c_lib import (
    PERSON_BODY,
    R_PERSON_FIRST,
    R_ROLE,
    R_TEAM_ADD,
    R_TEAM_REMOVE,
    UNIQUE_ID,
    assert_gated,
    assert_unwired_is_503,
    path_of,
    refusals,
)
from fastapi import Request
from fastapi.testclient import TestClient

MEMBERSHIP_VIEW = {"id", "display_name", "org_role", "memberships"}
BAD_EMAILS = {  # each is accepted by the contract's pattern today; the API refuses it (422)
    "NUL": "ni\x00na@example.com",
    "DEL": "ni\x7fna@example.com",
    "ESC": "ni\x1bna@example.com",
    "bidi override": "ni" + u(0x202E) + "na@example.com",
    "zero width": "ni" + u(0x200B) + "na@example.com",
    "non-ASCII local": "niéna@example.com",
    "non-ASCII domain": "nina@exämple.com",
    "angle brackets": "<nina@example.com>",
    "quoted local": '"nina"@example.com',
    "backslash": "ni\\na@example.com",
    "slash": "a/b@example.com",
    "pipe": "a|b@example.com",
    "semicolon": "a;b@example.com",
    "colon": "a:b@example.com",
    "parentheses": "a(b)@example.com",
    "leading dot": ".nina@example.com",
    "double dot": "ni..na@example.com",
    "trailing dot in local part": "nina.@example.com",
    "label starts with a hyphen": "nina@-example.com",
    "empty label": "nina@example..com",
    "trailing dot": "nina@example.com.",
    "ip literal": "nina@[127.0.0.1]",
    "underscore in domain": "a@exa_mple.com",
    "label over 63": "a@" + "x" * 64 + ".com",
    "digits in the top level": "a@example.c0m",
    "one-letter top level": "a@example.c",
}


def _person(**changes):
    return {**PERSON_BODY, **changes}


def _first(rig, body=None):
    rig.require_route(R_PERSON_FIRST)
    return rig.client.post("/v1/people/first", json=_person() if body is None else body)


def _org_owner_rig(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    return rig


# --- the first person of an org (PE-17) -----------------------------------------------------------------------------


def test_PPL_11c_s3_PE_17_the_first_person_of_an_org_is_minted_as_its_owner_from_the_principal(people_rig):
    """Given an org with no person, when the signed-in principal u_founder posts their details, then 201 with the
    membership view; the stored record has the principal's id, `org_id` = `deps.ORG_ID`, role owner, no memberships,
    `created_by` = {founder, server now}; then the founder may create people and promote them."""
    rig = people_rig()
    rig.as_user("u_founder")
    response = _first(rig)
    assert response.status_code == 201, response.text[:300]
    assert response.json() == {"id": "u_founder", "display_name": "Nina Patel", "org_role": "owner", "memberships": []}
    stored = rig.stored("persons", "u_founder")
    assert conforms("person.schema.json", stored)
    assert (stored["id"], stored["org_id"], stored["org_role"], stored["memberships"]) == (
        "u_founder",
        rig.org,
        "owner",
        [],
    )
    assert stored["created_by"] == {"by": "u_founder", "at": NOW}
    assert (stored["email"], stored["aliases"], stored["time_zone"]) == (PERSON_BODY["email"], ["Nina"], "Asia/Kolkata")
    colleague = rig.post("/v1/people", _person(email="sam@example.com", display_name="Sam"))
    assert colleague.status_code == 201 and rig.stored("persons", colleague.json()["id"])["created_by"] == {
        "by": "u_founder",
        "at": NOW,
    }


@pytest.mark.parametrize(
    "extra",
    [{"org_id": "org_other"}, {"org_role": "owner"}, {"id": "u_other"}, {"created_by": {"by": "u_x", "at": NOW}},
     {"memberships": []}, {"org": "org_other"}],
    ids=lambda e: next(iter(e)),
)  # fmt: skip
def test_PPL_11c_s3_PE_17_the_org_and_the_role_never_come_from_the_request(people_rig, extra):
    rig = people_rig()
    rig.as_user("u_founder")
    assert _first(rig, _person(**extra)).status_code == 422
    assert rig.stored("persons", "u_founder") is None


def test_PPL_11c_s3_PE_17_once_an_org_has_a_person_nobody_else_becomes_its_first_and_its_owner(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user("u_late")
    before = rig.snapshot()
    refused = _first(rig)
    assert refused.status_code == 403, refused.text[:200]
    assert rig.snapshot() == before, "no record, no promotion, nothing"
    rig.as_user(PRIYA)  # a member with a record is not a newcomer either
    assert _first(rig, _person(email="priya.two@example.com")).status_code == 403
    rig.as_user(OWNER)
    assert _first(rig, _person(email="owner.two@example.com")).status_code == 403
    assert rig.snapshot() == before


def test_PPL_11c_s3_PE_17_a_principal_is_bound_to_exactly_one_person_record(people_rig):
    rig = people_rig()
    rig.as_user("u_founder")
    assert _first(rig).status_code == 201
    again = _first(rig, _person(email="other@example.com"))
    assert again.status_code == 403, "a second record for the same principal"
    assert [s.record["id"] for s in rig.real.persons.list(rig.org)] == ["u_founder"]


def test_PPL_11c_s3_PE_17_two_principals_racing_for_an_empty_org_leave_exactly_one_owner(people_rig):
    """Eight signed-in strangers claim an empty org at once: one 201, seven 403, one record, and it is an owner."""
    rig = people_rig()
    rig.require_route(R_PERSON_FIRST)

    def principal(request: Request):
        return rig.deps.Principal(user_id=request.headers["x-test-user"], role="owner")

    rig.app.dependency_overrides[rig.deps.get_current_principal] = principal

    def claim(i: int) -> int:
        with TestClient(rig.app, raise_server_exceptions=False) as client:
            body = _person(email=f"founder{i}@example.com", display_name=f"Founder {i}")
            return client.post("/v1/people/first", json=body, headers={"x-test-user": f"u_f{i}"}).status_code

    statuses = run_threads(8, claim)
    assert sorted(statuses) == [201] + [403] * 7, statuses
    persons = [s.record for s in rig.real.persons.list(rig.org)]
    assert len(persons) == 1 and persons[0]["org_role"] == "owner"


# --- email: validated and unique (#464, #470) -----------------------------------------------------------------------


@pytest.mark.parametrize("email", list(BAD_EMAILS.values()), ids=list(BAD_EMAILS))
def test_PPL_11c_s3_PE_09_an_email_is_a_printable_ascii_address_or_a_422(people_rig, email):
    """The contract's pattern lets NUL, DEL, U+202E and more through; a recipient is resolved from this field (PE-09),
    so the API accepts only an ASCII dot-atom address (letters, digits, `. _ % + - '` before the `@`; dotted
    letter-digit-hyphen labels after it, the last one letters only). Never echoed back."""
    rig = _org_owner_rig(people_rig)
    before = rig.snapshot()
    response = rig.client.post("/v1/people", json=_person(email=email))
    assert response.status_code == 422, (repr(email), response.status_code)
    assert "example" not in response.text, "the address is not echoed"
    rig2 = people_rig()
    rig2.as_user("u_founder")
    assert _first(rig2, _person(email=email)).status_code == 422, "the first person's address is checked too"
    assert rig.snapshot() == before and rig2.stored("persons", "u_founder") is None


def test_PPL_11c_s3_PE_17_an_email_belongs_to_one_person_of_the_org_whatever_its_case(people_rig):
    rig = _org_owner_rig(people_rig)
    first = rig.post("/v1/people", _person())
    assert first.status_code == 201
    before = rig.snapshot()
    for email in (
        "nina.patel@example.com",
        "NINA.PATEL@EXAMPLE.COM",
        "Nina.Patel@Example.com",
        "priya@example.com",
        "ASHA@example.com",
    ):
        taken = rig.post("/v1/people", _person(email=email, display_name="Someone Else"))
        assert taken.status_code == 409 and taken.json()["code"] == "email_taken", (email, taken.text[:200])
    assert rig.snapshot() == before, "no second record"
    assert rig.post("/v1/people", _person(email="nina.patel2@example.com")).status_code == 201
    rig.add("persons", pl.person(id="u_elsewhere", org_id=OTHER_ORG, email="dup@example.org"))
    assert rig.post("/v1/people", _person(email="dup@example.org", display_name="Dup")).status_code == 201, (
        "the API serves one org: another org's address is not a clash"
    )


def test_PPL_11c_s3_PE_17_eight_racing_creates_with_one_address_leave_one_person(people_rig):
    rig = _org_owner_rig(people_rig)
    count = len(rig.real.persons.list(rig.org))

    def create(i: int) -> int:
        with TestClient(rig.app, raise_server_exceptions=False) as client:
            return client.post("/v1/people", json=_person(display_name=f"Nina {i}")).status_code

    statuses = run_threads(8, create)
    assert statuses.count(201) == 1 and statuses.count(409) == 7, statuses
    assert len(rig.real.persons.list(rig.org)) == count + 1


# --- memberships (PE-02, PE-17) -------------------------------------------------------------------------------------


def _team(rig, person_id: str, team: str = "tm_ops", **body):
    rig.require_route(R_TEAM_ADD)
    return rig.client.post(path_of(R_TEAM_ADD, person_id=person_id), json={"team": team, **body})


def _unteam(rig, person_id: str, team: str = "tm_launch", **body):
    rig.require_route(R_TEAM_REMOVE)
    return rig.client.post(path_of(R_TEAM_REMOVE, person_id=person_id), json={"team": team, **body})


def test_PPL_11c_s3_PE_17_an_org_owner_adds_a_person_to_a_team_and_the_stamp_is_theirs(people_rig):
    rig = _org_owner_rig(people_rig)
    before = rig.stored("persons", PRIYA)
    version = rig.version_of("persons", PRIYA)
    response = _team(rig, PRIYA, "tm_ops")
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("persons", PRIYA)
    assert conforms("person.schema.json", stored)
    assert stored["memberships"] == before["memberships"] + [
        {"team": "tm_ops", "assigned_by": {"by": OWNER, "at": NOW}}
    ]
    assert response.json() == {k: stored[k] for k in MEMBERSHIP_VIEW}, "the membership view, no email or time zone"
    assert {k: stored[k] for k in stored if k != "memberships"} == {k: before[k] for k in before if k != "memberships"}
    assert rig.version_of("persons", PRIYA) == version + 1


def test_PPL_11c_s3_PE_02_adding_a_team_twice_is_the_same_answer_and_a_ninth_team_is_refused(people_rig):
    rig = _org_owner_rig(people_rig)
    assert _team(rig, PRIYA, "tm_ops").status_code == 200
    version = rig.version_of("persons", PRIYA)
    again = _team(rig, PRIYA, "tm_ops")
    assert again.status_code == 200 and rig.version_of("persons", PRIYA) == version, "idempotent: no new version"
    assert [m["team"] for m in rig.stored("persons", PRIYA)["memberships"]].count("tm_ops") == 1
    for n in range(2, 8):
        assert _team(rig, PRIYA, f"tm_extra{n}").status_code == 200
    snapshot = rig.snapshot()
    ninth = _team(rig, PRIYA, "tm_one_too_many")
    assert ninth.status_code == 409 and "schema" in ninth.json()["problems"], ninth.text[:200]
    assert rig.snapshot() == snapshot


def test_PPL_11c_s3_PE_17_an_org_owner_may_put_themselves_in_a_team_a_member_may_not_put_anyone(people_rig):
    rig = _org_owner_rig(people_rig)
    assert _team(rig, OWNER, "tm_ops").status_code == 200
    rig.as_user(PRIYA)
    before = rig.snapshot()
    seen = [_team(rig, i) for i in (PRIYA, SAM, OWNER, UNIQUE_ID.replace("wi_", "u_"), "bad_id")]
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1, "a member cannot add themselves"
    assert rig.snapshot() == before


def test_PPL_11c_s3_PE_17_everyone_but_an_org_owner_gets_the_one_404_on_every_directory_change(people_rig):
    rig = _org_owner_rig(people_rig)
    rig.add("persons", pl.person(id="u_elsewhere", org_id=OTHER_ORG, email="e@example.org"))
    before = rig.snapshot()
    rig.require_route(R_ROLE)
    seen = []
    for actor in (PRIYA, DEV, SAM, "u_ghost"):
        rig.as_user(actor)
        for target in (PRIYA, SAM, OWNER, "u_elsewhere", "u_nobody_here", "bad_id"):
            seen.append(_team(rig, target))
            seen.append(_unteam(rig, target))
            seen.append(rig.client.post(path_of(R_ROLE, person_id=target), json={"org_role": "owner"}))
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1
    assert rig.snapshot() == before


def test_PPL_11c_s3_PE_02_an_org_owner_removes_a_membership_and_removing_an_absent_one_changes_nothing(people_rig):
    rig = _org_owner_rig(people_rig)
    response = _unteam(rig, PRIYA, "tm_launch")
    assert response.status_code == 200 and response.json()["memberships"] == [], response.text[:200]
    assert rig.stored("persons", PRIYA)["memberships"] == []
    version = rig.version_of("persons", PRIYA)
    again = _unteam(rig, PRIYA, "tm_launch")
    assert again.status_code == 200 and rig.version_of("persons", PRIYA) == version


@pytest.mark.parametrize(
    "extra",
    [
        {"assigned_by": {"by": SAM, "at": NOW}},
        {"org_role": "owner"},
        {"memberships": []},
        {"id": SAM},
        {"email": "x@example.com"},
    ],
    ids=lambda e: next(iter(e)),
)  # fmt: skip
def test_PPL_11c_s3_PE_19_a_membership_body_names_a_team_and_nothing_else(people_rig, extra):
    rig = _org_owner_rig(people_rig)
    before = rig.snapshot()
    assert _team(rig, PRIYA, "tm_ops", **extra).status_code == 422
    assert _unteam(rig, PRIYA, "tm_launch", **extra).status_code == 422
    for team in ("tm_Ops", "ops", "", "tm_" + "x" * 60, 7, None):
        assert rig.client.post(path_of(R_TEAM_ADD, person_id=PRIYA), json={"team": team}).status_code == 422, team
    assert rig.client.post(path_of(R_TEAM_ADD, person_id=PRIYA), json={}).status_code == 422
    assert rig.snapshot() == before


def test_PPL_11c_s3_PE_02_a_new_membership_makes_two_people_teammates(people_rig):
    """The effect is real: u_sam (tm_ops) and u_priya (tm_launch) become teammates once an org owner puts u_priya in
    tm_ops, so each is a directory name to the other (here: a quote speaker for a teammate, PE-24)."""
    rig = _org_owner_rig(people_rig)
    from tilo_people.directory import Directory  # noqa: PLC0415

    directory = Directory.of(s.record for s in rig.real.persons.list(rig.org))
    assert not directory.teammates(PRIYA, SAM, NOW)
    assert _team(rig, PRIYA, "tm_ops").status_code == 200
    directory = Directory.of(s.record for s in rig.real.persons.list(rig.org))
    assert directory.teammates(PRIYA, SAM, NOW)


# --- roles (PE-17: only ever promoted) ------------------------------------------------------------------------------


def _role(rig, person_id: str, org_role="owner", **body):
    rig.require_route(R_ROLE)
    return rig.client.post(path_of(R_ROLE, person_id=person_id), json={"org_role": org_role, **body})


def test_PPL_11c_s3_PE_17_an_org_owner_promotes_a_member_and_the_new_owner_can_then_create_people(people_rig):
    rig = _org_owner_rig(people_rig)
    response = _role(rig, PRIYA)
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("persons", PRIYA)
    assert stored["org_role"] == "owner" and conforms("person.schema.json", stored)
    assert response.json() == {k: stored[k] for k in MEMBERSHIP_VIEW}
    rig.as_user(PRIYA)
    assert rig.post("/v1/people", _person()).status_code == 201, "a promoted owner creates people (PE-17)"


def test_PPL_11c_s3_PE_17_roles_are_only_ever_promoted_and_a_member_cannot_promote_themselves(people_rig):
    rig = _org_owner_rig(people_rig)
    before = rig.snapshot()
    for target, role in ((OWNER, "owner"), (MEERA, "owner"), (PRIYA, "member"), (OWNER, "member")):
        refused = _role(rig, target, role)
        assert refused.status_code == 409 and "transition" in refused.json()["problems"], (
            target,
            role,
            refused.text[:200],
        )
    assert rig.snapshot() == before
    rig.as_user(PRIYA)
    assert _role(rig, PRIYA).status_code == 404, "no one promotes themselves"
    assert rig.snapshot() == before


@pytest.mark.parametrize(
    "body",
    [{"org_role": "admin"}, {"org_role": ""}, {"org_role": None}, {"org_role": "owner", "id": SAM},
     {"org_role": "owner", "memberships": []},
     {"org_role": "owner", "created_by": {"by": SAM, "at": NOW}},
     {},
     [],
     "owner"],
    ids=lambda b: str(b)[:40],
)  # fmt: skip
def test_PPL_11c_s3_PE_19_a_role_body_is_one_closed_field(people_rig, body):
    rig = _org_owner_rig(people_rig)
    rig.require_route(R_ROLE)
    before = rig.snapshot()
    assert rig.client.post(path_of(R_ROLE, person_id=PRIYA), json=body).status_code == 422
    assert rig.snapshot() == before


@pytest.mark.parametrize("which", ["team_add", "team_remove", "role"])
def test_PPL_11c_s3_PE_19_a_lost_compare_and_set_is_a_409_after_one_attempt(people_rig, which):
    rig = _org_owner_rig(people_rig)
    before = rig.snapshot()
    rig.conflicting_stores("persons")
    response = {
        "team_add": lambda: _team(rig, PRIYA, "tm_ops"),
        "team_remove": lambda: _unteam(rig, PRIYA, "tm_launch"),
        "role": lambda: _role(rig, PRIYA),
    }[which]()
    assert response.status_code == 409 and response.json()["code"] == "version_conflict", response.text[:200]
    assert [c for c in rig.store_calls if c[:2] == ("person", "replace")] == [("person", "replace", rig.org)]
    assert rig.snapshot() == before


def test_PPL_11c_s3_SEC_15_the_directory_routes_are_gated_and_fail_closed(people_rig):
    routes = [R_PERSON_FIRST, R_TEAM_ADD, R_TEAM_REMOVE, R_ROLE]
    assert_gated(people_rig, routes)
    assert_unwired_is_503(people_rig, routes, "people_stores")
