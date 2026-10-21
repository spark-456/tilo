"""ADR-0042 amendment 1 (owner decision 21 Oct, BQ-MTG-ACTIONS-1): the meeting bot's three write actions.

The bot calls `POST /internal/meeting-actions/run` with its Google ID token and this attend's action claim. The claim
names the meeting owner; the speaker's caption name, when given, is matched exactly to a person the owner can see,
and the action runs as that person (the owner when no speaker is named: one-on-one). Three actions only, at most five
per call, a replay of the same key answers the same, and nothing is written for an unknown speaker, a missing claim,
another caller, or with the switch off. No Google Calendar, no invite, no email."""

from __future__ import annotations

import secrets

import pytest
from _mv_lib import AUDIENCE, BOT_SA, TASKS_SA, TICK_SA, FakeVerifier
from _ppl11a_lib import OWNER, PRIYA

ROUTE = "/internal/meeting-actions/run"
MEETING = "mt_actions0001"


@pytest.fixture()
def rig(people_rig, monkeypatch):
    from tilo_api import meeting_action_claims, schedules  # noqa: PLC0415

    r = people_rig()
    r.add_people()
    r.add(
        "meetings",
        {
            **_meeting_record(r),
            "id": MEETING,
            "owner": OWNER,
        },
    )
    verifier = FakeVerifier()
    claims = meeting_action_claims.ActionClaims()
    ov = r.app.dependency_overrides
    ov[schedules.get_oidc_verifier] = lambda: verifier
    ov[meeting_action_claims.get_action_claims] = lambda: claims
    monkeypatch.setenv("TILO_MEETING_ACTIONS", "1")
    monkeypatch.setenv("TILO_MEETING_ACTIONS_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("TILO_MEETING_ACTIONS_CALLER", BOT_SA)
    monkeypatch.setenv("TILO_SCHEDULE_TICK_CALLER", TICK_SA)
    monkeypatch.setenv("TILO_TASKS_CALLER", TASKS_SA)
    monkeypatch.delenv("TILO_APPCHECK_ENFORCE", raising=False)
    r.verifier, r.claims = verifier, claims
    r.token = verifier.register(BOT_SA)
    r.nonce = claims.open(MEETING, uid=OWNER, org_id=r.org)
    return r


def _meeting_record(r):
    import json  # noqa: PLC0415

    from _ppl11a_lib import CONTRACTS  # noqa: PLC0415

    record = json.loads(
        (CONTRACTS / "fixtures" / "meeting" / "valid" / "switches_off_and_no_brief_yet.json").read_text()
    )
    record["org_id"] = r.org
    record["agenda"] = [{"title": "Kick-off", "minutes": None}]
    return record


def _run(r, action, args, *, speaker=None, key=None, token="", nonce=None, meeting=MEETING):
    body = {
        "meeting_id": meeting,
        "claim": r.nonce if nonce is None else nonce,
        "key": key or secrets.token_urlsafe(12),
        "speaker": speaker,
        "action": action,
        "args": args,
    }
    headers = {"Authorization": f"Bearer {r.token if token == '' else token}"} if token is not None else {}
    return r.client.post(ROUTE, json=body, headers=headers)


def test_MTG_ACTIONS_1_owner_one_on_one_pins_to_their_personal_board(rig):
    answer = _run(rig, "create_pin", {"title": "Submission checklist", "board": "personal"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["outcome"] == "done" and answer.json()["board"] == "personal"
    pins = [p.record for p in rig.real.pins.list(rig.org)]
    assert [(p["title"], p["scope"]) for p in pins] == [("Submission checklist", {"kind": "personal", "user": OWNER})]


def test_MTG_ACTIONS_1_a_named_speaker_writes_to_their_own_team_board(rig):
    answer = _run(rig, "create_pin", {"title": "Launch date moved", "board": "team"}, speaker="Priya Nair")
    assert answer.status_code == 200, answer.text
    pin = [p.record for p in rig.real.pins.list(rig.org)][0]
    assert pin["scope"] == {"kind": "team", "team": "tm_launch"} and pin["created_by"]["ref"] == PRIYA


def test_MTG_ACTIONS_1_an_unknown_speaker_writes_nothing(rig):
    answer = _run(rig, "create_pin", {"title": "x", "board": "personal"}, speaker="Mallory Fake")
    assert answer.status_code == 404 and answer.json()["outcome"] == "unknown_person"
    assert list(rig.real.pins.list(rig.org)) == []


def test_MTG_ACTIONS_1_add_agenda_item_appends_to_this_meeting(rig):
    answer = _run(rig, "add_agenda_item", {"title": "Submission requirements"}, speaker="Asha Rao")
    assert answer.status_code == 200, answer.text
    agenda = rig.stored("meetings", MEETING)["agenda"]
    assert [a["title"] for a in agenda] == ["Kick-off", "Submission requirements"]


def test_MTG_ACTIONS_1_create_meeting_needs_the_spoken_recording_attestation_and_sends_no_invite(rig):
    args = {"title": "Follow-up", "start": "2026-10-23T09:30:00.000Z", "minutes": 30}
    assert _run(rig, "create_meeting", args).status_code == 422  # no attestation
    answer = _run(rig, "create_meeting", {**args, "recording_attested": True})
    assert answer.status_code == 200, answer.text
    assert answer.json()["start"] == "2026-10-23T09:30:00.000Z"
    made = [m.record for m in rig.real.meetings.list(rig.org) if m.record["id"] != MEETING]
    assert len(made) == 1 and made[0]["owner"] == OWNER and made[0]["status"] == "scheduled"
    assert made[0]["attendees"] == [] and made[0]["source"] == "bot"


def test_MTG_ACTIONS_1_at_most_five_actions_per_call_and_a_replay_answers_the_same(rig):
    first = _run(rig, "create_pin", {"title": "one", "board": "personal"}, key="k1")
    again = _run(rig, "create_pin", {"title": "one", "board": "personal"}, key="k1")
    assert first.json() == again.json() and len(list(rig.real.pins.list(rig.org))) == 1
    for n in range(4):
        assert _run(rig, "create_pin", {"title": f"n{n}", "board": "personal"}).status_code == 200
    capped = _run(rig, "create_pin", {"title": "six", "board": "personal"})
    assert capped.status_code == 409 and capped.json()["outcome"] == "cap_reached"
    assert len(list(rig.real.pins.list(rig.org))) == 5


@pytest.mark.parametrize(
    "case,status",
    [("no_token", 401), ("tick_caller", 403), ("wrong_nonce", 409), ("other_meeting", 409), ("bad_action", 422)],
)
def test_MTG_ACTIONS_1_refusals_write_nothing(rig, case, status):
    kw = {}
    action, args = "create_pin", {"title": "x", "board": "personal"}
    if case == "no_token":
        kw["token"] = None
    elif case == "tick_caller":
        kw["token"] = rig.verifier.register(TICK_SA)
    elif case == "wrong_nonce":
        kw["nonce"] = "n" * 32
    elif case == "other_meeting":
        kw["meeting"] = "mt_actions0002"
    elif case == "bad_action":
        action = "send_email"
    assert _run(rig, action, args, **kw).status_code == status
    assert list(rig.real.pins.list(rig.org)) == []


def test_MTG_ACTIONS_1_off_by_default_is_a_plain_404(rig, monkeypatch):
    monkeypatch.delenv("TILO_MEETING_ACTIONS")
    assert _run(rig, "create_pin", {"title": "x", "board": "personal"}).status_code == 404
    assert list(rig.real.pins.list(rig.org)) == []


# -- the deployed wiring (live failure 21 Oct 15:22 IST): the bot's call carries no sign-in --------------------------


@pytest.fixture()
def deployed(rig, monkeypatch):
    """The rig as a Cloud Run revision has it: NO principal, store, event writer, Desk or redactor override, so every
    seam resolves the way production does (`deps._people_stores`, `durable_store.deployed`, the real redactor). The
    meeting is mid-call (`joining`), as it was when the owner asked. Only the clock, the verifier and the claim
    registry stay faked."""
    from tilo_api import deps, durable_store  # noqa: PLC0415

    monkeypatch.setenv("K_SERVICE", "tilo-api")
    for seam in (
        deps.get_current_principal,
        deps.get_people_stores,
        deps.get_event_writer,
        deps.get_desk_worlds,
        deps.get_redactor,
        deps.get_store,
    ):
        rig.app.dependency_overrides.pop(seam, None)
    store = rig.event_store
    monkeypatch.setattr(store, "load_path", lambda params: store, raising=False)
    monkeypatch.setattr(deps, "_people_stores", rig.stores)
    monkeypatch.setattr(durable_store, "deployed", lambda: (store, rig.events))
    stored = rig.stored("meetings", MEETING)
    rig.real.meetings.replace({**stored, "status": "joining"}, expected_version=rig.version_of("meetings", MEETING))
    return rig


def test_MTG_ACTIONS_1_deployed_add_agenda_item_mid_call_writes_through_the_real_seams(deployed):
    answer = _run(deployed, "add_agenda_item", {"title": "Finish up the demo video"})
    assert answer.status_code == 200, answer.text
    agenda = deployed.stored("meetings", MEETING)["agenda"]
    assert [a["title"] for a in agenda] == ["Kick-off", "Finish up the demo video"]


def test_MTG_ACTIONS_1_deployed_create_pin_and_create_meeting_write_through_the_real_seams(deployed):
    pinned = _run(deployed, "create_pin", {"title": "Submission checklist", "board": "personal"})
    assert pinned.status_code == 200, pinned.text
    team = _run(deployed, "create_pin", {"title": "Launch date moved", "board": "team"}, speaker="Priya Nair")
    assert team.status_code == 200, team.text
    args = {"title": "Follow-up", "start": "2026-10-23T09:30:00.000Z", "minutes": 30, "recording_attested": True}
    made = _run(deployed, "create_meeting", args)
    assert made.status_code == 200, made.text
    assert len(list(deployed.real.pins.list(deployed.org))) == 2
    assert len([m for m in deployed.real.meetings.list(deployed.org) if m.record["id"] != MEETING]) == 1


def test_MTG_ACTIONS_1_a_team_pin_for_someone_on_no_team_says_so_and_writes_nothing(rig):
    """Live 21 Oct 19:17: the owner is on no team in the org; Tilo said "I couldn't tell which team board to use"."""
    me = rig.stored("persons", OWNER)
    rig.real.persons.replace({**me, "memberships": []}, expected_version=rig.version_of("persons", OWNER))
    answer = _run(rig, "create_pin", {"title": "Unfinished demo video", "board": "team"})
    assert answer.status_code == 409 and answer.json()["outcome"] == "no_team"
    assert list(rig.real.pins.list(rig.org)) == []
    personal = _run(rig, "create_pin", {"title": "Unfinished demo video", "board": "personal"})
    assert personal.status_code == 200, personal.text
