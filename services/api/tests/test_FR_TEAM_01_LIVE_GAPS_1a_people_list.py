"""LIVE-GAPS-1a (FR-TEAM-01, PE-20, PE-17, PE-26): `GET /v1/people`, the signed-in person's team list.

PRD / contract sources: PRD supplement FR-TEAM-01 (the team screen lists the people of the caller's team); contracts/
people.rules.md PE-20 (a person reads their own record in full; teammates read the directory view only, id and display
name; org owners also read `org_role` and `memberships`; email, aliases, time zone and preferred channel never leave
`tilo-api` except to the person; a person outside the team reads nothing, not even a display name, except through a
team they share), PE-17 (the org owner and the memberships an owner assigned), PE-26 (the caller is the principal and
nothing in the request names another person or org), PE-22 (no-store).

Pinned interface (the ticket's decided spec):

    GET /v1/people          auth `deps.get_current_principal`; org `deps.ORG_ID`; stores `deps.get_people_stores`
    200 {"people": [...], "you": "<caller person id>"}   (top-level keys are exactly these two)
        people   the org's persons the caller may read, through the PE-20 projection (`tilo_people.access`), sorted by
                 (display_name, id)
                 * the caller's own record: the stored record in full (every person-schema key);
                 * an org owner reading another person: {id, display_name, org_role, memberships} (never email,
                   aliases, time_zone, preferred_channel, org_id, created_by); an owner reads every person of the org;
                 * a member reading a teammate (a team both belong to, memberships assigned by an owner at or before
                   now): {id, display_name} only; a person who shares no team is absent.
        you      the caller's person id (`Principal.user_id`)
    404 {"detail": "not_found"}      the caller has no person record in the org (the other routes' one body)
    503 {"detail": "not_configured"} the people stores are unwired, or the store raises NotImplementedError
    503 {"detail": "unavailable"}    the store raises anything else (the cause is never in the body or the headers)
    Every answer, refusals included, carries `Cache-Control: no-store`. No query parameter selects another person or
    org (ignored). A person of another org never appears. GET writes nothing (no store write, no event, no model).

Ambiguities resolved (listed in the report):
* "lists the org's persons ... through the existing PE-20 projection": a member sees only themselves and their
  teammates (PE-20: "a person outside the team reads nothing, not even a display name"); an org owner sees the whole
  org (people.rules.md `_person` oracle: read_directory is allowed to an org owner). The oracle decides, not the test.
* A demo (anonymous) session and the session's world role neither grant nor take away anything: like `/v1/plate`, the
  caller is the principal's `user_id` and the answer rests on the person record alone (PPL-11a module doc).
* The stable order is plain code-point order of display_name, then id; the test names are ASCII with distinct first
  letters, so the collation question does not arise.

No network, no model, no cloud credentials. Planted email addresses, aliases and zones are assembled at runtime.
"""

from __future__ import annotations

import copy
import json
import secrets
from typing import Any

