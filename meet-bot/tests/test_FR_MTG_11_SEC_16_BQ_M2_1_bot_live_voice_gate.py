"""FR-MTG-11 (M2b), SEC-16, BQ-M2-1: the bot never speaks with the Live voice unless the process hands `ProviderTTS` a
spend hook. Without one, under the user's live switch, the voice is built as Chirp; a hook is passed through to the
provider layer untouched; a refusing ledger is a permanent refusal, so the bot's local voice speaks for the meeting and
the Live provider is never reached. No network, no SDK, no real audio."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider
from tilo_providers.voice import GoogleVoiceProvider

from bot import providers
from bot.providers import ProviderTTS, load_voice_config, repo_root
from bot.tts import TTSError

ROOT = repo_root()


def _flagged(tmp_path: Path):
    raw = yaml.safe_load((ROOT / "config" / "voice.yaml").read_text(encoding="utf-8"))
    raw["voice"]["live"]["enabled"] = True
    raw["voice"]["live"]["price_approved"] = True
    path = tmp_path / "voice.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_voice_config(path, models_path=ROOT / "config" / "models.yaml")


class Ledger:
    def __init__(self, *, refuse: bool) -> None:
        self.refuse, self.calls = refuse, []

    def reserve(self):
        self.calls.append("reserve")
        return None if self.refuse else "hold"

    def settle(self, hold, usage):
        self.calls.append("settle")

    def release(self, hold):
        self.calls.append("release")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)


def test_FR_MTG_11_SEC_16_BQ_M2_1_the_flag_and_the_switch_without_a_hook_build_chirp_not_the_live_voice(
    tmp_path, monkeypatch
):
    config = _flagged(tmp_path)
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "tilo-dev-test")
    assert isinstance(ProviderTTS(config=config).provider, GoogleVoiceProvider)
    assert isinstance(ProviderTTS(config=config, meter=Ledger(refuse=False)).provider, GeminiLiveVoiceProvider)


def test_FR_MTG_11_SEC_16_BQ_M2_1_the_hook_reaches_the_provider_layer_and_a_refusal_falls_back_for_the_meeting(
    tmp_path,
):
    config, ledger, opened = _flagged(tmp_path), Ledger(refuse=True), []

    @asynccontextmanager
    async def connect():
        opened.append(1)
        yield SimpleNamespace()

    live = GeminiLiveVoiceProvider(config, fixtures_dir=None, session_factory=lambda settings: connect(), meter=ledger)
    tts = ProviderTTS(provider=live, config=config)

    async def speak():
        return [piece async for piece in tts.stream("The release is Friday.")]

    with pytest.raises(TTSError) as caught:
        asyncio.run(speak())
    assert caught.value.permanent and ledger.calls == ["reserve"] and opened == []


def test_FR_MTG_11_SEC_16_BQ_M2_1_provider_tts_forwards_its_meter_to_the_voice_factory(tmp_path, monkeypatch):
    seen = {}

    def spy(config, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(providers, "build_voice_provider", spy)
    hook = Ledger(refuse=False)
    ProviderTTS(config=_flagged(tmp_path), meter=hook)
    assert seen["meter"] is hook
