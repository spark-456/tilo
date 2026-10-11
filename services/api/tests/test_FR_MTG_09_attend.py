"""The owner explicitly starts capture; fake attendance and real scoped artifact storage."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _clint2_lib import wait_for
from _mtg09b_lib import MEETING, ORG, OWNER, SAM, WORLD, HostRig, block_network
from _ppl11c_lib import gone_meeting
from tilo_api.meeting_bot import BotCapture, attend_meeting
from tilo_api.people_writes import Refusal, Writer
from tilo_contracts import Transcript
from tilo_memory.artifacts import Scope


@pytest.fixture
def rig(people_rig, monkeypatch):
    block_network(monkeypatch)
    h = HostRig(people_rig())
    h.approve_and_wait_sent()
    wait_for(lambda: h.events("artifact.created"), what="host receipt")
    h.rig.as_user(OWNER)
    captured = BotCapture(
        Transcript(
            v="1.0",
            meeting_id=MEETING,
            utterances=[
                {"id": "u0001", "speaker": "Someone", "t_ms": 1250, "text": "Decision: proceed."},
            ],
        ),
        "left_on_request",
    )
    bot = SimpleNamespace(attend=AsyncMock(return_value=captured))
    w = Writer(h.rig.stores, ORG, OWNER, h.rig.clock)
    return h, w, bot


def attend(h, w, bot):
    host = h.rig.app.dependency_overrides[h.deps.get_meeting_host_client]()
    return asyncio.run(attend_meeting(w, h.store, h.art.store, host, bot, MEETING, lambda: h.rig.clock))


def test_FR_MTG_09_explicit_attend_attaches_scoped_transcript_and_retention(rig):
    h, w, bot = rig
    result = attend(h, w, bot)
    assert result["status"] == "ended" and result["ended_reason"] == "left_on_request"
    assert result["transcript"] is not None and result["delete_transcript_after"] > h.rig.clock
    stored = h.art.store.read(Scope(ORG, WORLD, OWNER), result["transcript"])
    assert b"Decision: proceed." in stored
    assert b"meet.google.com" not in stored
    bot.attend.assert_awaited_once()


def test_FR_MTG_09_non_owner_never_starts_bot(rig):
    h, w, bot = rig
    w.actor = SAM
    with pytest.raises(Refusal) as raised:
        attend(h, w, bot)
    assert raised.value.status_code == 404
    bot.attend.assert_not_awaited()


def test_FR_MTG_09_second_attend_does_not_launch_again(rig):
    h, w, bot = rig
    attend(h, w, bot)
    with pytest.raises(Refusal) as raised:
        attend(h, w, bot)
    assert raised.value.status_code == 409
    assert bot.attend.await_count == 1


def test_FR_MTG_09_deleted_during_capture_does_not_attach_notes(rig):
    h, w, bot = rig

    async def deleted(*_):
        stored = h.rig.real.meetings.get(ORG, MEETING)
        h.rig.real.meetings.replace(gone_meeting(dict(stored.record), "deleted"), expected_version=stored.version)
        return bot.attend.return_value

    bot.attend.side_effect = deleted
    with pytest.raises(Refusal):
        attend(h, w, bot)
    assert h.rig.real.meetings.get(ORG, MEETING).record["transcript"] is None


def test_FR_MTG_09_attend_route_requires_empty_body_and_owner(rig):
    from tilo_api.meeting_bot_rpc import get_meeting_bot_client

    h, _, bot = rig
    h.rig.app.dependency_overrides[get_meeting_bot_client] = lambda: bot
    path = f"/v1/meetings/{MEETING}/attend"
    assert h.rig.client.post(path, json={"owner": OWNER}).status_code == 422
    h.rig.as_user(SAM)
    assert h.rig.client.post(path, json={}).status_code == 404
    bot.attend.assert_not_awaited()


def test_FR_MTG_09_attend_route_completes_with_fake_worker(rig):
    from tilo_api.meeting_bot_rpc import get_meeting_bot_client

    h, _, bot = rig
    h.rig.app.dependency_overrides[get_meeting_bot_client] = lambda: bot
    response = h.rig.client.post(f"/v1/meetings/{MEETING}/attend", json={})
    assert response.status_code == 200
    assert response.json()["transcript"] is not None
    assert response.headers["cache-control"] == "no-store"
    bot.attend.assert_awaited_once()


def test_FR_MTG_09_failed_bot_releases_claim_without_notes(rig):
    h, w, bot = rig
    bot.attend.side_effect = RuntimeError("failed")
    with pytest.raises(RuntimeError):
        attend(h, w, bot)
    record = h.rig.real.meetings.get(ORG, MEETING).record
    assert record["status"] == "scheduled" and record["transcript"] is None


def test_FR_MTG_09_cancelled_attendance_releases_only_its_claim(rig):
    h, w, bot = rig
    host = h.rig.app.dependency_overrides[h.deps.get_meeting_host_client]()

    async def check():
        entered = asyncio.Event()

        async def pending(*_):
            entered.set()
            await asyncio.Event().wait()

        bot.attend.side_effect = pending
        task = asyncio.create_task(attend_meeting(w, h.store, h.art.store, host, bot, MEETING, lambda: h.rig.clock))
        await asyncio.wait_for(entered.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert h.rig.real.meetings.get(ORG, MEETING).record["status"] == "scheduled"

    asyncio.run(check())


def test_FR_MTG_09_concurrent_owner_clicks_launch_one_bot(rig):
    h, w, bot = rig
    host = h.rig.app.dependency_overrides[h.deps.get_meeting_host_client]()

    async def check():
        entered, release = asyncio.Event(), asyncio.Event()

        async def pending(*_):
            entered.set()
            await release.wait()
            return bot.attend.return_value

        bot.attend.side_effect = pending
        first = asyncio.create_task(attend_meeting(w, h.store, h.art.store, host, bot, MEETING, lambda: h.rig.clock))
        await asyncio.wait_for(entered.wait(), timeout=3)
        try:
            with pytest.raises(Refusal) as raised:
                await attend_meeting(w, h.store, h.art.store, host, bot, MEETING, lambda: h.rig.clock)
            assert raised.value.status_code == 409
        finally:
            release.set()
            await first
        assert bot.attend.await_count == 1

    asyncio.run(check())