import pytest
from _ppl11a_lib import (
    DEV,
    MEERA,
    NOW,
    ORG,
    OTHER_ORG,
    OWNER,
    PRIYA,
    SAM,
    STANDARD_PERSONS,
    Rig,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

PATH = "/v1/people"
ROUTE = ("GET", PATH)
TOP_KEYS = {"people", "you"}
DIRECTORY_KEYS = {"id", "display_name"}
OWNER_VIEW_KEYS = {"id", "display_name", "org_role", "memberships"}
PERSON_KEYS = {
    "id",
    "org_id",
    "display_name",
    "aliases",
    "email",
    "time_zone",
    "preferred_channel",
    "org_role",
    "memberships",
    "created_by",
}
NEVER_OTHERS = ("email", "aliases", "time_zone", "preferred_channel", "org_id", "created_by")
ZONES = ["Pacific/Auckland", "Europe/Lisbon", "America/Lima", "Asia/Tokyo", "Africa/Nairobi"]
EARLY = "2026-10-05T09:00:00.000Z"  # before NOW, the rig's clock
NO_STORE = "no-store"


def _tok() -> str:
    """A runtime-assembled marker: nothing secret-looking is committed."""
    return secrets.token_hex(6)


def _planted(persons: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The standard people with a unique email, alias, zone and channel each, so a leak is findable by text scan."""
    out = copy.deepcopy(persons)
    for index, (uid, person) in enumerate(sorted(out.items())):
        token = _tok()
        person["email"] = f"{uid}.{token}@example.com"
        person["aliases"] = [f"Nick{token}"]
        person["time_zone"] = ZONES[index % len(ZONES)]
        person["preferred_channel"] = "email"
    return out


@pytest.fixture()
def rig(people_rig):
    r = people_rig()
    yield r
    r.close()


def _seed(rig: Rig, persons: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    planted = _planted(persons if persons is not None else STANDARD_PERSONS)
    rig.add_people(planted.values())
    return planted


def _list(rig: Rig, user: str, **kwargs: Any) -> Any:
    rig.require_route(ROUTE)
    rig.as_user(user)
    return rig.get(PATH, **kwargs)


def _by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in body["people"]}


def _foreign_markers(planted: dict[str, dict[str, Any]], caller: str) -> list[str]:
    """Every planted string of a person other than the caller: none may appear in the caller's answer."""
    marks: list[str] = []
    for uid, p in planted.items():
        if uid != caller:
            marks += [p["email"], *p["aliases"], p["time_zone"]]
    return marks


def _person(
    uid: str, name: str, *, org: str = ORG, role: str = "member", teams: tuple[str, ...] = ()
) -> dict[str, Any]:
    token = _tok()
    return {
        "id": uid,
        "org_id": org,
        "display_name": name,
        "aliases": [f"Nick{token}"],
        "email": f"{uid}.{token}@example.com",
        "time_zone": "Pacific/Auckland",
        "preferred_channel": "email",
        "org_role": role,
        "memberships": [{"team": t, "assigned_by": {"by": OWNER, "at": EARLY}} for t in teams],
        "created_by": {"by": OWNER, "at": EARLY},
    }


# --- the views ------------------------------------------------------------------------------------------------------


def test_FR_TEAM_01_LIVE_GAPS_1a_owner_sees_every_person_of_the_org_with_role_and_memberships(rig):
    planted = _seed(rig)
    r = _list(rig, OWNER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == TOP_KEYS
    assert body["you"] == OWNER
    people = _by_id(body)
    assert set(people) == set(STANDARD_PERSONS), "an org owner reads every person of the org (PE-20)"
    for uid, row in people.items():
        if uid == OWNER:
            continue
        assert set(row) == OWNER_VIEW_KEYS, (uid, sorted(row))
        assert row["display_name"] == planted[uid]["display_name"]
        assert row["org_role"] == planted[uid]["org_role"]
        assert row["memberships"] == planted[uid]["memberships"]


def test_FR_TEAM_01_LIVE_GAPS_1a_a_second_owner_gets_the_same_owner_view(rig):
    _seed(rig)
    r = _list(rig, MEERA)
    assert r.status_code == 200, r.text
    people = _by_id(r.json())
    assert set(people) == set(STANDARD_PERSONS)
    assert set(people[OWNER]) == OWNER_VIEW_KEYS and set(people[SAM]) == OWNER_VIEW_KEYS
    assert set(people[MEERA]) == PERSON_KEYS


def test_FR_TEAM_01_LIVE_GAPS_1a_member_sees_teammates_by_id_and_display_name_only(rig):
    planted = _seed(rig)
    r = _list(rig, PRIYA)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["you"] == PRIYA
    people = _by_id(body)
    assert set(people) == {OWNER, PRIYA, DEV}, (
        "Priya shares tm_launch with Asha (owner) and Dev; Sam and Meera are tm_ops"
    )
    for uid in (OWNER, DEV):
        assert set(people[uid]) == DIRECTORY_KEYS, (uid, sorted(people[uid]))
        assert people[uid]["display_name"] == planted[uid]["display_name"]


def test_FR_TEAM_01_LIVE_GAPS_1a_PE_20_a_person_outside_every_shared_team_is_absent_for_a_member(rig):
    planted = _seed(rig)
    r = _list(rig, SAM)  # tm_ops: shares it with Meera only
    assert r.status_code == 200, r.text
    people = _by_id(r.json())
    assert set(people) == {SAM, MEERA}
    assert set(people[MEERA]) == DIRECTORY_KEYS
    for hidden in (OWNER, PRIYA, DEV):
        assert hidden not in people
        assert planted[hidden]["display_name"] not in r.text, "not even a display name (PE-20)"


def test_FR_TEAM_01_LIVE_GAPS_1a_PE_20_a_member_with_no_team_sees_only_their_own_record(rig):
    _seed(rig)
    loner = _person("u_loner", "Lena Loner")
    rig.add("persons", loner)
    r = _list(rig, "u_loner")
    assert r.status_code == 200, r.text
    assert r.json() == {"people": [loner], "you": "u_loner"}


def test_FR_TEAM_01_LIVE_GAPS_1a_PE_20_own_record_is_returned_in_full_for_member_and_owner(rig):
    planted = _seed(rig)
    for uid in (PRIYA, OWNER):
        r = _list(rig, uid)
        assert r.status_code == 200, r.text
        own = _by_id(r.json())[uid]
        assert set(own) == PERSON_KEYS
        assert own == planted[uid], "the caller's own record is the stored record, every field"


# --- PE-20 redaction ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("caller", [OWNER, MEERA, PRIYA, DEV, SAM])
def test_FR_TEAM_01_LIVE_GAPS_1a_PE_20_other_peoples_contact_details_never_leave_the_api(rig, caller):
    planted = _seed(rig)
    r = _list(rig, caller)
    assert r.status_code == 200, r.text
    people = _by_id(r.json())
    for uid, row in people.items():
        if uid == caller:
            continue
        for key in NEVER_OTHERS:
            assert key not in row, f"{key} of {uid} leaked to {caller}"
    for mark in _foreign_markers(planted, caller):
        assert mark not in r.text, f"a planted value of another person is in the answer for {caller}: {mark[:12]}"
    assert "@" not in json.dumps([row for uid, row in people.items() if uid != caller]), "no address-shaped text"


def test_FR_TEAM_01_LIVE_GAPS_1a_PE_20_an_org_owner_never_gets_email_aliases_zone_or_channel_of_others(rig):
    planted = _seed(rig)
    r = _list(rig, OWNER)
    assert r.status_code == 200, r.text
    for mark in _foreign_markers(planted, OWNER):
        assert mark not in r.text
    for uid, row in _by_id(r.json()).items():
        if uid != OWNER:
            assert not ({"email", "aliases", "time_zone", "preferred_channel"} & set(row))
    assert not [k for k in r.headers if k.lower().startswith("x-") and "@" in r.headers[k]]


# --- the org -------------------------------------------------------------------------------------------------------


def test_FR_TEAM_01_LIVE_GAPS_1a_a_person_of_another_org_never_appears_even_with_the_same_id(rig):
    _seed(rig)
    elsewhere = [
        _person("u_zed", "Zed Elsewhere", org=OTHER_ORG, role="owner", teams=("tm_launch",)),
        _person(OWNER, "Eve Elsewhere", org=OTHER_ORG, role="owner", teams=("tm_launch",)),
    ]
    for p in elsewhere:
        p["created_by"] = {"by": OWNER, "at": EARLY}
        rig.add("persons", p)
    for user in (OWNER, PRIYA):
        r = _list(rig, user)
        assert r.status_code == 200, r.text
        assert "u_zed" not in _by_id(r.json())
        assert "Elsewhere" not in r.text
        assert all(row["id"] != OWNER or row["display_name"] != "Eve Elsewhere" for row in r.json()["people"])
        for p in elsewhere:
            assert p["email"] not in r.text


def test_FR_TEAM_01_LIVE_GAPS_1a_the_other_orgs_owner_with_a_record_only_there_is_a_404_here(rig):
    _seed(rig)
    rig.add("persons", _person("u_visitor", "Vera Visitor", org=OTHER_ORG, role="owner"))
    r = _list(rig, "u_visitor")
    assert r.status_code == 404
    assert r.json() == {"detail": "not_found"}
    assert "Asha" not in r.text


def test_FR_TEAM_01_LIVE_GAPS_1a_no_query_parameter_selects_another_person_or_org(rig):
    _seed(rig)
    probes = {
        "org_id": OTHER_ORG,
        "org": OTHER_ORG,
        "user": SAM,
        "user_id": MEERA,
        "person": SAM,
        "id": SAM,
        "as": SAM,
        "team": "tm_ops",
        "limit": "1",
    }
    for caller in (OWNER, PRIYA):
        plain = _list(rig, caller)
        assert plain.status_code == 200, plain.text
        probed = _list(rig, caller, params=probes)
        assert probed.status_code == 200, probed.text
        assert probed.json() == plain.json(), "a query parameter must change nothing"


# --- order ----------------------------------------------------------------------------------------------------------


def test_FR_TEAM_01_LIVE_GAPS_1a_people_are_ordered_by_display_name_then_id_whatever_the_insertion_order(rig):
    rig.add("persons", _person(OWNER, "Mara Owner", role="owner", teams=("tm_a",)))
    extra = [
        _person("u_z9", "Abe Aardvark", teams=("tm_a",)),
        _person("u_b1", "Zed Zero", teams=("tm_a",)),
        _person("u_a1", "Zed Zero", teams=("tm_a",)),
        _person("u_m5", "Mara Owner", teams=("tm_a",)),  # same name as the owner, a later id
        _person("u_c3", "Cleo Cole", teams=("tm_a",)),
    ]
    for p in reversed(extra):
        rig.add("persons", p)
    r = _list(rig, OWNER)
    assert r.status_code == 200, r.text
    rows = [(p["display_name"], p["id"]) for p in r.json()["people"]]
    assert rows == sorted(rows), rows
    assert [i for _, i in rows] == [
        "u_z9",
        "u_c3",
        "u_m5",
        OWNER,
        "u_a1",
        "u_b1",
    ]  # same name: by id, "u_m5" < "u_owner"
    again = _list(rig, OWNER)
    assert again.json() == r.json(), "a stable answer"


# --- the caller -----------------------------------------------------------------------------------------------------


def test_FR_TEAM_01_LIVE_GAPS_1a_a_caller_with_no_person_record_gets_the_one_not_found_body(rig):
    _seed(rig)
    r = _list(rig, "u_nobody")
    assert r.status_code == 404
    assert r.json() == {"detail": "not_found"}
    assert r.headers["cache-control"] == NO_STORE
    for p in STANDARD_PERSONS.values():
        assert p["display_name"] not in r.text


def test_FR_TEAM_01_LIVE_GAPS_1a_an_unsigned_request_is_refused_and_lists_nobody(rig):
    planted = _seed(rig)
    rig.require_route(ROUTE)
    rig.sign_out()
    r = rig.get(PATH)
    assert r.status_code == 401
    for p in planted.values():
        assert p["display_name"] not in r.text


def test_FR_TEAM_01_LIVE_GAPS_1a_demo_and_world_role_neither_grant_nor_take_away(rig):
    from tilo_api import deps

    _seed(rig)
    rig.require_route(ROUTE)
    normal = _list(rig, PRIYA)
    assert normal.status_code == 200
    for role, demo in (("viewer", True), ("owner", True), ("viewer", False), ("team_lead", False)):
        rig.app.dependency_overrides[deps.get_current_principal] = lambda r=role, d=demo: deps.Principal(
            user_id=PRIYA, role=r, demo_session=d
        )
        r = rig.get(PATH)
        assert r.status_code == 200, (role, demo, r.text)
        assert r.json() == normal.json(), "the answer rests on the person record, not on the session's role"
    # an anonymous demo uid has no person record: the one 404, nothing listed
    rig.app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id="u_anon_" + _tok(), role="viewer", demo_session=True
    )
    r = rig.get(PATH)
    assert r.status_code == 404 and r.json() == {"detail": "not_found"}


# --- headers, unwired and failing stores -----------------------------------------------------------------------------


def test_FR_TEAM_01_LIVE_GAPS_1a_PE_22_every_answer_is_no_store(rig):
    _seed(rig)
    answered = [_list(rig, OWNER), _list(rig, PRIYA), _list(rig, "u_nobody")]
    assert [r.status_code for r in answered] == [200, 200, 404]
    rig.unwire("people_stores")
    answered.append(_list(rig, OWNER))
    for r in answered:
        assert r.headers["cache-control"] == NO_STORE, r.status_code


def test_FR_TEAM_01_LIVE_GAPS_1a_unwired_people_store_is_503_not_configured(rig):
    _seed(rig)
    rig.require_route(ROUTE)
    rig.unwire("people_stores")
    rig.as_user(OWNER)
    r = rig.get(PATH)
    assert r.status_code == 503
    assert r.json() == {"detail": "not_configured"}
    assert r.headers["cache-control"] == NO_STORE


def test_FR_TEAM_01_LIVE_GAPS_1a_a_store_that_is_not_implemented_is_503_not_configured(rig):
    _seed(rig)
    rig.require_route(ROUTE)

    def not_built(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("no firestore here")

    rig.stores.persons.list = not_built
    rig.as_user(OWNER)
    r = rig.get(PATH)
    assert r.status_code == 503
    assert r.json() == {"detail": "not_configured"}
    assert "firestore" not in r.text


def test_FR_TEAM_01_LIVE_GAPS_1a_a_failing_store_is_503_unavailable_without_the_cause(rig):
    _seed(rig)
    rig.require_route(ROUTE)
    cause = "boom-" + _tok()

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"store exploded: {cause}")

    rig.stores.persons.list = broken
    rig.as_user(OWNER)
    r = rig.get(PATH)
    assert r.status_code == 503
    assert r.json() == {"detail": "unavailable"}
    assert cause not in r.text and "exploded" not in r.text
    assert cause not in json.dumps(dict(r.headers))
    assert r.headers["cache-control"] == NO_STORE
    assert [p["display_name"] for p in STANDARD_PERSONS.values() if p["display_name"] in r.text] == [], (
        "no partial list"
    )


# --- a read changes nothing -------------------------------------------------------------------------------------------


def test_FR_TEAM_01_LIVE_GAPS_1a_get_mutates_nothing_and_calls_no_model(rig):
    _seed(rig)
    rig.require_route(ROUTE)
    before = rig.snapshot()
    rig.store_calls.clear()
    for user in (OWNER, PRIYA, SAM, "u_nobody"):
        _list(rig, user)
    assert rig.snapshot() == before, "the stores are unchanged"
    writes = [c for c in rig.store_calls if c[1] not in ("get", "list", "founded")]
    assert writes == [], writes
    assert all(c[2] == ORG for c in rig.store_calls), "only the org's rows are read"
    assert rig.router_calls == [], "a people read builds no model router"
    assert not rig.events.events if hasattr(rig.events, "events") else True


# --- the property ---------------------------------------------------------------------------------------------------

_NAMES = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij ", min_size=1, max_size=14).filter(
    lambda s: s.strip() == s and s
)


@st.composite
def _orgs(draw: Any) -> tuple[list[dict[str, Any]], str]:
    count = draw(st.integers(min_value=1, max_value=6))
    teams = ["tm_a", "tm_b", "tm_c"]
    persons: list[dict[str, Any]] = []
    for i in range(count):
        token = f"{i}{draw(st.integers(min_value=0, max_value=10**6))}"
        uid = "u_o0" if i == 0 else f"u_p{token}"
        chosen = draw(st.lists(st.sampled_from(teams), unique=True, max_size=3))
        persons.append(
            {
                "id": uid,
                "org_id": ORG,
                "display_name": draw(_NAMES),
                "aliases": draw(st.lists(st.just(f"Alias{token}"), max_size=1)),
                "email": f"em{token}.{secrets.token_hex(4)}@example.com",
                "time_zone": draw(st.sampled_from(ZONES)),
                "preferred_channel": draw(st.sampled_from(["web", "mobile_web", "email"])),
                "org_role": "owner" if i == 0 else draw(st.sampled_from(["owner", "member"])),
                "memberships": [{"team": t, "assigned_by": {"by": "u_o0", "at": EARLY}} for t in chosen],
                "created_by": {"by": "u_o0", "at": EARLY},
            }
        )
    ids = {p["id"] for p in persons}
    assert len(ids) == len(persons)
    caller = draw(st.sampled_from(sorted(ids)))
    return persons, caller


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_orgs())
def test_FR_TEAM_01_LIVE_GAPS_1a_PE_20_property_no_field_outside_the_allowlist_ever_appears(case):
    persons, caller = case
    with pytest.MonkeyPatch.context() as mp:
        rig = Rig(mp, now=NOW)
        try:
            # names may repeat, emails are unique per person by construction
            for p in persons:
                rig.add("persons", p)
            rig.require_route(ROUTE)
            rig.as_user(caller)
            r = rig.get(PATH)
            assert r.status_code == 200, r.text
            body = r.json()
            assert set(body) == TOP_KEYS and body["you"] == caller
            by_id = {p["id"]: p for p in persons}
            me = by_id[caller]
            listed = [row["id"] for row in body["people"]]
            assert len(listed) == len(set(listed)) and set(listed) <= set(by_id)
            keys_of_me = {m["team"] for m in me["memberships"]}
            allowed_others = OWNER_VIEW_KEYS if me["org_role"] == "owner" else DIRECTORY_KEYS
            for row in body["people"]:
                if row["id"] == caller:
                    assert row == me
                    continue
                assert set(row) <= allowed_others, (me["org_role"], sorted(row))
                assert row["display_name"] == by_id[row["id"]]["display_name"]
                if me["org_role"] != "owner":
                    assert keys_of_me & {m["team"] for m in by_id[row["id"]]["memberships"]}, "a non-teammate listed"
            if me["org_role"] == "owner":
                assert set(listed) == set(by_id)
            ordered = [(row["display_name"], row["id"]) for row in body["people"]]
            assert ordered == sorted(ordered)
            for p in persons:
                if p["id"] != caller:
                    assert p["email"] not in r.text
                    assert not any(a in r.text for a in p["aliases"] if a not in me["aliases"])
        finally:
            rig.close()
