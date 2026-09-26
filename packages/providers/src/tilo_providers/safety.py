"""tilo_providers.safety — the SafetyProvider layer (FR-INT-02, PRD 7.1,
16.3 item 2; ticket CC-SP-47). `check()` returns exactly
`{"flagged": bool, "reason": str | None}`; `check("", content=..., mime_type=...)`
screens a native PDF/PNG/JPEG, and any other media type raises `RequestError`
(fails closed, never `flagged: False`). `FakeSafetyProvider` is deterministic
and stateless; `SafetyRecordReplayProvider` mirrors `replay.RecordReplayProvider`
(EFF-01: replay by default, `LIVE=1` live, `+TILO_RECORD=1` writes a redacted
recording); `build_safety_provider` resolves the "safety" role in
config/models.yaml. The Model Armor adapter is not built yet (ADR-0003): with
`LIVE=1` its live factory refuses loudly."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tilo_contracts import ProvidersProfile

from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.interfaces import SafetyProvider, SafetyResult
from tilo_providers.replay import ReplayMissError, redact_strings

SAFETY_ROLE = "safety"
NATIVE_MIME_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})  # issue #47 item 2
_LIVE_SAFETY_PROVIDERS = frozenset({"model_armor"})
_INJECTION_MARKERS = (  # FakeSafetyProvider only: a fixed, case-insensitive phrase list
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "ignore the above instructions",
)


def native_mime_type(content: bytes | None, mime_type: str | None) -> str | None:
    """Validates the native-file arguments; returns the normalised media type,
    or None for a text-only check. Raises `RequestError` for anything that
    cannot be screened, so an unsupported file never passes as clean."""
    if content is None and mime_type is None:
        return None
    if content is None or mime_type is None:
        raise RequestError("FR-INT-02: a native-file safety check needs both content= and mime_type=")
    if not isinstance(content, bytes):
        raise RequestError("FR-INT-02: a native-file safety check needs content= as bytes")
    normalised = mime_type.strip().lower()
    if normalised not in NATIVE_MIME_TYPES:
        raise RequestError(f"FR-INT-02: the safety provider cannot screen media type {mime_type!r}; refused")
    return normalised


def as_safety_result(raw: Any) -> SafetyResult:
    """Accepts only the fixed result shape; anything else fails closed."""
    if (
        not isinstance(raw, dict)
        or set(raw) != {"flagged", "reason"}
        or not isinstance(raw["flagged"], bool)
        or not (raw["reason"] is None or isinstance(raw["reason"], str))
    ):
        raise ProviderError("FR-INT-02: safety provider returned a result that is not {flagged, reason}")
    return {"flagged": raw["flagged"], "reason": raw["reason"]}


class FakeSafetyProvider(SafetyProvider):
    """Deterministic, stateless (so thread-safe), no network. Flags text that
    contains a known prompt-injection marker; a supported native file has no
    extracted text, so it is always clean."""

    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> SafetyResult:
        native_mime_type(content, mime_type)
        lowered = " ".join(text.lower().split())
        for marker in _INJECTION_MARKERS:
            if marker in lowered:
                return {"flagged": True, "reason": f"prompt-injection marker: {marker!r}"}
        return {"flagged": False, "reason": None}


def safety_recording_key(
    role: str, profile_id: str, text: str, *, content: bytes | None = None, mime_type: str | None = None
) -> str:
    """A stable hash of (role, profile, text, file digest, media type): the
    recording's filename stem. Raw file bytes never reach the key or the file."""
    request: dict[str, Any] = {"text": text}
    if content is not None:
        request["content_sha256"] = hashlib.sha256(content).hexdigest()
        request["mime_type"] = mime_type
    normalised = json.dumps({"role": role, "profile": profile_id, "safety_request": request}, sort_keys=True)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


class SafetyRecordReplayProvider(SafetyProvider):
    def __init__(
        self, role: str, profile_id: str, live_factory: Callable[[], SafetyProvider], fixtures_dir: Path | str
    ) -> None:
        self._role = role
        self._profile_id = profile_id
        self._live_factory = live_factory
        self._live_provider: SafetyProvider | None = None
        self._lock = threading.Lock()  # intake calls check() from a threadpool (issue #47)
        self._recordings_dir = Path(fixtures_dir) / "safety-recordings" / role

    def _live(self) -> SafetyProvider:
        with self._lock:
            if self._live_provider is None:
                self._live_provider = self._live_factory()
            return self._live_provider

    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> SafetyResult:
        native = native_mime_type(content, mime_type)
        key = safety_recording_key(self._role, self._profile_id, text, content=content, mime_type=native)
        path = self._recordings_dir / f"{key}.json"

        if os.environ.get("LIVE") == "1":
            live = self._live()
            raw = live.check(text) if native is None else live.check(text, content=content, mime_type=native)
            result = as_safety_result(raw)
            if os.environ.get("TILO_RECORD") == "1":
                self._write_recording(path, key, result, live)
            return result

        if path.is_file():
            return as_safety_result(json.loads(path.read_text(encoding="utf-8"))["result"])

        raise ReplayMissError(
            f"EFF-01: no safety recording for role={self._role!r} profile={self._profile_id!r} key={key!r} "
            f"at {path} — run with LIVE=1 TILO_RECORD=1 to record one"
        )

    def _write_recording(self, path: Path, key: str, result: SafetyResult, live: SafetyProvider) -> None:
        payload = {"role": self._role, "profile": self._profile_id, "key": key, "result": dict(result)}
        # PRD 16.1 rule 4: the adapter's own redact() (a duck-typed adapter may lack one),
        # then the Authorization/Bearer backstop.
        redacted = redact_strings(payload, live if isinstance(live, SafetyProvider) else None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_safety_provider(config: ProvidersConfig, *, fixtures_dir: Path | str) -> SafetyProvider:
    """The "safety" role's primary profile: `provider: fake` gives
    `FakeSafetyProvider`; a known live provider gives record-and-replay."""
    if SAFETY_ROLE not in config.roles:
        raise ProviderConfigError(f"FR-INT-02: config/models.yaml has no {SAFETY_ROLE!r} role")
    profile_id = config.roles[SAFETY_ROLE].primary
    profile = config.profiles[profile_id]
    if profile.provider == "fake":
        return FakeSafetyProvider()
    if profile.provider not in _LIVE_SAFETY_PROVIDERS:
        raise ProviderConfigError(f"FR-INT-02: unknown safety provider {profile.provider!r} for {profile_id!r}")

    def live_factory() -> SafetyProvider:
        return _build_live_safety_provider(profile, profile_id)

    return SafetyRecordReplayProvider(SAFETY_ROLE, profile_id, live_factory, fixtures_dir)


def _build_live_safety_provider(profile: ProvidersProfile, profile_id: str) -> SafetyProvider:
    raise ProviderConfigError(
        f"FR-INT-02: the {profile.provider!r} safety adapter for {profile_id!r} is not built yet "
        "(ADR-0003: Google adapters stay on mocks and recordings); refusing to screen live"
    )
