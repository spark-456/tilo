"""CH-RM follow-up (SEC-06, FR-HIL-10): the Team Lead console answers on the principal's own session channel, not a
hardcoded `web`. It takes the same session check as the cards route: a web or mobile web session answers, a session of
another class or a tilo-channels caller is refused (400 `invalid_channel`) before anything is written."""

from __future__ import annotations

import pytest
from _cards_lib import FakeClock, FakeEventWriter, clone_card, load_valid_card, new_ulid, principal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import cards, console, deps
from tilo_api.cards import CardStore

START = "2026-09-29T09:30:00.000Z"
W, OWNER = "w_01", "u_owner"
LEAD = {
    "id": "tl_security",
    "user": "u_sec",
    "domain": "security",
    "assigned_by": {"by": OWNER, "at": "2026-09-01T00:00:00.000Z"},
}


def _setup(channel: str, *, from_channels: bool = False, listed=("web", "mobile_web", "email")):
    writer = FakeEventWriter()
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={W: OWNER})
    q = clone_card(load_valid_card("needs_you_blocked"), id_=new_ulid("q"), created_at=START, building="B2")
    q["answer_channels"] = list(listed)
    assert store.submit(q, district="D1", domain="security").outcome == "accepted"
    app = FastAPI()
    app.include_router(console.build_router(store))
    who = principal(role="team_lead", user_id="u_sec", world_id=W, districts=("D1",), channel=channel)
    app.dependency_overrides[deps.get_current_principal] = lambda: who
    app.dependency_overrides[cards.get_channels_caller] = lambda: from_channels
    app.dependency_overrides[console.get_team_leads] = lambda: [LEAD]
    return TestClient(app), writer, q


def _answer(http, q):
    return http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": q["options"][0]["id"]})


@pytest.mark.parametrize("channel", ["web", "mobile_web"])
def test_CH_RM_SEC_06_a_team_lead_answers_on_their_own_signed_in_channel(channel):
    http, writer, q = _setup(channel, listed=(channel,))  # the card lists only this session's channel

    assert _answer(http, q).status_code == 200
    assert len(writer.of_type("question.answered")) == 1


def test_CH_RM_SEC_06_the_console_no_longer_answers_as_web_for_a_mobile_web_session():
    http, writer, q = _setup("mobile_web", listed=("web",))  # a mobile web session is not answering "web"

    response = _answer(http, q)

    assert (response.status_code, response.json()) == (400, {"outcome": "rejected", "reason": "invalid_channel"})
    assert writer.parts == []


@pytest.mark.parametrize(("channel", "from_channels"), [("email", False), ("email", True), ("web", True)])
def test_CH_RM_SEC_06_the_console_refuses_a_session_that_is_not_signed_in_web(channel, from_channels):
    http, writer, q = _setup(channel, from_channels=from_channels)

    response = _answer(http, q)

    assert (response.status_code, response.json()) == (400, {"outcome": "rejected", "reason": "invalid_channel"})
    assert writer.parts == []
