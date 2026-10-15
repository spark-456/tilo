"""SELF-SERVE-TEAMS security review (ADR-0044; PE-17, PE-20, PE-37): the reviewer's probes as tests.

1. A self-join or a founding stores only the sign-in's Google-verified address: nobody claims another person's
   address, so nobody receives their invitations or blocks their founding.
2. A lead's remove answers the same bytes whether the person had a pending entry, no entry or no record.
3. Entries that count for nothing are listed (`lapsed`) so their person can remove them and free the 8 slots.
Plus: a world-bound session cannot join; an invite in the founding millisecond keeps the founder the lead; a world
shared with a self-serve team is read over HTTP by accepted members only.
"""

from __future__ import annotations

from types import SimpleNamespace

from _api_lib import base_event
from _ppl11c_lib import PERSON_BODY
from _tsw1_lib import ASHA, BEN, CARA, DEV, ORGOWNER, WORLD, web
from _tsw1_lib import Rig as WorldRig

ENV_UID = "TILO_PEOPLE_BOOTSTRAP_UID"
FOUNDER = "u_founder"
FORBIDDEN = {"detail": "forbidden"}


def _rig(people_rig, monkeypatch):
    for name in (ENV_UID, "TILO_PEOPLE_STORE", "TILO_FIRESTORE_PROJECT", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    rig = people_rig()
    rig.unwire("founder_gate")
    monkeypatch.setenv(ENV_UID, FOUNDER)
    rig.set_now("2026-10-15T09:00:00.000Z")
    return rig


def _post_first(rig, uid: str, *, token_email: str | None, body_email: str):
    rig.as_user(uid)
    rig.email = token_email
    name = uid[2:].capitalize()
    body = {**PERSON_BODY, "display_name": name, "aliases": [name], "email": body_email}
    return rig.client.post("/v1/people/first", json=body)


def _join(rig, uid: str, email: str | None = None):
    email = email or f"{uid[2:]}@example.com"
    joined = _post_first(rig, uid, token_email=email, body_email=email)
    assert joined.status_code == 201, joined.text[:300]
    return joined


def _tick(rig, minute: int) -> None:
    rig.set_now(f"2026-10-15T09:{minute:02d}:00.000Z")


def _create(rig, uid: str) -> str:
    rig.as_user(uid)
    made = rig.post("/v1/teams", {})
    assert made.status_code == 201, made.text[:300]
    return made.json()["team"]


def _do(rig, uid: str, path: str, body=None):
    rig.as_user(uid)
    return rig.post(path, {} if body is None else body)


# --- 1. only the verified address ---------------------------------------------------------------------------------


def test_SELF_SERVE_TEAMS_a_body_address_other_than_the_verified_one_is_never_claimed(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    _join(rig, FOUNDER)
    _join(rig, "u_mia")
    before = rig.snapshot()
    squat = _post_first(rig, "u_mallory", token_email="mallory@example.com", body_email="alice@example.com")
    assert squat.status_code == 403 and squat.json() == FORBIDDEN
    assert _post_first(rig, "u_mallory", token_email=None, body_email="alice@example.com").json() == FORBIDDEN
    assert rig.snapshot() == before, "nothing stored for a claimed address"
    _join(rig, "u_alice", "Alice@Example.com")  # the real Alice; the case of the token's address is what is stored
    assert rig.stored("persons", "u_alice")["email"] == "Alice@Example.com"
    _join(rig, "u_mallory")
    _tick(rig, 1)
    team = _create(rig, "u_mia")
    _tick(rig, 2)
    _do(rig, "u_mia", f"/v1/teams/{team}/invites", {"email": "alice@example.com"})
    assert [m["team"] for m in rig.stored("persons", "u_alice")["memberships"]] == [team], "the invite reaches Alice"
    assert rig.stored("persons", "u_mallory")["memberships"] == []


def test_SELF_SERVE_TEAMS_nobody_blocks_the_founder_by_taking_their_address(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    squat = _post_first(rig, "u_mallory", token_email="mallory@example.com", body_email="founder@example.com")
    assert squat.status_code == 403
    founded = _post_first(rig, FOUNDER, token_email="founder@example.com", body_email="founder@example.com")
    assert founded.status_code == 201 and founded.json()["org_role"] == "owner"


def test_SELF_SERVE_TEAMS_a_world_bound_session_cannot_join(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    rig.as_user("u_mia", world_id="w_some_world")
    rig.email = "mia@example.com"
    refused = rig.client.post("/v1/people/first", json={**PERSON_BODY, "email": "mia@example.com"})
    assert refused.status_code == 403 and refused.json() == FORBIDDEN
    assert rig.stored("persons", "u_mia") is None


# --- 2. no membership oracle on remove ----------------------------------------------------------------------------


def test_SELF_SERVE_TEAMS_a_leads_remove_answers_the_same_bytes_whatever_the_person_had(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    _join(rig, FOUNDER)
    _join(rig, "u_mia")
    _join(rig, "u_ben", "ben.secret@example.com")
    _tick(rig, 1)
    team = _create(rig, "u_mia")
    _tick(rig, 2)
    answers = []
    for guess in ("ben@example.com", "ben.secret@example.com"):  # a wrong guess, then Ben's real address
        _do(rig, "u_mia", f"/v1/teams/{team}/invites", {"email": guess})
        answers.append(_do(rig, "u_mia", f"/v1/teams/{team}/members/u_ben/remove"))
    answers.append(_do(rig, "u_mia", f"/v1/teams/{team}/members/u_nobody/remove"))  # no record at all
    assert {(r.status_code, r.content) for r in answers} == {(answers[0].status_code, answers[0].content)}
    assert answers[0].status_code == 200
    assert rig.stored("persons", "u_ben")["memberships"] == [], "the pending entry was removed all the same"


# --- 3. lapsed entries are listed and removable -------------------------------------------------------------------


def test_SELF_SERVE_TEAMS_lapsed_invitations_are_listed_and_freed_by_their_person(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    _join(rig, FOUNDER)
    _join(rig, "u_eve")
    _join(rig, "u_vic")
    minute = 1
    for _ in range(8):  # Eve: create a team, invite Vic, leave it (so her invitation lapses)
        _tick(rig, minute)
        team = _create(rig, "u_eve")
        _tick(rig, minute + 1)
        _do(rig, "u_eve", f"/v1/teams/{team}/invites", {"email": "vic@example.com"})
        assert _do(rig, "u_eve", f"/v1/teams/{team}/members/u_eve/remove").status_code == 200
        minute += 2
    rig.as_user("u_vic")
    mine = rig.client.get("/v1/teams").json()["teams"]
    assert len(mine) == 8 and {(r["state"], r["lead"]) for r in mine} == {("lapsed", False)}
    assert all("invited_by" not in r for r in mine), "a lapsed entry names nobody"
    assert rig.post("/v1/teams", {}).status_code == 403, "eight slots used"
    for row in mine:
        assert _do(rig, "u_vic", f"/v1/teams/{row['team']}/members/u_vic/remove").status_code == 200
    _tick(rig, minute)
    _create(rig, "u_vic")
    own = _create(rig, FOUNDER)
    _tick(rig, minute + 1)
    _do(rig, FOUNDER, f"/v1/teams/{own}/invites", {"email": "vic@example.com"})
    rig.as_user(FOUNDER)
    assert "u_vic" in [m["id"] for m in rig.client.get(f"/v1/teams/{own}").json()["members"]]


# --- small ones ---------------------------------------------------------------------------------------------------


def test_SELF_SERVE_TEAMS_an_invite_in_the_founding_millisecond_keeps_the_founder_the_lead(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    _join(rig, FOUNDER)
    _join(rig, "u_mia")
    _join(rig, "u_ben")
    _tick(rig, 1)
    team = _create(rig, "u_mia")
    _do(rig, "u_mia", f"/v1/teams/{team}/invites", {"email": "ben@example.com"})  # the same millisecond
    entry = rig.stored("persons", "u_ben")["memberships"][0]
    assert entry["assigned_by"]["at"] > rig.stored("persons", "u_mia")["memberships"][0]["assigned_by"]["at"]
    roster = rig.client.get(f"/v1/teams/{team}")
    assert roster.status_code == 200 and roster.json()["members"][0] == {
        "id": "u_mia",
        "display_name": "Mia",
        "lead": True,
    }
    _tick(rig, 2)
    assert _do(rig, "u_ben", f"/v1/teams/{team}/accept").status_code == 200
    rig.as_user("u_ben")
    assert [m["id"] for m in rig.client.get(f"/v1/teams/{team}").json()["members"]] == ["u_mia", "u_ben"]


def test_SELF_SERVE_TEAMS_PE_32_a_world_shared_with_a_self_serve_team_is_read_by_accepted_members_only():
    """Over HTTP: Asha creates a team, Ben accepts her invitation, Cara's stays pending; Asha shares her world with
    the team. Ben reads `GET /worlds/{id}`; Cara, an org owner outside the team and a person of another org get the
    unknown-world 404."""
    rig = WorldRig()
    rig.store.events[WORLD] = [
        base_event(seq=1, type_="world.requested", data={"title": "T"}, vis="all", world_id=WORLD, actor=ASHA)
    ]
    rig.store.runs[WORLD] = SimpleNamespace(layout=None, titles={}, cards=None)

    def at(minute: int) -> None:
        rig.now = f"2026-10-10T09:{minute:02d}:00.000Z"

    at(1)
    team = rig.as_(web(ASHA)).client.post("/v1/teams", json={}).json()["team"]
    at(2)
    for who in ("ben@example.com", "cara@example.com"):
        assert rig.as_(web(ASHA)).client.post(f"/v1/teams/{team}/invites", json={"email": who}).status_code == 200
    at(3)
    assert rig.as_(web(BEN)).client.post(f"/v1/teams/{team}/accept", json={}).status_code == 200
    at(4)
    shared = rig.as_(web(ASHA)).client.put(f"/worlds/{WORLD}/team-shares/{team}")
    assert shared.status_code in (200, 201), shared.text[:300]
    at(5)
    assert rig.as_(web(BEN)).client.get(f"/worlds/{WORLD}").status_code == 200
    unknown = rig.as_(web(BEN)).client.get("/worlds/w_no_such_world")
    for outsider in (CARA, ORGOWNER, DEV):
        got = rig.as_(web(outsider)).client.get(f"/worlds/{WORLD}")
        assert (got.status_code, got.content) == (404, unknown.content), outsider


def test_SELF_SERVE_TEAMS_the_principal_carries_only_a_google_verified_address_and_never_in_its_repr():
    from tilo_api import firebase_auth  # noqa: PLC0415

    google = {"sub": "uid-1", "firebase": {"sign_in_provider": "google.com"}, "email": "a@example.com"}
    verified = firebase_auth.principal_from_claims({**google, "email_verified": True}, channel="web")
    assert verified.verified_email == "a@example.com" and "a@example.com" not in repr(verified)
    unverified = firebase_auth.principal_from_claims({**google, "email_verified": "true"}, channel="web")
    assert unverified.verified_email is None
    anonymous = {"sub": "uid-2", "firebase": {"sign_in_provider": "anonymous"}, "email": "b@example.com"}
    demo = firebase_auth.principal_from_claims({**anonymous, "email_verified": True}, channel="web")
    assert demo.verified_email is None
