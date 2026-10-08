"""tilo_providers.speech — the SpeechProvider layer (FR-MTG-17, FR-MTG-11; PRD 6.4). `transcribe(audio, media_type=...,
language=None)` returns exactly `{"segments": [{"speaker", "start_ms", "text"}]}`. The vendor and model are config
(`config/speech.yaml`), Google only (D-1: Gemini audio, `google_speech_adapter`); `FakeSpeechProvider` is the dev
vendor and `SpeechRecordReplayProvider` mirrors `safety.SafetyRecordReplayProvider` (EFF-01: replay by default,
`LIVE=1` live, `+TILO_RECORD=1` writes a redacted recording; raw audio never reaches a key or a file).
`build_speech_provider` resolves a `SpeechConfig`; any other vendor fails loudly."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from tilo_providers.config import ProviderConfigError, refuse_dev_only
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.interfaces import SpeechProvider
from tilo_providers.replay import Redactor, ReplayMissError, is_live_mode, redact_strings

SPEECH_VENDORS = frozenset({"google", "fake"})  # D-1 (FR-MTG-11): Google only; `fake` is the dev vendor
_LANGUAGE_RE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?")  # a BCP-47 hint; it reaches a prompt, so a strict shape
_SEGMENT_KEYS = frozenset({"speaker", "start_ms", "text"})


@dataclass(frozen=True)
class SpeechConfig:
    vendor: str
    profile_id: str
    model: str
    max_bytes: int  # one upload, enforced before any request (EFF-03)
    max_duration_ms: int  # read by the ingest (tilo_planning.recording): the last utterance offset


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProviderConfigError(f"FR-MTG-17: config/speech.yaml `{name}` must be a positive whole number")
    return value


def load_speech_config(path: Path | str, *, models_path: Path | str | None = None) -> SpeechConfig:
    """Loads and validates `config/speech.yaml`; the PL-07 denylist is `rules.deny` of `models_path` (default: the
    `models.yaml` beside it; no such file means no deny rule). Fails loudly rather than starting on a bad config."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ProviderConfigError(f"could not read {path}: {type(error).__name__}") from None
    section = raw.get("speech") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        raise ProviderConfigError(f"{path} must have a `speech` mapping")
    vendor = section.get("vendor")
    if vendor not in SPEECH_VENDORS:
        raise ProviderConfigError(f"FR-MTG-11: speech vendor {vendor!r} is not allowed; only {sorted(SPEECH_VENDORS)}")
    profile, model = section.get("profile"), section.get("model")
    if not (isinstance(profile, str) and profile and isinstance(model, str) and model):
        raise ProviderConfigError("FR-MTG-17: config/speech.yaml needs a `profile` and a `model`")
    models = Path(models_path) if models_path is not None else path.with_name("models.yaml")
    deny: list[str] = []
    if models.is_file():
        rules = (yaml.safe_load(models.read_text(encoding="utf-8")) or {}).get("rules") or {}
        deny = [g for g in rules.get("deny", []) if isinstance(g, str)]
    if any(fnmatch.fnmatchcase(model, glob) for glob in deny):
        raise ProviderConfigError(f"PL-07: speech model id {model!r} is denied by the rules in {models.name}")
    max_bytes = _positive_int(section.get("max_bytes"), "max_bytes")
    return SpeechConfig(
        vendor, profile, model, max_bytes, _positive_int(section.get("max_duration_ms"), "max_duration_ms")
    )


def as_speech_result(raw: Any) -> dict[str, Any]:
    """The fixed result shape, or `ProviderError` (fails closed; the message never quotes the content)."""
    segments = raw.get("segments") if isinstance(raw, dict) and set(raw) == {"segments"} else None
    if not isinstance(segments, list):
        raise ProviderError("FR-MTG-17: the speech provider returned a result that is not {segments: [...]}")
    clean = []
    for item in segments:
        ok = (
            isinstance(item, dict)
            and set(item) == _SEGMENT_KEYS
            and isinstance(item["speaker"], str)
            and isinstance(item["text"], str)
            and type(item["start_ms"]) is int
            and item["start_ms"] >= 0
        )
        if not ok:
            raise ProviderError("FR-MTG-17: the speech provider returned a malformed segment")
        clean.append({key: item[key] for key in ("speaker", "start_ms", "text")})
    return {"segments": clean}


def check_request(audio: Any, kwargs: dict[str, Any], max_bytes: int | None) -> tuple[str, str | None]:
    """Validates one `transcribe` call before anything is looked up or sent; returns (media_type, language)."""
    extra = set(kwargs) - {"media_type", "language"}
    media_type, language = kwargs.get("media_type"), kwargs.get("language")
    if extra or not isinstance(media_type, str) or not media_type.strip():
        raise RequestError("FR-MTG-17: transcribe needs media_type= (and only media_type=, language=)")
    if language is not None and not (isinstance(language, str) and _LANGUAGE_RE.fullmatch(language)):
        raise RequestError("FR-MTG-17: language= must be a language tag such as 'en' or 'en-GB'")
    if not isinstance(audio, bytes) or not audio:
        raise RequestError("FR-MTG-17: transcribe needs the recording as non-empty bytes")
    if max_bytes is not None and len(audio) > max_bytes:
        raise RequestError(f"EFF-03: the recording is over the speech cap of {max_bytes} bytes")
    return media_type.strip().lower(), language


