"""tilo_providers.safety — the SafetyProvider layer (FR-INT-02, PRD 7.1,
16.3 item 2; ticket CC-SP-47). `check()` returns exactly
`{"flagged": bool, "reason": str | None}`; `check("", content=..., mime_type=...)`
screens a native PDF/PNG/JPEG, and any other media type raises `RequestError`
(fails closed, never `flagged: False`). `FakeSafetyProvider` is deterministic
and stateless; `SafetyRecordReplayProvider` mirrors `replay.RecordReplayProvider`
(EFF-01: replay by default, `LIVE=1` live, `+TILO_RECORD=1` writes a redacted
recording); `build_safety_provider` resolves the "safety" role in
config/models.yaml. With `LIVE=1` the `model_armor` profile builds
`model_armor_adapter.ModelArmorSafetyProvider` (lazily; a missing project refuses loudly)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tilo_contracts import ProvidersProfile

from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.interfaces import NATIVE_MIME_TYPES, SafetyProvider, SafetyResult, native_mime_type
from tilo_providers.replay import ReplayMissError, is_live_mode, redact_strings

__all__ = ["NATIVE_MIME_TYPES", "native_mime_type"]  # the media-type gate now lives in interfaces.py

SAFETY_ROLE = "safety"
_LIVE_SAFETY_PROVIDERS = frozenset({"model_armor"})
# A live adapter's free-text reason can quote the screened content or echo a secret, so it is
# never recorded or returned verbatim: only these fixed categories leave this module (#103).
SAFETY_REASON_CATEGORIES = frozenset({"prompt_injection", "sensitive_data", "unsafe_content", "other"})
_REASON_CATEGORY_PATTERNS = (  # first match wins; anything else is "other"
    ("prompt_injection", re.compile(r"injection|jailbreak|instruction", re.I)),
    ("sensitive_data", re.compile(r"sensitive|\bpii\b|personal data|credential|secret|\bdlp\b", re.I)),
    ("unsafe_content", re.compile(r"hate|harass|violen|sexual|dangerous|harm|unsafe|toxic", re.I)),
)
_INJECTION_MARKERS = (  # FakeSafetyProvider only: a fixed, case-insensitive phrase list
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "ignore the above instructions",
)


def estimate_safety_tokens(text: str, content: bytes | None = None) -> int:
    """A deliberately high token estimate (about one token per 3 bytes, text plus file): errs toward refusing."""
    return math.ceil(len(text.encode("utf-8")) / 3) + (math.ceil(len(content) / 3) if content is not None else 0)


def enforce_input_cap(text: str, content: bytes | None, max_input_tokens: int | None) -> None:
    """EFF-03: an input over the role's `max_input_tokens` is refused before any lookup or request, never sent
    or screened as clean (fails closed). `None` means the role sets no cap."""
    if max_input_tokens is not None and estimate_safety_tokens(text, content) > max_input_tokens:
        raise RequestError(f"EFF-03: the safety input is over the role's max_input_tokens cap of {max_input_tokens}")


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


def reason_category(reason: str | None) -> str | None:
    """Maps a live adapter's reason onto `SAFETY_REASON_CATEGORIES` (None stays None)."""
    if reason is None:
        return None
    if reason in SAFETY_REASON_CATEGORIES:
        return reason
    for category, pattern in _REASON_CATEGORY_PATTERNS:
        if pattern.search(reason):
            return category
    return "other"


def _categorised(raw: Any) -> SafetyResult:
    result = as_safety_result(raw)
    return {"flagged": result["flagged"], "reason": reason_category(result["reason"]) if result["flagged"] else None}


