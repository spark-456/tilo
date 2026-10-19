"""Fake private service transport; no metadata, browsers or paid calls."""

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from tilo_api.meeting_bot_rpc import MeetingBotRpc
from tilo_contracts import MeetingJoin

BASE = "https://tilo-meet-bot.example.run.app"
JOIN = MeetingJoin(join_url="https://meet.google.com/abc-defg-hij", expires_at="2026-10-11T12:30:00.000Z")
TRANSCRIPT = {"v": "1.0", "meeting_id": "mt_demo", "utterances": []}


def client(handler):
    return MeetingBotRpc(BASE, token_for=lambda _: "test-identity", transport=httpx.MockTransport(handler))


def test_FR_MTG_09_bot_rpc_passes_identity_and_closed_capture(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=TRANSCRIPT, headers={"X-Tilo-Meeting-End-Reason": "completed"})

    result = asyncio.run(client(handle).attend("mt_demo", JOIN))
    assert result.transcript.meeting_id == "mt_demo" and result.reason == "completed"
    assert len(seen) == 1 and seen[0].headers["authorization"] == "Bearer test-identity"
    assert seen[0].url.path == "/internal/meetings/mt_demo/attend"


def test_FR_MTG_09_bot_rpc_unset_live_never_calls_transport(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)

    def refuse(_):
        raise AssertionError("called")

    with pytest.raises(HTTPException) as raised:
        asyncio.run(client(refuse).attend("mt_demo", JOIN))
    assert raised.value.detail == "bot_not_enabled"


@pytest.mark.parametrize(
    "status,document,reason",
    [
        (302, TRANSCRIPT, "completed"),
        (200, {**TRANSCRIPT, "meeting_id": "mt_other"}, "completed"),
        (200, TRANSCRIPT, "unknown"),
        (200, {"secret": JOIN.join_url}, "completed"),
    ],
)
def test_FR_MTG_09_bot_rpc_invalid_capture_has_fixed_error_no_capability(monkeypatch, status, document, reason):
    monkeypatch.setenv("LIVE", "1")
    rpc = client(lambda _: httpx.Response(status, json=document, headers={"X-Tilo-Meeting-End-Reason": reason}))
    with pytest.raises(HTTPException) as raised:
        asyncio.run(rpc.attend("mt_demo", JOIN))
    assert raised.value.detail == "bot_unavailable"
    assert "meet.google.com" not in str(raised.value)


# --- MEET-SIMPLE: a cold bot is woken and a launch it never started is asked again, never one it ran ---


def quick(handler, pauses=None):
    async def sleep(seconds):
        if pauses is not None:
            pauses.append(seconds)

    return MeetingBotRpc(BASE, token_for=lambda _: "test-identity", transport=httpx.MockTransport(handler), sleep=sleep)


def test_FR_MTG_09_MEET_SIMPLE_attend_repeats_while_the_bot_is_cold_then_succeeds(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    calls, pauses = [], []

    def handle(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(502, text="<html>Bad Gateway</html>")
        if len(calls) == 2:
            return httpx.Response(503, text="upstream connect error")
        return httpx.Response(200, json=TRANSCRIPT, headers={"X-Tilo-Meeting-End-Reason": "completed"})

    result = asyncio.run(quick(handle, pauses).attend("mt_demo", JOIN))
    assert result.reason == "completed"
    assert calls == ["/internal/meetings/mt_demo/attend"] * 3
    assert len(pauses) == 2 and pauses == sorted(pauses), "it backs off between tries"


def test_FR_MTG_09_MEET_SIMPLE_attend_repeats_after_a_connection_error(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    calls = []

    def handle(request):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("cold")
        return httpx.Response(200, json=TRANSCRIPT, headers={"X-Tilo-Meeting-End-Reason": "removed"})

    assert asyncio.run(quick(handle).attend("mt_demo", JOIN)).reason == "removed"
    assert len(calls) == 3


@pytest.mark.parametrize(
    "status,detail", [(502, "Meeting bot failed"), (504, "Meeting duration exceeded"), (409, "x"), (422, "x")]
)
def test_FR_MTG_09_MEET_SIMPLE_attend_never_repeats_a_launch_the_bot_answered(monkeypatch, status, detail):
    monkeypatch.setenv("LIVE", "1")
    calls = []

    def handle(request):
        calls.append(1)
        return httpx.Response(status, json={"detail": detail})

    with pytest.raises(HTTPException) as raised:
        asyncio.run(quick(handle).attend("mt_demo", JOIN))
    assert raised.value.detail == "bot_unavailable" and len(calls) == 1


@pytest.mark.parametrize(
    "status,detail",
    [
        (502, "browser_unavailable"),
        (409, "meeting_requires_sign_in"),
        (409, "meeting_join_failed"),
    ],
)
def test_P0_MEET_JOIN_bot_rpc_preserves_known_reason_codes(monkeypatch, status, detail):
    monkeypatch.setenv("LIVE", "1")
    rpc = quick(lambda _: httpx.Response(status, json={"detail": detail}))
    with pytest.raises(HTTPException) as raised:
        asyncio.run(rpc.attend("mt_demo", JOIN))
    assert raised.value.status_code == status
    assert raised.value.detail == detail


def test_FR_MTG_09_MEET_SIMPLE_attend_gives_up_after_the_budget(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    calls, spent = [], []

    def handle(request):
        calls.append(1)
        return httpx.Response(502, text="bad gateway")

    rpc = quick(handle, spent)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(rpc.attend("mt_demo", JOIN))
    assert raised.value.detail == "bot_unavailable"
    assert 2 <= len(calls) <= 20


def test_FR_MTG_09_MEET_SIMPLE_wake_reads_health_until_it_answers(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path, request.headers["authorization"]))
        return httpx.Response(502 if len(seen) < 3 else 200, json={"status": "ok"})

    assert asyncio.run(quick(handle).wake()) is True
    assert seen == [("GET", "/health", "Bearer test-identity")] * 3


def test_FR_MTG_09_MEET_SIMPLE_wake_is_off_without_live_and_never_raises(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    assert asyncio.run(quick(lambda _: (_ for _ in ()).throw(AssertionError("called"))).wake()) is False
    monkeypatch.setenv("LIVE", "1")
    assert asyncio.run(quick(lambda r: httpx.Response(500)).wake(budget_s=0)) is False
