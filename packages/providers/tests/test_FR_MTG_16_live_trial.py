"""Synthetic native-audio trial: no meeting capture and no network in tests."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest
from tilo_providers.errors import NotConfigured, ProviderError
from tilo_providers.live_trial import TrialConfig, run_trial


def settings():
    return TrialConfig(model="fake-live", prompt="Say ready.", timeout_s=1, max_audio_bytes=64, max_output_tokens=32)


def message(audio=b"\x00\x01", text="Ready", complete=True):
    return NS(
        server_content=NS(
            model_turn=NS(parts=[NS(inline_data=NS(data=audio, mime_type="audio/pcm;rate=24000"))]),
            output_transcription=NS(text=text),
            turn_complete=complete,
            interrupted=False,
        ),
        usage_metadata=None,
    )


class Session:
    def __init__(self, replies):
        self.replies, self.sent, self.closed = replies, [], False

    async def send_client_content(self, **kwargs):
        self.sent.append(kwargs)

    async def receive(self):
        for reply in self.replies:
            yield reply

    @asynccontextmanager
    async def connect(self, config):
        try:
            yield self
        finally:
            self.closed = True


def test_FR_MTG_16_default_replay_miss_never_builds_a_client(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)

    def forbidden(config):
        pytest.fail("opened a network client")

    with pytest.raises(ProviderError, match="recording unavailable"):
        asyncio.run(run_trial(settings(), tmp_path, session_factory=forbidden))


def test_FR_MTG_16_synthetic_record_then_replay_is_identical_and_offline_even_with_live(tmp_path, monkeypatch):
    session = Session([message()])
    recorded = asyncio.run(run_trial(settings(), tmp_path, record=True, session_factory=session.connect))
    assert session.closed and len(session.sent) == 1
    assert recorded["audio_pcm_b64"] and recorded["usage"] is None
    assert recorded["first_audio_ms"] >= 0 and recorded["turn_complete"]
    monkeypatch.setenv("LIVE", "1")
    replay = asyncio.run(run_trial(settings(), tmp_path, session_factory=lambda cfg: pytest.fail("live replay")))
    assert replay == recorded


def test_FR_MTG_16_recording_requires_users_live_switch_before_client_build(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    with pytest.raises(NotConfigured, match="LIVE"):
        asyncio.run(run_trial(settings(), tmp_path, record=True))
    assert not list(tmp_path.iterdir())


def test_FR_MTG_16_unpriced_live_trial_refuses_before_sdk_client(tmp_path, monkeypatch):
    from google import genai

    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "tilo-dev-test")
    monkeypatch.setenv("GOOGLE_LOCATION", "asia-southeast1")
    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("unpriced SDK client"))
    with pytest.raises(NotConfigured, match="price quote"):
        asyncio.run(run_trial(settings(), tmp_path, record=True))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("reply", [message(audio=b"x" * 66), message(audio=b"x"), message(audio=b"")])
def test_FR_MTG_16_invalid_or_over_cap_audio_closes_without_recording(tmp_path, reply):
    session = Session([reply])
    with pytest.raises(ProviderError):
        asyncio.run(run_trial(settings(), tmp_path, record=True, session_factory=session.connect))
    assert session.closed and not list(tmp_path.iterdir())


def test_FR_MTG_16_incomplete_response_is_not_a_successful_trial(tmp_path):
    session = Session([message(complete=False)])
    with pytest.raises(ProviderError, match="incomplete"):
        asyncio.run(run_trial(settings(), tmp_path, record=True, session_factory=session.connect))
    assert session.closed and not list(tmp_path.iterdir())


def test_FR_MTG_16_response_credentials_and_meet_links_are_not_recorded(tmp_path):
    session = Session([message(text="Bearer private-token https://meet.google.com/abc-defg-hij")])
    recorded = asyncio.run(run_trial(settings(), tmp_path, record=True, session_factory=session.connect))
    assert "private-token" not in recorded["text"] and "meet.google.com" not in recorded["text"]
    assert "private-token" not in next(tmp_path.iterdir()).read_text()


def test_FR_MTG_16_timeout_awaits_session_cleanup_without_a_recording(tmp_path):
    session = Session([])

    async def wait_forever():
        await asyncio.Event().wait()
        yield message()

    session.receive = wait_forever
    config = settings()
    config = TrialConfig(**{**config.__dict__, "timeout_s": 0.01})
    with pytest.raises(ProviderError, match="timed out"):
        asyncio.run(run_trial(config, tmp_path, record=True, session_factory=session.connect))
    assert session.closed and not list(tmp_path.iterdir())