class FakeSafetyProvider(SafetyProvider):
    """Deterministic, stateless (so thread-safe), no network. Flags text that
    contains a known prompt-injection marker; a supported native file has no
    extracted text, so it is always clean."""

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult:
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
        self,
        role: str,
        profile_id: str,
        live_factory: Callable[[], SafetyProvider],
        fixtures_dir: Path | str,
        max_input_tokens: int | None = None,
        force_replay: bool = False,
    ) -> None:
        self._force_replay = force_replay  # SEC-15: the caller decided this replays: never live, never records
        self._max_input_tokens = max_input_tokens
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

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult:
        enforce_input_cap(text, content, self._max_input_tokens)  # EFF-03: before the lookup, replay or live
        native = mime_type  # already gated and normalised by SafetyProvider.check
        key = safety_recording_key(self._role, self._profile_id, text, content=content, mime_type=native)
        path = self._recordings_dir / f"{key}.json"

        if is_live_mode() and not self._force_replay:
            live = self._live()
            raw = live.check(text) if native is None else live.check(text, content=content, mime_type=native)
            result = _categorised(raw)
            if os.environ.get("TILO_RECORD") == "1":
                self._write_recording(path, key, result, live)
            return result

        if path.is_file():
            return self._read_recording(path)

        raise ReplayMissError(
            f"EFF-01: no safety recording for role={self._role!r} profile={self._profile_id!r} key={key!r} "
            f"at {path} — run with LIVE=1 TILO_RECORD=1 to record one"
        )

    @staticmethod
    def _read_recording(path: Path) -> SafetyResult:
        """A corrupt, truncated or hand-edited recording is a `ProviderError`, never a
        JSONDecodeError/KeyError/TypeError (fails closed; the message names the file only)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # JSONDecodeError and UnicodeDecodeError are ValueErrors
            raise ProviderError(
                f"FR-INT-02: safety recording {path.name} is unreadable ({type(exc).__name__})"
            ) from None
        if not isinstance(data, dict) or "result" not in data:
            raise ProviderError(f"FR-INT-02: safety recording {path.name} has no result")
        try:
            return _categorised(data["result"])
        except ProviderError:
            raise ProviderError(f"FR-INT-02: safety recording {path.name} has a malformed result") from None

    def _write_recording(self, path: Path, key: str, result: SafetyResult, live: SafetyProvider) -> None:
        payload = {"role": self._role, "profile": self._profile_id, "key": key, "result": dict(result)}
        # PRD 16.1 rule 4: the adapter's own redact() (a duck-typed adapter may lack one),
        # then the Authorization/Bearer backstop.
        redacted = redact_strings(payload, live if isinstance(live, SafetyProvider) else None)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: a temp file in the same directory, then os.replace, so a crash or a concurrent
        # reader never sees a truncated recording.
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{key}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(redacted, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def build_safety_provider(
    config: ProvidersConfig, *, fixtures_dir: Path | str, force_replay: bool = False
) -> SafetyProvider:
    """The "safety" role's primary profile: `provider: fake` gives
    `FakeSafetyProvider` (refused in live mode or in any Cloud Run environment); a
    known live provider gives record-and-replay.

    The safety role never falls back: only `primary` is read, so a configured
    `fallback` is ignored and an error, a replay miss or a missing capability fails
    closed instead of passing the content through a weaker or fake profile (BQ-68).
    Keep it that way when this role joins the router. `force_replay` (SEC-15): the caller decided this request
    replays, so the screen never goes live (nor records) whatever the live switch says; the fake's refusal stands."""
    if SAFETY_ROLE not in config.roles:
        raise ProviderConfigError(f"FR-INT-02: config/models.yaml has no {SAFETY_ROLE!r} role")
    profile_id = config.roles[SAFETY_ROLE].primary
    profile = config.profiles[profile_id]
    if profile.provider == "fake":
        # SEC-04, PRD 16.3 item 2: the fake would fail open on a live or deployed service.
        # Presence, not truthiness: Cloud Run can set a variable to an empty string.
        if is_live_mode() or "K_SERVICE" in os.environ or "CLOUD_RUN_JOB" in os.environ:
            raise ProviderConfigError(
                f"FR-INT-02: refusing the fake safety provider for {profile_id!r} "
                "in live mode or when deployed (K_SERVICE or CLOUD_RUN_JOB set)"
            )
        return FakeSafetyProvider()
    if profile.provider not in _LIVE_SAFETY_PROVIDERS:
        raise ProviderConfigError(f"FR-INT-02: unknown safety provider {profile.provider!r} for {profile_id!r}")

    cap = config.roles[SAFETY_ROLE].max_input_tokens

    def live_factory() -> SafetyProvider:
        return _build_live_safety_provider(profile, profile_id, cap)

    return SafetyRecordReplayProvider(
        SAFETY_ROLE, profile_id, live_factory, fixtures_dir, cap, force_replay=force_replay
    )


def _build_live_safety_provider(profile: ProvidersProfile, profile_id: str, cap: int | None) -> SafetyProvider:
    """The live Model Armor adapter: the profile's `model` is the template id, the project is
    `GOOGLE_CLOUD_PROJECT` and the location `TILO_MODEL_ARMOR_LOCATION` (default asia-southeast1)."""
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise ProviderConfigError(f"FR-INT-02: GOOGLE_CLOUD_PROJECT is not set; cannot screen live for {profile_id!r}")
    location = os.environ.get("TILO_MODEL_ARMOR_LOCATION", "asia-southeast1")
    from tilo_providers import model_armor_adapter  # noqa: PLC0415  (lazy: replay never loads it)

    return model_armor_adapter.ModelArmorSafetyProvider(
        profile_id=profile_id, template_id=profile.model, project=project, location=location, max_input_tokens=cap
    )
