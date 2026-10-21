"""ADR-0042 amendment 1 (BQ-MTG-ACTIONS-1): the attend route, and only it, opens the ACTION claim. Its uid and org are
the verified principal's (the meeting owner), its nonce reaches the bot as the attend call's `X-Tilo-Meeting-Actions`
header, never in the body, and it closes when the attend ends. Off (`TILO_MEETING_ACTIONS` unset), nothing is made and
the attend call is exactly what it was."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from _clint2_lib import wait_for
from _mtg09b_lib import MEETING, ORG, OWNER, HostRig, block_network
from tilo_api.meeting_action_claims import ActionClaims, enabled, get_action_claims
from tilo_api.meeting_bot import BotCapture, attend_meeting
from tilo_api.meeting_bot_rpc import MeetingBotRpc
from tilo_api.people_writes import Writer
from tilo_contracts import MeetingJoin, Transcript

CAPTURE = BotCapture(
    Transcript(v="1.0", meeting_id=MEETING, utterances=[{"id": "u0001", "speaker": "A", "t_ms": 1, "text": "Hi."}]),
    "left_on_request",
)


@pytest.fixture
def rig(people_rig, monkeypatch):
    block_network(monkeypatch)
    h = HostRig(people_rig())
    h.approve_and_wait_sent()
    wait_for(lambda: h.events("world.completed"), what="the hosted run to finish")
    h.rig.as_user(OWNER)
    bot = SimpleNamespace(attend=AsyncMock(return_value=CAPTURE))
    return h, Writer(h.rig.stores, ORG, OWNER, h.rig.clock), bot


def _attend(h, w, bot, action_claims):
    host = h.rig.app.dependency_overrides[h.deps.get_meeting_host_client]()
    return asyncio.run(
        attend_meeting(w, h.store, h.art.store, host, bot, MEETING, lambda: h.rig.clock, action_claims=action_claims)
    )


def test_MTG_ACTIONS_1_the_action_claim_is_the_owners_reaches_the_bot_and_closes_after(rig):
    h, w, bot = rig
    claims, seen = ActionClaims(), {}

    async def bot_side(meeting_id, join, *, action_claim):
        found = claims.find(meeting_id, action_claim)
        seen.update(uid=found.uid, org=found.org_id, meeting=found.meeting_id, nonce=action_claim)
        return CAPTURE

    bot.attend.side_effect = bot_side
    _attend(h, w, bot, claims)
    assert (seen["uid"], seen["org"], seen["meeting"]) == (OWNER, ORG, MEETING)
    assert claims.find(MEETING, seen["nonce"]) is None  # closed when the attend ended


def test_MTG_ACTIONS_1_off_by_default_the_attend_call_is_unchanged(rig, monkeypatch):
    monkeypatch.delenv("TILO_MEETING_ACTIONS", raising=False)
    assert enabled() is False and get_action_claims() is None
    h, w, bot = rig
    _attend(h, w, bot, get_action_claims())
    assert bot.attend.await_args.kwargs == {} and len(bot.attend.await_args.args) == 2


def test_MTG_ACTIONS_1_the_nonce_is_only_the_actions_header_never_the_body(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={"v": "1.0", "meeting_id": "mt_demo", "utterances": []},
            headers={"X-Tilo-Meeting-End-Reason": "completed"},
        )

    rpc = MeetingBotRpc(
        "https://tilo-meet-bot.example.run.app", token_for=lambda _: "id-token", transport=httpx.MockTransport(handle)
    )
    join = MeetingJoin(join_url="https://meet.google.com/abc-defg-hij", expires_at="2026-10-11T12:30:00.000Z")
    nonce = "a" * 32
    asyncio.run(rpc.attend("mt_demo", join, None, action_claim=nonce))
    asyncio.run(rpc.attend("mt_demo", join))
    with_actions, without = seen
    assert with_actions.headers["x-tilo-meeting-actions"] == nonce and nonce.encode() not in with_actions.content
    assert "x-tilo-meeting-actions" not in without.headers and "x-tilo-meeting-claim" not in with_actions.headers
    assert with_actions.content == without.content
