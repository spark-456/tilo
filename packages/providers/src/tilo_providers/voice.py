"""tilo_providers.voice: the bot's voice (FR-MTG-11), `SpeechProvider.synthesize` behind `config/voice.yaml`.

The vendor (`google-cloud-tts`, `google`, or the dev vendor `fake`; anything else fails start-up), the voice model id,
the voice name, the PCM sample rate, the region, the request timeout and the caps are config, never code in a service.
`google-cloud-tts` is the shipped voice: Cloud Text-to-Speech, a Chirp 3 HD voice, streamed (`cloud_tts_adapter`;
BQ-MTG11-13). `google` is Gemini speech output through the client the transcribe path uses (`google_speech_adapter`).
Both speak only with the live switch (`LIVE=1`, which only the user sets), so dev and CI never reach them. Audio is not
recorded for replay (it is large and not a transcript), so without the switch a Google voice raises `NotConfigured` and
the dev config names the deterministic fake. The model id appears only in the config file (PL-01); the PL-07 denylist
(`rules.deny` of `config/models.yaml`) applies to it. Cost: the Cloud TTS profile has a `character` unit_price in
`config/prices.yaml` (ADR-0029); `VoiceTiming.characters` is its unit count."""

from __future__ import annotations

import dataclasses
import fnmatch
import logging
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import NotConfigured, ProviderError
from tilo_providers.google_adapter import _LOCATION_RE
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.replay import is_live_mode
from tilo_providers.speech import FakeSpeechProvider, check_synth_request

log = logging.getLogger("tilo_providers.voice")
VOICE_VENDORS = frozenset(
    {"google-cloud-tts", "google", "fake"}
)  # D-1 (FR-MTG-11): Google only; `fake` is the dev vendor
SAMPLE_RATES = frozenset({16000, 22050, 24000, 44100, 48000})


LIVE_SAMPLE_RATE = 24000  # Gemini Live's native output rate: the flagged voice cannot be resampled here
_LIVE_KEYS = frozenset(
    {"enabled", "profile", "model", "voice", "location", "timeout_s", "max_output_tokens", "price_approved"}
)


@dataclass(frozen=True)
class LiveVoiceConfig:
    """The optional Gemini Live voice (M2, FR-MTG-11). `enabled` is the flag: off in the shipped config, so Chirp
    speaks. `price_approved` stays false until the user approves a current Live quote (PL-06); a live call refuses
    before it."""

    enabled: bool
    profile_id: str
    model: str
    voice: str
    location: str  # `global` (the Live endpoint), us, eu or a region
    timeout_s: float  # the deadline of one spoken reply
    max_output_tokens: int  # the model's own output cap for one reply
    price_approved: bool


class LiveVoiceMeter(Protocol):
    """The SEC-16 hook (BQ-M2-1): one spoken Live reply is one unit on the process's spend ledger. Called from the
    thread that drives the reply, so it must be thread-safe. `reserve` returns an opaque hold, or None when the ledger
    will not take the unit (capped uid, replay-only switch, no headroom); raising counts as a refusal (fail closed).
    `settle` gets that reply's own whole-number token counts (maybe empty); `release` frees a hold no model reached."""

    def reserve(self) -> object | None: ...
    def settle(self, hold: object, usage: Mapping[str, int]) -> None: ...
    def release(self, hold: object) -> None: ...


