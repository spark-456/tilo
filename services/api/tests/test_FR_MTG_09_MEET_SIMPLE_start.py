"""MEET-SIMPLE (FR-MTG-09, ADR-0024): `POST /v1/meetings/{id}/start`, the person's own click as the approval.

The route runs the same host run and gate card as `/host` and answers that card with `approve` as the signed-in owner,
so the approval is the record a card answer writes (`approval.resolved`, authz by person). It sends exactly the people
the dialog showed (`invited`) and nobody else; any other draft starts nothing. No policy or risk tier is changed."""

from __future__ import annotations

import pytest
from _mtg09b_lib import MEETING, OWNER, PRIYA, SAM, WORLD, HostRig, block_network
from _ppl11a_lib import MEERA

SHOWN = [OWNER, PRIYA, SAM]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture()
def hr(people_rig):
    return HostRig(people_rig())


def start(hr: HostRig, invited=SHOWN, *, approve=True, actor=OWNER, meeting_id=MEETING):
    hr.rig.as_user(actor)
    return hr.rig.client.post(f"/v1/meetings/{meeting_id}/start", json={"approve": approve, "invited": invited})


def test_FR_MTG_09_MEET_SIMPLE_one_click_sends_the_invitation_to_exactly_the_shown_people(hr):
    response = start(hr)
    assert response.status_code == 200, response.text[:300]
    assert response.json() == {"world_id": WORLD}
    assert response.headers["cache-control"] == "no-store"
    (request,) = hr.calendar.requests
    emails = [a["email"] for a in request["json"]["attendees"]]
    assert len(emails) == 3, "the owner, Priya and Sam; the attendee with no account is never invited"
    (entry,) = hr.entries()
    assert entry["state"] == "sent" and entry["risk_tier"] == "T3", "the tier is unchanged: the click is the approval"
    assert entry["recipients"] == emails


def test_FR_MTG_09_MEET_SIMPLE_the_approval_is_the_one_a_card_answer_writes(hr):
    assert start(hr).status_code == 200
    (resolved,) = hr.events("approval.resolved")
    assert resolved["authz"]["by"] == "person" and resolved["authz"]["ref"] == OWNER
    assert resolved["data"]["option"] == "approve" and resolved["data"]["channel"] == "web"
    (requested,) = hr.events("approval.requested")
    assert resolved["data"]["card_id"] == requested["data"]["card_id"] and resolved["data"]["pin_verified"] is False
    assert hr.gate_cards() == [], "no card is left waiting for a second approval"


def test_FR_MTG_09_MEET_SIMPLE_the_person_can_still_join_after_the_start(hr):
    assert start(hr).status_code == 200
    hr.rig.as_user(OWNER)
    joined = hr.rig.client.get(f"/v1/meetings/{MEETING}/join")
    assert joined.status_code == 200, joined.text[:200]
    assert joined.json()["join_url"].startswith("https://meet.google.com/")


@pytest.mark.parametrize(
    "invited",
    [[OWNER], [OWNER, PRIYA], [OWNER, PRIYA, SAM, MEERA], [PRIYA, SAM], ["u_ghost"]],
)
def test_FR_MTG_09_MEET_SIMPLE_a_draft_that_differs_from_what_was_shown_starts_nothing(hr, invited):
    before = hr.nothing_happened()
    response = start(hr, invited)
    assert response.status_code == 409 and response.json()["detail"] == "invitees_changed"
    assert hr.nothing_happened() == before, "no run, no card, no entry, no call"


def test_FR_MTG_09_MEET_SIMPLE_only_a_true_click_with_a_list_is_accepted(hr):
    before = hr.nothing_happened()
    for body in (
        {"invited": SHOWN},
        {"approve": False, "invited": SHOWN},
        {"approve": 1, "invited": SHOWN},
        {"approve": True, "invited": []},
        {"approve": True, "invited": SHOWN, "extra": 1},
        {},
    ):
        hr.rig.as_user(OWNER)
        assert hr.rig.client.post(f"/v1/meetings/{MEETING}/start", json=body).status_code == 422, body
    assert hr.nothing_happened() == before


def test_FR_MTG_09_MEET_SIMPLE_nobody_but_the_owner_on_a_full_sign_in_can_start(hr):
    before = hr.nothing_happened()
    for actor in (PRIYA, SAM, MEERA, "u_ghost"):
        assert start(hr, actor=actor).status_code in (403, 404), actor
    assert start(hr, meeting_id="mt_never_made").status_code == 404
    hr.rig.full_session = False
    assert start(hr).status_code == 403
    assert hr.nothing_happened() == before


def test_FR_MTG_09_MEET_SIMPLE_a_second_click_does_not_send_twice(hr):
    assert start(hr).status_code == 200
    again = start(hr)
    assert again.status_code == 409
    assert len(hr.calendar.requests) == 1 and len(hr.entries()) == 1


def test_FR_MTG_09_MEET_SIMPLE_a_picked_person_resolves_only_to_a_teammate(hr):
    hr.rig.as_user(OWNER)
    body = {
        "attest": True,
        "notice_version": "1.0.0",
        "title": "Picked",
        "source": "bot",
        "attendees": [
            {"name": "x", "person": PRIYA},
            {"name": "y", "person": "u_ghost"},
            {"name": "z", "person": OWNER},
        ],
    }
    made = hr.rig.client.post("/v1/meetings", json=body, headers={"Idempotency-Key": "k-1"})
    assert made.status_code == 201, made.text[:300]
    users = [a["user"] for a in made.json()["attendees"]]
    assert users[0] == PRIYA and users[1] is None and users[2] == OWNER
    # an existing person of the org who is not the owner's teammate never resolves
    for other in (MEERA,):
        got = hr.rig.client.post(
            "/v1/meetings",
            json={**body, "attendees": [{"name": "n", "person": other}]},
            headers={"Idempotency-Key": f"k-{other}"},
        )
        assert got.status_code == 201, got.text[:300]
        assert [a["user"] for a in got.json()["attendees"]] == [None], other


def test_FR_MTG_09_MEET_SIMPLE_a_pause_after_the_card_writes_no_approval(hr, monkeypatch):
    from tilo_api.cards import CardStore  # noqa: PLC0415

    real = CardStore.is_open

    def is_open_then_pause(self, world_id, card_id):
        found = real(self, world_id, card_id)
        if found:
            hr.store.worlds[world_id].paused = True  # the owner pauses the world right after the card is raised
        return found

    monkeypatch.setattr(CardStore, "is_open", is_open_then_pause)
    response = start(hr)
    assert response.status_code == 409 and response.json()["detail"] == "world_paused"
    assert hr.events("approval.resolved") == [] and hr.entries() == [] and hr.calendar.requests == []


def test_FR_MTG_09_MEET_SIMPLE_the_answer_uses_the_session_channel(hr):
    hr.rig.channel = "mobile_web"
    assert start(hr).status_code == 200
    (resolved,) = hr.events("approval.resolved")
    assert resolved["data"]["channel"] == "mobile_web"
