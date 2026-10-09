"""tilo_providers.voice: the bot's voice (FR-MTG-11), `SpeechProvider.synthesize` behind `config/voice.yaml`.

The vendor (`google`, or the dev vendor `fake`; anything else fails start-up), the voice model id, the voice name, the
PCM sample rate and the caps are config, never code in a service. `google` is Gemini speech output through the same
client the transcribe path uses (`google_speech_adapter`); it speaks only with the live switch (`LIVE=1`, which only
the user sets), so dev and CI never reach it. Audio is not recorded for replay (it is large and not a transcript), so
without the switch the Google voice raises `NotConfigured` and the dev config names the deterministic fake. The model
id appears only in the config file (PL-01); the PL-07 denylist (`rules.deny` of `config/models.yaml`) applies to it.
Cost: `config/prices.yaml` has no price for audio OUTPUT (BQ-MTG11-3), so a live voice call is not metered here."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import NotConfigured, ProviderError
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.replay import is_live_mode
from tilo_providers.speech import FakeSpeechProvider, check_synth_request

VOICE_VENDORS = frozenset({"google", "fake"})  # D-1 (FR-MTG-11): Google only; `fake` is the dev vendor
SAMPLE_RATES = frozenset({16000, 22050, 24000, 44100, 48000})


@dataclass(frozen=True)
class VoiceConfig:
    vendor: str
    profile_id: str
    model: str
    voice: str
    sample_rate: int  # Hz of the 16-bit mono little-endian PCM `synthesize` returns
    max_chars: int  # one call's text, enforced before any request (EFF-03)
    max_audio_bytes: int  # one call's returned audio, enforced after it (a reply is a sentence or two)


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProviderConfigError(f"FR-MTG-11: config/voice.yaml `{name}` must be a positive whole number")
    return value


def load_voice_config(path: Path | str, *, models_path: Path | str | None = None) -> VoiceConfig:
    """Loads and validates `config/voice.yaml`; the PL-07 denylist is `rules.deny` of `models_path` (default: the
    `models.yaml` beside it). Fails loudly rather than starting on a bad config."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ProviderConfigError(f"could not read {path}: {type(error).__name__}") from None
    section = raw.get("voice") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        raise ProviderConfigError(f"{path} must have a `voice` mapping")
    vendor = section.get("vendor")
    if vendor not in VOICE_VENDORS:
        raise ProviderConfigError(f"FR-MTG-11: voice vendor {vendor!r} is not allowed; only {sorted(VOICE_VENDORS)}")
    profile, model, voice = section.get("profile"), section.get("model"), section.get("voice")
    if not (isinstance(profile, str) and profile and isinstance(model, str) and model):
        raise ProviderConfigError("FR-MTG-11: config/voice.yaml needs a `profile` and a `model`")
    if not (isinstance(voice, str) and check_voice_name(voice)):
        raise ProviderConfigError("FR-MTG-11: config/voice.yaml `voice` must be a plain voice name")
    rate = section.get("sample_rate")
    if type(rate) is not int or rate not in SAMPLE_RATES:
        raise ProviderConfigError(f"FR-MTG-11: config/voice.yaml `sample_rate` must be one of {sorted(SAMPLE_RATES)}")
    models = Path(models_path) if models_path is not None else path.with_name("models.yaml")
    deny: list[str] = []
    if models.is_file():
        rules = (yaml.safe_load(models.read_text(encoding="utf-8")) or {}).get("rules") or {}
        deny = [g for g in rules.get("deny", []) if isinstance(g, str)]
    if any(fnmatch.fnmatchcase(model, glob) for glob in deny):
        raise ProviderConfigError(f"PL-07: voice model id {model!r} is denied by the rules in {models.name}")
    return VoiceConfig(
        vendor,
        profile,
        model,
        voice,
        rate,
        _positive_int(section.get("max_chars"), "max_chars"),
        _positive_int(section.get("max_audio_bytes"), "max_audio_bytes"),
    )


def check_voice_name(voice: str) -> bool:
    try:
        check_synth_request("x", voice, {}, None)
    except ProviderError:
        return False
    return True


class GoogleVoiceProvider(SpeechProvider):
    """The Google voice: Gemini speech output, built lazily and only when the live switch is on. It does not transcribe
    (the speech provider does); a call without the switch is `NotConfigured`, never a silent fake."""

    def __init__(self, config: VoiceConfig) -> None:
        self._config = config
        self._live: SpeechProvider | None = None

    def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
        raise NotConfigured("FR-MTG-11: the voice provider only synthesizes; transcribe through the speech provider")

    def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
        text, voice = check_synth_request(text, voice, kwargs, self._config.max_chars)  # before anything else
        if not is_live_mode():
            raise NotConfigured("FR-MTG-11: the Google voice speaks only with LIVE=1, which only the user sets")
        if self._live is None:
            self._live = self._build_live()
        pcm = self._live.synthesize(text, voice=voice)
        if len(pcm) > self._config.max_audio_bytes:
            raise ProviderError(f"EFF-03: the voice audio is over the cap of {self._config.max_audio_bytes} bytes")
        return pcm

    def _build_live(self) -> SpeechProvider:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ProviderConfigError("FR-MTG-11: GOOGLE_CLOUD_PROJECT is not set; cannot speak live")
        from tilo_providers.google_speech_adapter import GoogleSpeechProvider  # noqa: PLC0415  (dev never loads it)

        return GoogleSpeechProvider(
            model=self._config.model,
            project=project,
            location=os.environ.get("GOOGLE_LOCATION", "global"),
            tts_model=self._config.model,
            tts_voice=self._config.voice,
        )


def build_voice_provider(config: VoiceConfig, *, fixtures_dir: Path | str | None = None) -> SpeechProvider:
    """`fake` gives the deterministic fake; `google` the lazily built live voice; anything else is refused.
    `fixtures_dir` is accepted for symmetry with `build_speech_provider`: speech output is not recorded."""
    if config.vendor == "fake":
        return FakeSpeechProvider(max_chars=config.max_chars)
    if config.vendor != "google":
        raise ProviderConfigError(f"FR-MTG-11: voice vendor {config.vendor!r} is not allowed; Google only")
    return GoogleVoiceProvider(config)
