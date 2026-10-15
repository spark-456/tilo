"""JUDGE-FIRST-RUN F1 (UX audit 15 Oct): a person who declared `judge` becomes a plain org Member through the web's
existing `POST /v1/people/first` call, so Team, Agenda and the Plate work. They never become the owner, and nobody who
has not declared `judge` (or the configured bootstrap uid) gets in.
"""

from __future__ import annotations

from _ppl11c_lib import PERSON_BODY, R_PERSON_FIRST

ENV_UID = "TILO_PEOPLE_BOOTSTRAP_UID"
FOUNDER = "u_founder"
JUDGE = "u_judge1"
FORBIDDEN = {"detail": "forbidden"}


class _Access:
    def __init__(self, declared: dict[str, str]) -> None:
        self.declared = declared

    def get(self, user_id: str):
        return self.declared.get(user_id)

    def declare(self, user_id: str, declaration: str):
        return self.declared.setdefault(user_id, declaration)


def _rig(people_rig, monkeypatch, declared: dict[str, str]):
    for name in (ENV_UID, "TILO_PEOPLE_STORE", "TILO_FIRESTORE_PROJECT", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    rig = people_rig(access=_Access(declared))
    rig.unwire("founder_gate")
    monkeypatch.setenv(ENV_UID, FOUNDER)
    rig.require_route(R_PERSON_FIRST)
    return rig


def _first(rig, **body):
    return rig.client.post("/v1/people/first", json={**PERSON_BODY, **body})


def _found(rig) -> None:
    """The owner has founded the org (the bootstrap uid), as live: judges join an org that already has its owner."""
    rig.as_user(FOUNDER)
    assert _first(rig, email="founder@example.com", display_name="Founder").status_code == 201


def test_JUDGE_FIRST_RUN_F1_a_judge_joins_as_a_member_never_the_owner(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch, {JUDGE: "judge"})
    _found(rig)
    rig.as_user(JUDGE)
    joined = _first(rig)
    assert joined.status_code == 201, joined.text[:300]
    assert joined.json()["id"] == JUDGE and joined.json()["org_role"] == "member"
    assert rig.stored("persons", JUDGE)["org_role"] == "member"
    assert rig.stored("persons", FOUNDER)["org_role"] == "owner"
    listed = rig.client.get("/v1/people")
    assert listed.status_code == 200 and listed.json()["you"] == JUDGE


def test_JUDGE_FIRST_RUN_F1_a_judge_cannot_close_the_door_on_the_owner_before_the_org_is_founded(
    people_rig, monkeypatch
):
    """SELF-SERVE-TEAMS (ADR-0044): a judge may join before founding now, as a member, and that never blocks the
    owner, who still founds the org afterwards."""
    rig = _rig(people_rig, monkeypatch, {JUDGE: "judge"})
    rig.as_user(JUDGE)
    joined = _first(rig)
    assert joined.status_code == 201 and joined.json()["org_role"] == "member"
    assert rig.real.persons.founded(rig.org) is False
    _found(rig)  # the owner can still found it
    assert rig.stored("persons", FOUNDER)["org_role"] == "owner"


def test_JUDGE_FIRST_RUN_F1_a_visitor_or_undeclared_person_joins_as_a_member_never_the_owner(people_rig, monkeypatch):
    """SELF-SERVE-TEAMS (ADR-0044, BQ-SST-6): the judge declaration no longer gates joining; every full, non-demo web
    sign-in joins as a plain member, and none of them becomes owner."""
    rig = _rig(people_rig, monkeypatch, {"u_visitor1": "visitor"})
    for i, uid in enumerate(("u_visitor1", "u_nobody1")):
        rig.as_user(uid)
        joined = _first(rig, email=f"v{i}@example.com")
        assert joined.status_code == 201 and joined.json()["org_role"] == "member", (uid, joined.text[:200])
    assert rig.real.persons.founded(rig.org) is False


def test_JUDGE_FIRST_RUN_F1_a_judge_needs_a_full_web_session_and_not_a_demo_one(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch, {JUDGE: "judge"})
    _found(rig)
    rig.as_user(JUDGE)
    before = rig.snapshot()
    for channel, full in (("email", True), ("web", False), ("whatsapp", True)):
        rig.channel, rig.full_session = channel, full
        refused = _first(rig)
        assert refused.status_code == 403 and refused.json() == FORBIDDEN, (channel, full)
    assert rig.snapshot() == before


def test_JUDGE_FIRST_RUN_F1_a_judge_with_a_record_is_not_written_twice(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch, {JUDGE: "judge"})
    _found(rig)
    rig.as_user(JUDGE)
    assert _first(rig).status_code == 201
    version = rig.version_of("persons", JUDGE)
    again = _first(rig, display_name="Someone Else", email="else@example.com")
    assert again.status_code == 200 and again.json()["org_role"] == "member", again.text  # SELF-SERVE-TEAMS
    assert rig.version_of("persons", JUDGE) == version
    assert rig.stored("persons", JUDGE)["org_role"] == "member"


def test_JUDGE_FIRST_RUN_F1_a_taken_address_is_a_409_not_a_second_judge(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch, {JUDGE: "judge", "u_judge2": "judge"})
    _found(rig)
    rig.as_user(JUDGE)
    assert _first(rig).status_code == 201
    rig.as_user("u_judge2")
    clash = _first(rig)
    assert clash.status_code == 409 and clash.json()["code"] == "email_taken"
    assert rig.stored("persons", "u_judge2") is None