@dataclass(frozen=True)
class VoiceConfig:
    vendor: str
    profile_id: str
    model: str
    voice: str
    sample_rate: int  # Hz of the 16-bit mono little-endian PCM `synthesize` returns
    max_chars: int  # one call's text, enforced before any request (EFF-03)
    max_audio_bytes: int  # one call's returned audio, enforced as it arrives (a reply is a sentence or two)
    region: str = (
        "global"  # google-cloud-tts: `global` is the default endpoint, else `<region>-texttospeech.googleapis.com`
    )
    timeout_s: float = 15.0  # google-cloud-tts: the deadline of one streaming request
    live: LiveVoiceConfig | None = None  # the optional Gemini Live voice; None or enabled=False: Chirp stays the voice


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
    region = section.get("region", "global")
    if not (isinstance(region, str) and _LOCATION_RE.fullmatch(region)):
        raise ProviderConfigError(
            "FR-MTG-11: config/voice.yaml `region` must be global, us, eu or a region like asia-southeast1"
        )
    timeout = section.get("timeout_s", 15)
    if type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise ProviderConfigError("FR-MTG-11: config/voice.yaml `timeout_s` must be above 0 seconds and at most 60")
    models = Path(models_path) if models_path is not None else path.with_name("models.yaml")
    deny: list[str] = []
    if models.is_file():
        rules = (yaml.safe_load(models.read_text(encoding="utf-8")) or {}).get("rules") or {}
        deny = [g for g in rules.get("deny", []) if isinstance(g, str)]
    live = _live_section(section.get("live"), vendor, rate)
    for denied in (model, live.model if live else model):
        if any(fnmatch.fnmatchcase(denied, glob) for glob in deny):
            raise ProviderConfigError(f"PL-07: voice model id {denied!r} is denied by the rules in {models.name}")
    return VoiceConfig(
        vendor,
        profile,
        model,
        voice,
        rate,
        _positive_int(section.get("max_chars"), "max_chars"),
        _positive_int(section.get("max_audio_bytes"), "max_audio_bytes"),
        region,
        float(timeout),
        live,
    )


def _live_section(raw: Any, vendor: str, rate: int) -> LiveVoiceConfig | None:
    """The optional `voice.live` mapping (M2). Absent: None. Anything unknown or ill-typed fails start-up loudly."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - _LIVE_KEYS:
        raise ProviderConfigError(f"FR-MTG-11: config/voice.yaml `live` takes only {sorted(_LIVE_KEYS)}")
    where = "FR-MTG-11: config/voice.yaml `live."
    enabled, approved = raw.get("enabled", False), raw.get("price_approved", False)
    if type(enabled) is not bool or type(approved) is not bool:
        raise ProviderConfigError(f"{where}enabled` and `live.price_approved` must be true or false")
    profile, model, voice = raw.get("profile"), raw.get("model"), raw.get("voice")
    if not (isinstance(profile, str) and profile and isinstance(model, str) and model):
        raise ProviderConfigError(f"{where}profile` and `live.model` are required")
    if not (isinstance(voice, str) and check_voice_name(voice)):
        raise ProviderConfigError(f"{where}voice` must be a plain voice name")
    location = raw.get("location", "global")
    if not (isinstance(location, str) and _LOCATION_RE.fullmatch(location)):
        raise ProviderConfigError(f"{where}location` must be global, us, eu or a region like asia-southeast1")
    timeout = raw.get("timeout_s", 20)
    if type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise ProviderConfigError(f"{where}timeout_s` must be above 0 seconds and at most 60")
    tokens = raw.get("max_output_tokens")
    if type(tokens) is not int or not 0 < tokens <= 2048:
        raise ProviderConfigError(f"{where}max_output_tokens` must be a whole number from 1 to 2048")
    if enabled and (vendor == "fake" or rate != LIVE_SAMPLE_RATE):
        raise ProviderConfigError(f"{where}enabled` needs a Google vendor and sample_rate {LIVE_SAMPLE_RATE}")
    return LiveVoiceConfig(enabled, profile, model, voice, location, float(timeout), tokens, approved)


def character_metering_ready() -> bool:
    """True once the price loader can charge a `unit_price` (LW-05 gives `ProfilePriceQuote` a `unit`). Until then the
    `character` fee of the Chirp profile would be ignored, so the live voice refuses to build (BQ-MTG11-15)."""
    from tilo_providers import config  # noqa: PLC0415  (read at call time, so a later loader is seen)

    return "unit" in {f.name for f in dataclasses.fields(config.ProfilePriceQuote)}


def check_voice_name(voice: str) -> bool:
    try:
        check_synth_request("x", voice, {}, None)
    except ProviderError:
        return False
    return True


class GoogleVoiceProvider(SpeechProvider):
    """The Google voice: Cloud TTS Chirp 3 HD (streamed) or Gemini speech output, built lazily and only when the live
    switch is on. It does not transcribe (the speech provider does); a call without the switch is `NotConfigured`,
    never a silent fake. The config's caps apply to both vendors."""

    def __init__(self, config: VoiceConfig) -> None:
        self._config = config
        self._live: SpeechProvider | None = None

    def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
        raise NotConfigured("FR-MTG-11: the voice provider only synthesizes; transcribe through the speech provider")

    def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
        return b"".join(self.synthesize_stream(text, voice=voice, **kwargs))

    def synthesize_stream(self, text: str, *, voice: str | None = None, **kwargs: Any) -> Iterator[bytes]:
        """The reply's PCM piece by piece (the first piece as soon as the service sends it), under the audio cap."""
        text, voice = check_synth_request(text, voice, kwargs, self._config.max_chars)  # before anything else
        if not is_live_mode():
            raise NotConfigured("FR-MTG-11: the Google voice speaks only with LIVE=1, which only the user sets")
        if self._live is None:
            self._live = self._build_live()
        return self._capped(self._live.synthesize_stream(text, voice=voice))

    def _capped(self, pieces: Iterator[bytes]) -> Iterator[bytes]:
        total = 0
        try:
            for piece in pieces:
                total += len(piece)
                if total > self._config.max_audio_bytes:
                    raise ProviderError(
                        f"EFF-03: the voice audio is over the cap of {self._config.max_audio_bytes} bytes"
                    )
                yield piece
        finally:
            close = getattr(pieces, "close", None)
            if callable(close):
                close()

    def _build_live(self) -> SpeechProvider:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ProviderConfigError("FR-MTG-11: GOOGLE_CLOUD_PROJECT is not set; cannot speak live")
        if self._config.vendor == "google-cloud-tts":
            if not character_metering_ready():  # a live call the meter cannot charge is a silent overspend
                raise NotConfigured(
                    "FR-MTG-11: character metering needs LW-05 (BQ-MTG11-15); the Chirp voice stays off"
                )
            from tilo_providers.cloud_tts_adapter import GoogleCloudTTSProvider  # noqa: PLC0415  (dev never loads it)

            return GoogleCloudTTSProvider(
                voice=self._config.voice,
                sample_rate=self._config.sample_rate,
                project=project,
                region=self._config.region,
                timeout_s=self._config.timeout_s,
            )
        from tilo_providers.google_speech_adapter import GoogleSpeechProvider  # noqa: PLC0415  (dev never loads it)

        return GoogleSpeechProvider(
            model=self._config.model,
            project=project,
            location=os.environ.get("GOOGLE_LOCATION", "global"),
            tts_model=self._config.model,
            tts_voice=self._config.voice,
        )