class FakeSpeechProvider(SpeechProvider):
    """Deterministic, no network: the given segments, or one segment derived from the audio's digest. Refused when
    `LIVE=1` or deployed (a fake transcript must never reach a real meeting)."""

    def __init__(self, segments: list[dict[str, Any]] | None = None) -> None:
        refuse_dev_only("fake-speech")
        self._segments = as_speech_result({"segments": segments})["segments"] if segments is not None else None

    def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
        media_type, _ = check_request(audio, kwargs, None)
        if self._segments is not None:
            return {"segments": [dict(s) for s in self._segments]}
        digest = hashlib.sha256(audio).hexdigest()[:8]
        return {"segments": [{"speaker": "Speaker 1", "start_ms": 0, "text": f"[fake:{digest}] {media_type}"}]}


def speech_recording_key(profile_id: str, audio: bytes, media_type: str, language: str | None) -> str:
    """A stable hash of (profile, audio digest, media type, language): the recording's filename stem."""
    request = {"audio_sha256": hashlib.sha256(audio).hexdigest(), "media_type": media_type, "language": language}
    normalised = json.dumps({"role": "speech", "profile": profile_id, "speech_request": request}, sort_keys=True)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


class SpeechRecordReplayProvider(SpeechProvider):
    def __init__(
        self, profile_id: str, live_factory: Callable[[], SpeechProvider], fixtures_dir: Path | str, max_bytes: int
    ) -> None:
        self._profile_id, self._live_factory, self._max_bytes = profile_id, live_factory, max_bytes
        self._live_provider: SpeechProvider | None = None
        self._dir = Path(fixtures_dir) / "speech-recordings"

    def transcribe(self, audio: bytes, **kwargs: Any) -> Any:
        media_type, language = check_request(audio, kwargs, self._max_bytes)  # before the lookup, replay or live
        key = speech_recording_key(self._profile_id, audio, media_type, language)
        path = self._dir / f"{key}.json"
        if is_live_mode():
            if self._live_provider is None:
                self._live_provider = self._live_factory()
            result = as_speech_result(self._live_provider.transcribe(audio, **kwargs))
            if os.environ.get("TILO_RECORD") == "1":
                self._write(path, key, result, self._live_provider)
            return result
        if path.is_file():
            return self._read(path)
        raise ReplayMissError(
            f"EFF-01: no speech recording for profile={self._profile_id!r} key={key!r} at {path} "
            "- run with LIVE=1 TILO_RECORD=1 to record one"
        )

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return as_speech_result(data["result"])
        except (OSError, ValueError, KeyError, TypeError):  # a corrupt or hand-edited recording fails closed
            raise ProviderError(f"FR-MTG-17: speech recording {path.name} is unreadable or malformed") from None

    def _write(self, path: Path, key: str, result: dict[str, Any], live: SpeechProvider) -> None:
        payload = {"role": "speech", "profile": self._profile_id, "key": key, "result": result}
        # PRD 16.1 rule 4: the adapter's own redact() when it has one, then the Authorization/Bearer backstop.
        redactor = cast(Redactor, live) if callable(getattr(live, "redact", None)) else None
        redacted = redact_strings(payload, redactor)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{key}.", suffix=".tmp")
        try:  # atomic: a crash or a concurrent reader never sees a truncated recording
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(redacted, indent=2, sort_keys=True) + "\n")
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def build_speech_provider(config: SpeechConfig, *, fixtures_dir: Path | str) -> SpeechProvider:
    """`fake` gives the fake; `google` gives record-and-replay whose live adapter (Gemini audio on Agent Platform)
    is built lazily, only when a call goes live (`LIVE=1`); anything else is refused."""
    if config.vendor == "fake":
        return FakeSpeechProvider()
    if config.vendor != "google":
        raise ProviderConfigError(f"FR-MTG-11: speech vendor {config.vendor!r} is not allowed; Google only")

    def live_factory() -> SpeechProvider:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ProviderConfigError("FR-MTG-17: GOOGLE_CLOUD_PROJECT is not set; cannot transcribe live")
        from tilo_providers.google_speech_adapter import GoogleSpeechProvider  # noqa: PLC0415  (replay never loads it)

        return GoogleSpeechProvider(
            model=config.model, project=project, location=os.environ.get("GOOGLE_LOCATION", "global")
        )

    return SpeechRecordReplayProvider(config.profile_id, live_factory, fixtures_dir, config.max_bytes)
