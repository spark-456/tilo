"""SELF-SERVE-TEAMS (ADR-0044; people.rules.md "Terms", PE-17, PE-20, PE-37): anyone who signs in joins the org, and any
member can create a team, lead it and invite others. `/v1/people/first` lets a full, non-demo web sign-in join as a
member before or after founding; the bootstrap uid still founds as owner. `/v1/teams` routes create, invite (by
email, one answer), accept, remove and read the roster, each decided from the session and the whole stored org.
"""

from __future__ import annotations

import json

import pytest
from _ppl11c_lib import PERSON_BODY
from tilo_people.directory import Directory
from tilo_people.world_share import reader_share, share_id

ENV_UID = "TILO_PEOPLE_BOOTSTRAP_UID"
FOUNDER = "u_founder"
FORBIDDEN = {"detail": "forbidden"}
NOW = "2026-10-15T09:00:00.000Z"


def _rig(people_rig, monkeypatch):
    for name in (ENV_UID, "TILO_PEOPLE_STORE", "TILO_FIRESTORE_PROJECT", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    rig = people_rig()
    rig.unwire("founder_gate")
    monkeypatch.setenv(ENV_UID, FOUNDER)
    rig.set_now(NOW)
    return rig


def _join(rig, uid: str, **body):
    rig.as_user(uid)
    name = uid[2:].capitalize()
    rig.email = body.get("email", f"{uid[2:]}@example.com")  # the sign-in's verified address
    return rig.client.post(
        "/v1/people/first",
        json={**PERSON_BODY, "display_name": name, "aliases": [name], "email": f"{uid[2:]}@example.com", **body},
    )


def _tick(rig, minutes: int) -> None:
    rig.set_now(f"2026-10-15T09:{minutes:02d}:00.000Z")


def _team(rig, uid: str) -> str:
    rig.as_user(uid)
    made = rig.post("/v1/teams", {})
    assert made.status_code == 201, made.text[:300]
    assert made.json()["lead"] is True
    return made.json()["team"]


def _roster(rig, uid: str, team: str):
    rig.as_user(uid)
    return rig.client.get(f"/v1/teams/{team}")


def _invite(rig, uid: str, team: str, email: str):
    rig.as_user(uid)
    return rig.post(f"/v1/teams/{team}/invites", {"email": email})


# --- self-join (PE-17) --------------------------------------------------------------------------------------------


def test_SELF_SERVE_TEAMS_a_member_joins_before_founding_and_the_owner_founds_later(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    joined = _join(rig, "u_mia")
    assert joined.status_code == 201, joined.text[:300]
    assert joined.json()["org_role"] == "member" and joined.json()["memberships"] == []
    assert rig.real.persons.founded(rig.org) is False
    founded = _join(rig, FOUNDER)
    assert founded.status_code == 201, founded.text[:300]
    assert founded.json()["org_role"] == "owner"
    assert rig.real.persons.founded(rig.org) is True
    assert rig.stored("persons", "u_mia")["org_role"] == "member", "nobody else becomes owner"
    late = _join(rig, "u_ben")
    assert late.status_code == 201 and late.json()["org_role"] == "member"


def test_SELF_SERVE_TEAMS_a_second_call_is_idempotent_one_record_per_uid(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    assert _join(rig, "u_mia").status_code == 201
    version = rig.version_of("persons", "u_mia")
    again = _join(rig, "u_mia", display_name="Someone Else", email="else@example.com")
    assert again.status_code == 200 and again.json()["id"] == "u_mia" and again.json()["org_role"] == "member"
    assert rig.version_of("persons", "u_mia") == version
    assert rig.stored("persons", "u_mia")["email"] == "mia@example.com"
    assert _join(rig, FOUNDER).status_code == 201
    assert _join(rig, FOUNDER).status_code == 200
    assert [s.record["id"] for s in rig.real.persons.list(rig.org)].count(FOUNDER) == 1


@pytest.mark.parametrize(
    ("channel", "full", "demo"),
    [("web", True, True), ("web", False, False), ("email", True, False), ("whatsapp", True, False)],
)
def test_SELF_SERVE_TEAMS_a_demo_or_partial_session_is_refused(people_rig, monkeypatch, channel, full, demo):
    rig = _rig(people_rig, monkeypatch)
    rig.as_user("u_mia")
    rig.channel, rig.full_session = channel, full
    principal = rig._principal

    def with_demo():
        return rig.deps.Principal(**{**principal().__dict__, "demo_session": demo})

    rig.app.dependency_overrides[rig.deps.get_current_principal] = with_demo
    before = rig.snapshot()
    refused = rig.client.post("/v1/people/first", json=PERSON_BODY)
    assert refused.status_code == 403 and refused.json() == FORBIDDEN
    made = rig.post("/v1/teams", {})
    assert made.status_code in (403, 404)
    assert rig.snapshot() == before


def test_SELF_SERVE_TEAMS_the_role_never_comes_from_the_body(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    smuggled = _join(rig, "u_mia", org_role="owner")
    assert smuggled.status_code == 422
    assert rig.stored("persons", "u_mia") is None


# --- teams (PE-37) ------------------------------------------------------------------------------------------------


def _three(rig) -> str:
    """Founder founds; Mia and Ben join; Mia creates a team and is its lead."""
    for uid in (FOUNDER, "u_mia", "u_ben", "u_cara"):
        assert _join(rig, uid).status_code == 201
    _tick(rig, 1)
    return _team(rig, "u_mia")


def test_SELF_SERVE_TEAMS_a_member_creates_a_team_and_becomes_its_lead(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    team = _three(rig)
    assert team.startswith("tm_") and len(team) == 3 + 24
    entry = rig.stored("persons", "u_mia")["memberships"][0]
    assert entry == {"team": team, "lead": True, "assigned_by": {"by": "u_mia", "at": "2026-10-15T09:01:00.000Z"}}
    roster = _roster(rig, "u_mia", team)
    assert roster.status_code == 200
    assert roster.json()["members"] == [{"id": "u_mia", "display_name": "Mia", "lead": True}]
    rig.as_user("u_mia")
    mine = rig.client.get("/v1/teams").json()["teams"]
    assert mine == [{"team": team, "lead": True, "state": "member"}]


def test_SELF_SERVE_TEAMS_a_lead_invites_the_invitee_accepts_and_reads_the_roster(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    team = _three(rig)
    _tick(rig, 2)
    invited = _invite(rig, "u_mia", team, "BEN@example.com")
    assert invited.status_code == 200 and invited.json() == {"status": "invited"}
    assert [m["id"] for m in _roster(rig, "u_mia", team).json()["members"]] == ["u_mia"], "pending shows nothing"
    assert _roster(rig, "u_ben", team).status_code == 404, "a pending invitation reads no roster"
    rig.as_user("u_ben")
    pending = rig.client.get("/v1/teams").json()["teams"]
    assert pending == [
        {"team": team, "lead": False, "state": "pending", "invited_by": {"id": "u_mia", "display_name": "Mia"}}
    ]
    _tick(rig, 3)
    accepted = rig.post(f"/v1/teams/{team}/accept", {})
    assert accepted.status_code == 200, accepted.text[:300]
    assert rig.stored("persons", "u_ben")["memberships"][0]["accepted_at"] == "2026-10-15T09:03:00.000Z"
    names = [(m["id"], m["lead"]) for m in _roster(rig, "u_ben", team).json()["members"]]
    assert names == [("u_mia", True), ("u_ben", False)]


def test_SELF_SERVE_TEAMS_an_invitation_has_one_answer_whatever_the_address(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    team = _three(rig)
    _tick(rig, 2)
    answers = {
        _invite(rig, "u_mia", team, email).text
        for email in ("ben@example.com", "ben@example.com", "nobody@example.com", "mia@example.com")
    }
    assert answers == {json.dumps({"status": "invited"}, separators=(",", ":"))}
    assert len(rig.stored("persons", "u_ben")["memberships"]) == 1, "invited once"


def test_SELF_SERVE_TEAMS_only_the_invited_person_accepts(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    team = _three(rig)
    _tick(rig, 2)
    _invite(rig, "u_mia", team, "ben@example.com")
    rig.as_user("u_mia")
    before = rig.snapshot()
    assert rig.post(f"/v1/teams/{team}/accept", {}).status_code == 404, "the lead cannot accept for Ben"
    rig.as_user("u_cara")
    assert rig.post(f"/v1/teams/{team}/accept", {}).status_code == 404
    assert rig.snapshot() == before


def test_SELF_SERVE_TEAMS_a_lead_acts_on_their_own_team_only(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    mine = _three(rig)
    other = _team(rig, "u_cara")
    _tick(rig, 2)
    before = rig.snapshot()
    assert _invite(rig, "u_mia", other, "ben@example.com").json() == FORBIDDEN
    assert rig.post(f"/v1/teams/{other}/members/u_cara/remove", {}).json() == FORBIDDEN
    assert _invite(rig, "u_ben", mine, "cara@example.com").status_code == 403, "a plain member invites nobody"
    assert rig.snapshot() == before
    assert _roster(rig, "u_mia", other).status_code == 404


def test_SELF_SERVE_TEAMS_a_lead_is_refused_org_roles_people_and_team_settings(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    _three(rig)
    rig.as_user("u_mia")
    before = rig.snapshot()
    assert rig.post("/v1/people/u_ben/role", {"org_role": "owner"}).status_code == 404
    assert rig.post("/v1/people", {**PERSON_BODY, "email": "new@example.com"}).status_code == 403
    assert rig.post("/v1/people/u_ben/memberships", {"team": "tm_sales"}).status_code == 404
    assert rig.snapshot() == before
    assert rig.stored("persons", "u_mia")["org_role"] == "member"


def test_SELF_SERVE_TEAMS_a_lead_removes_a_member_and_a_member_leaves(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    team = _three(rig)
    _tick(rig, 2)
    _invite(rig, "u_mia", team, "ben@example.com")
    _invite(rig, "u_mia", team, "cara@example.com")
    for uid in ("u_ben", "u_cara"):
        rig.as_user(uid)
        assert rig.post(f"/v1/teams/{team}/accept", {}).status_code == 200
    rig.as_user("u_ben")
    assert rig.post(f"/v1/teams/{team}/members/u_mia/remove", {}).status_code == 403, "not another's lead entry"
    assert rig.post(f"/v1/teams/{team}/members/u_cara/remove", {}).status_code == 403, "a member removes nobody"
    assert rig.post(f"/v1/teams/{team}/members/u_ben/remove", {}).status_code == 200, "a member leaves"
    rig.as_user("u_mia")
    assert rig.post(f"/v1/teams/{team}/members/u_cara/remove", {}).status_code == 200
    assert [m["id"] for m in _roster(rig, "u_mia", team).json()["members"]] == ["u_mia"]


def test_SELF_SERVE_TEAMS_PE_31_a_shared_world_reaches_accepted_members_only(people_rig, monkeypatch):
    """The team visibility rule holds for a self-serve team: Mia's share of her world is in force, and makes Ben a
    reader once he accepted, never Cara (outside) or a pending invitee."""
    rig = _rig(people_rig, monkeypatch)
    team = _three(rig)
    _tick(rig, 2)
    _invite(rig, "u_mia", team, "ben@example.com")
    _invite(rig, "u_mia", team, "cara@example.com")
    _tick(rig, 3)
    rig.as_user("u_ben")
    assert rig.post(f"/v1/teams/{team}/accept", {}).status_code == 200
    world = "w_mia_world"
    share = {
        "id": share_id(world, team),
        "org_id": rig.org,
        "world_id": world,
        "team": team,
        "granted_by": {"by": "u_mia", "at": "2026-10-15T09:04:00.000Z"},
        "revoked": None,
    }
    now = "2026-10-15T09:05:00.000Z"
    d = Directory.of(s.record for s in rig.real.persons.list(rig.org))
    assert reader_share([share], world, "u_mia", d, "u_ben", now) is not None
    assert reader_share([share], world, "u_mia", d, "u_cara", now) is None, "a pending invitation reads nothing"
    assert reader_share([share], world, "u_mia", d, FOUNDER, now) is None, "the org owner is not in the team"