def build_voice_provider(
    config: VoiceConfig, *, fixtures_dir: Path | str | None = None, meter: LiveVoiceMeter | None = None
) -> SpeechProvider:
    """`fake` gives the deterministic fake; `google-cloud-tts` and `google` the lazily built live voice; anything else
    is refused. `fixtures_dir` is accepted for symmetry with `build_speech_provider`: speech output is not recorded,
    except that the flagged Gemini Live voice (`voice.live.enabled`, M2) replays hand-written recordings from it.
    SEC-16 (BQ-M2-1): under the live switch the Live voice is built only with a `meter`, the process's ledger hook;
    without one the flag is ignored and Chirp is built, so a live reply no ledger counts cannot happen."""
    if config.vendor == "fake":
        return FakeSpeechProvider(max_chars=config.max_chars)
    if config.vendor not in VOICE_VENDORS:
        raise ProviderConfigError(f"FR-MTG-11: voice vendor {config.vendor!r} is not allowed; Google only")
    if config.live is not None and config.live.enabled:  # M2: the flag alone selects it; off, Chirp stays the voice
        if meter is None and is_live_mode():
            log.warning("the Live voice is flagged on but this process has no spend meter: Chirp is the voice")
            return GoogleVoiceProvider(config)
        from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider  # noqa: PLC0415

        return GeminiLiveVoiceProvider(config, fixtures_dir=fixtures_dir, meter=meter)
    return GoogleVoiceProvider(config)
