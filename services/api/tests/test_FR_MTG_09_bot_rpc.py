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
