"""MEET-GUEST: Tilo's guest bot joins the person's own Google Meet; no meeting host sign-in is involved."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from _clint2_lib import wait_for
from _mtg09b_lib import MEETING, ORG, OWNER, SAM, WORLD, HostRig, block_network
from tilo_api.meeting_bot import BotCapture, attend_meeting
from tilo_api.people_writes import Refusal, Writer
from tilo_contracts import Transcript
from tilo_memory.artifacts import Scope

LINK = "https://meet.google.com/abc-defg-hij"


@pytest.fixture
def rig(people_rig, monkeypatch):
    block_network(monkeypatch)
    h = HostRig(people_rig())
    h.approve_and_wait_sent()
    wait_for(lambda: h.events("world.completed"), what="the run to finish")
    h.rig.as_user(OWNER)
    captured = BotCapture(
        Transcript(
            v="1.0",
            meeting_id=MEETING,
            utterances=[{"id": "u0001", "speaker": "Someone", "t_ms": 900, "text": "Ship it on Friday."}],
        ),
        "left_on_request",
    )
    bot = SimpleNamespace(attend=AsyncMock(return_value=captured))
    host = SimpleNamespace(join_link=Mock(side_effect=AssertionError("the guest path never asks the meeting host")))
    return h, Writer(h.rig.stores, ORG, OWNER, h.rig.clock), bot, host


def attend(h, w, bot, host, link):
    return asyncio.run(attend_meeting(w, h.store, h.art.store, host, bot, MEETING, lambda: h.rig.clock, join_url=link))


def test_MEET_GUEST_bot_joins_own_link_without_meeting_host(rig):
    h, w, bot, host = rig
    result = attend(h, w, bot, host, LINK)
    assert result["status"] == "ended" and result["transcript"] is not None
    join = bot.attend.await_args.args[1]
    assert join.join_url == LINK
    host.join_link.assert_not_called()
    stored = h.art.store.read(Scope(ORG, WORLD, OWNER), result["transcript"])
    assert b"Ship it on Friday." in stored and b"meet.google.com" not in stored
    assert "join_url" not in h.rig.real.meetings.get(ORG, MEETING).record


@pytest.mark.parametrize(
    "link",
    [
        "http://meet.google.com/abc-defg-hij",
        "https://meet.google.com.evil.example/abc-defg-hij",
        "https://meet.google.com/abc-defg-hij?authuser=1",
        "https://meet.google.com/abc-defg-hij/x",
        "https://example.com/abc-defg-hij",
        "https://meet.google.com/ABC-DEFG-HIJ",
    ],
)
def test_MEET_GUEST_refuses_anything_but_a_meet_link(rig, link):
    h, w, bot, host = rig
    with pytest.raises(Refusal) as raised:
        attend(h, w, bot, host, link)
    assert raised.value.status_code == 422
    bot.attend.assert_not_awaited()
    assert h.rig.real.meetings.get(ORG, MEETING).record["status"] == "scheduled"


def test_MEET_GUEST_non_owner_never_starts_bot(rig):
    h, w, bot, host = rig
    w.actor = SAM
    with pytest.raises(Refusal) as raised:
        attend(h, w, bot, host, LINK)
    assert raised.value.status_code == 404
    bot.attend.assert_not_awaited()


def test_MEET_GUEST_route_takes_a_link_and_refuses_extra_fields(rig):
    from tilo_api.meeting_bot_rpc import get_meeting_bot_client

    h, _, bot, _ = rig
    h.rig.app.dependency_overrides[get_meeting_bot_client] = lambda: bot
    path = f"/v1/meetings/{MEETING}/attend"
    assert h.rig.client.post(path, json={"join_url": LINK, "owner": OWNER}).status_code == 422
    assert h.rig.client.post(path, json={"join_url": "https://example.com/x"}).status_code == 422
    bot.attend.assert_not_awaited()
    response = h.rig.client.post(path, json={"join_url": LINK})
    assert response.status_code == 200 and response.json()["transcript"] is not None
    assert LINK not in response.text
    bot.attend.assert_awaited_once()
