"""Draft Cloud Run route acceptance: injected workers and identity verification, no network."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from bot.cloud_run import create_app

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
AUDIENCE = "https://tilo-meet-bot-example.asia-southeast1.run.app"
CALLER = "tilo-api@example.iam.gserviceaccount.com"


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv("TILO_MEET_BOT_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("TILO_MEET_BOT_CALLER", CALLER)
    monkeypatch.setenv("LIVE", "1")
    claims = {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": CALLER, "email_verified": True}
    verifier = SimpleNamespace(verify=lambda *a: claims)
    attend = AsyncMock(
        return_value={
            "v": "1.0",
            "meeting_id": "mt_demo",
            "utterances": [{"id": "u0001", "speaker": "Person", "t_ms": 0, "text": "A note."}],
        }
    )
    client = TestClient(create_app(attend=attend, verifier=verifier, clock=lambda: NOW))
    return client, attend, claims


def body(*, expires=30):
    return {
        "join_url": "https://meet.google.com/abc-defg-hij",
        "expires_at": (NOW + timedelta(seconds=expires)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def headers():
    return {"Authorization": "Bearer " + "test" + "-identity"}


def test_FR_MTG_09_health_does_not_start_a_browser(setup):
    client, attend, _ = setup
    assert client.get("/health").status_code == 200
    attend.assert_not_awaited()


def test_FR_MTG_09_authenticated_launch_returns_contract_transcript_with_no_link(setup):
    client, attend, _ = setup
    response = client.post("/internal/meetings/mt_demo/attend", json=body(), headers=headers())
    assert response.status_code == 200
    assert response.json()["meeting_id"] == "mt_demo"
    assert "meet.google.com" not in response.text
    assert response.headers["cache-control"] == "no-store"
    attend.assert_awaited_once_with("mt_demo", body()["join_url"])


@pytest.mark.parametrize("change", [{"email": "other@example.test"}, {"email_verified": False}, {"aud": "other"}])
def test_FR_MTG_09_wrong_identity_never_launches(setup, change):
    client, attend, claims = setup
    claims.update(change)
    assert client.post("/internal/meetings/mt_demo/attend", json=body(), headers=headers()).status_code == 403
    attend.assert_not_awaited()


@pytest.mark.parametrize(
    "payload",
    [
        body(expires=-1),
        body(expires=61),
        {**body(), "owner": "injected"},
        {
            **body(),
            "join_url": "https://meet.google.com/abc-defg-hij?extra=yes",
        },
    ],
)
def test_FR_MTG_09_invalid_or_expired_request_never_launches_or_echoes_link(setup, payload):
    client, attend, _ = setup
    response = client.post("/internal/meetings/mt_demo/attend", json=payload, headers=headers())
    assert response.status_code == 422
    assert "meet.google.com" not in response.text
    attend.assert_not_awaited()


def test_FR_MTG_11_unset_live_switch_refuses_before_browser(setup, monkeypatch):
    client, attend, _ = setup
    monkeypatch.delenv("LIVE", raising=False)
    assert client.post("/internal/meetings/mt_demo/attend", json=body(), headers=headers()).status_code == 503
    attend.assert_not_awaited()


def test_FR_MTG_09_missing_identity_refuses_before_browser(setup):
    client, attend, _ = setup
    assert client.post("/internal/meetings/mt_demo/attend", json=body()).status_code == 401
    attend.assert_not_awaited()


@pytest.mark.parametrize("result", [{"meeting_id": "mt_wrong"}, {"utterances": [{"text": "malformed"}]}])
def test_FR_MTG_09_worker_result_must_match_meeting_and_transcript_contract(setup, result):
    client, attend, _ = setup
    attend.return_value.update(result)
    response = client.post("/internal/meetings/mt_demo/attend", json=body(), headers=headers())
    assert response.status_code == 502
    assert response.json() == {"detail": "Meeting bot failed"}


def test_FR_MTG_09_oversized_request_refused_without_browser(setup):
    client, attend, _ = setup
    response = client.post("/internal/meetings/mt_demo/attend", content="x" * 2049, headers=headers())
    assert response.status_code == 413
    attend.assert_not_awaited()


def test_FR_MTG_09_worker_exception_never_exposes_capability(setup):
    client, attend, _ = setup
    attend.side_effect = RuntimeError(body()["join_url"])
    response = client.post("/internal/meetings/mt_demo/attend", json=body(), headers=headers())
    assert response.status_code == 502
    assert "meet.google.com" not in response.text


def test_FR_MTG_09_worker_result_strips_pasted_meet_capabilities(setup):
    client, attend, _ = setup
    attend.return_value["utterances"][0]["text"] = body()["join_url"]
    response = client.post("/internal/meetings/mt_demo/attend", json=body(), headers=headers())
    assert response.status_code == 200
    assert "meet.google.com" not in response.text


def test_FR_MTG_09_caption_conversion_preserves_offsets_and_contract_bounds():
    from bot.cloud_worker import transcript_from_items

    items = [
        SimpleNamespace(speaker="Someone\nElse", text="hello\tworld", t=1.25),
        SimpleNamespace(speaker="", text=" \n ", t=-1),
    ]
    transcript = transcript_from_items("mt_demo", items)
    assert transcript["utterances"] == [{"id": "u0001", "speaker": "Someone Else", "t_ms": 1250, "text": "hello world"}]


@pytest.mark.parametrize("fail", [False, True])
def test_FR_MTG_09_worker_uses_guest_and_cleans_capture_files(monkeypatch, fail):
    from bot import cloud_worker, config

    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    configs = []

    class Session:
        def __init__(self, cfg, *args):
            configs.append(cfg)
            self.events = SimpleNamespace(echo=True)
            self.store = SimpleNamespace(items=[])

        async def run(self):
            assert self.events.echo is False
            if fail:
                raise RuntimeError("failed")

    monkeypatch.setattr(cloud_worker, "LiveSession", Session)
    if fail:
        with pytest.raises(RuntimeError):
            asyncio.run(cloud_worker.attend_meeting("mt_demo", body()["join_url"]))
    else:
        assert asyncio.run(cloud_worker.attend_meeting("mt_demo", body()["join_url"]))["utterances"] == []
    cfg = configs[0]
    assert cfg.guest and not cfg.record_audio and not cfg.auto_admit
    assert cfg.max_meeting_minutes == 45
    assert not cfg.out_dir.parent.exists()


def test_FR_MTG_09_disconnected_caller_cancels_and_awaits_browser_cleanup():
    from bot.cloud_run import attend_while_connected

    async def check():
        entered, cleaned = asyncio.Event(), asyncio.Event()

        async def attendance():
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        async def disconnected():
            await entered.wait()
            return {"type": "http.disconnect"}

        request = SimpleNamespace(receive=disconnected)
        with pytest.raises(ConnectionError):
            await attend_while_connected(request, attendance())
        assert cleaned.is_set()

    asyncio.run(check())
