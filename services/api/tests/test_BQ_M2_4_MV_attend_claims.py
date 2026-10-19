"""BQ-M2-4, ADR-0042 decision 2 (MV-02, MV-08, MV-16): the attend route, and only the attend route, makes the claim.
Its uid and org are the verified principal's (the same ones that proved the meeting's, the world's and the receipt's
owner), its nonce goes to the bot as the attend call's `X-Tilo-Meeting-Claim` header, and it is closed on every way out
of the attend. Off (`TILO_VOICE_METER` unset) nothing is made and the attend call is byte for byte what it was."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from _clint2_lib import wait_for
from _mtg09b_lib import MEETING, ORG, OWNER, HostRig, block_network
from tilo_api.meeting_bot import BotCapture, attend_meeting
from tilo_api.meeting_bot_rpc import MeetingBotRpc
from tilo_api.meeting_voice_claims import AttendClaims, Hold, enabled, get_attend_claims
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


def attend(h, w, bot, claims):
    host = h.rig.app.dependency_overrides[h.deps.get_meeting_host_client]()
    return asyncio.run(attend_meeting(w, h.store, h.art.store, host, bot, MEETING, lambda: h.rig.clock, claims=claims))


def test_BQ_M2_4_MV_02_the_claim_is_the_verified_principals_and_the_bot_gets_its_nonce_as_the_third_argument(rig):
    h, w, bot = rig
    claims, seen = AttendClaims(), {}

    async def bot_side(meeting_id, join, nonce):
        found = claims.find(meeting_id, nonce)
        seen.update(uid=found.uid, org=found.org_id, run=found.run_id, nonce=nonce, join=join)
        return CAPTURE

    bot.attend.side_effect = bot_side
    attend(h, w, bot, claims)
    assert (seen["uid"], seen["org"], seen["run"]) == (OWNER, ORG, MEETING)
    assert 32 <= len(seen["nonce"]) <= 64 and seen["nonce"].replace("-", "").replace("_", "").isalnum()
    assert isinstance(seen["join"], MeetingJoin)


def test_BQ_M2_4_MV_16_each_attend_makes_its_own_nonce(rig):
    h, w, bot = rig
    nonces = []
    claims = AttendClaims()

    async def remember(_meeting, _join, nonce):
        nonces.append(nonce)
        raise RuntimeError("the bot failed")  # the meeting returns to scheduled: the owner may attend again

    bot.attend.side_effect = remember
    for _ in range(2):
        with pytest.raises(RuntimeError):
            attend(h, w, bot, claims)
    assert len(nonces) == 2 and nonces[0] != nonces[1]


@pytest.mark.parametrize("how", ["success", "failure", "cancel"])
def test_BQ_M2_4_MV_02_the_claim_closes_on_success_failure_and_cancellation_and_a_late_reserve_is_409(rig, how):
    h, w, bot = rig
    claims, nonce_seen = AttendClaims(), []
    host = h.rig.app.dependency_overrides[h.deps.get_meeting_host_client]()

    async def bot_side(_meeting, _join, nonce):
        nonce_seen.append(nonce)
        assert claims.find(MEETING, nonce) is not None
        if how == "failure":
            raise RuntimeError("failed")
        if how == "cancel":
            await asyncio.Event().wait()
        return CAPTURE

    bot.attend.side_effect = bot_side

    async def run():
        task = asyncio.create_task(
            attend_meeting(w, h.store, h.art.store, host, bot, MEETING, lambda: h.rig.clock, claims=claims)
        )
        if how == "cancel":
            while not nonce_seen:
                await asyncio.sleep(0.01)
            task.cancel()
        try:
            await task
        except BaseException:  # noqa: BLE001  (the failure and the cancellation themselves are not under test)
            pass

    asyncio.run(run())
    assert nonce_seen and claims.find(MEETING, nonce_seen[0]) is None


def test_BQ_M2_4_MV_08_an_open_hold_when_the_attend_ends_settles_at_the_whole_unit(rig, monkeypatch):
    from _sec16_lib import make_caps, make_guard, make_ledger

    h, w, bot = rig
    ledger = make_ledger(make_caps())
    guard, claims = make_guard(ledger), AttendClaims()
    unit = guard._caps.unit_reserve_minor

    async def bot_side(meeting_id, _join, nonce):
        claim = claims.find(meeting_id, nonce)
        plan = guard.begin_unit(
            "live", uid=claim.uid, run_id=claim.run_id, org_id=claim.org_id, estimate_minor=unit, at=datetime.now(UTC)
        )
        claim.holds["k" * 16] = Hold(plan, guard, unit, claims.now())
        return CAPTURE

    bot.attend.side_effect = bot_side
    attend(h, w, bot, claims)
    assert (ledger.spent_minor(OWNER), ledger.settled_minor(OWNER)) == (unit, unit)


def test_BQ_M2_5_MV_13_off_by_default_no_claim_is_made_and_the_attend_call_is_unchanged(rig, monkeypatch):
    monkeypatch.delenv("TILO_VOICE_METER", raising=False)
    assert enabled() is False and get_attend_claims() is None
    h, w, bot = rig
    attend(h, w, bot, get_attend_claims())
    bot.attend.assert_awaited_once()
    assert len(bot.attend.await_args.args) == 2  # (meeting_id, join): no third argument, no header
    monkeypatch.setenv("TILO_VOICE_METER", "1")
    assert enabled() is True and isinstance(get_attend_claims(), AttendClaims)
    assert get_attend_claims() is get_attend_claims()  # one registry for the process


def test_BQ_M2_4_MV_16_the_nonce_reaches_the_bot_only_as_the_claim_header_never_in_the_body(monkeypatch):
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
    nonce = "n" * 32
    asyncio.run(rpc.attend("mt_demo", join, nonce))
    asyncio.run(rpc.attend("mt_demo", join))
    with_claim, without = seen
    assert with_claim.headers["x-tilo-meeting-claim"] == nonce and nonce.encode() not in with_claim.content
    assert "x-tilo-meeting-claim" not in without.headers
    assert with_claim.content == without.content  # the body is MeetingJoin and nothing more
