"""tilo_providers.replay — record-and-replay `ModelProvider` (EFF-01, PRD
6.6 "Record and replay" row). Default mode (`LIVE` unset) replays a
recording from `fixtures/model-recordings/<role>/<key>.json`, keyed by a
stable hash of the role, profile and normalised request; a miss raises
`ReplayMissError` naming the key. `LIVE=1` sends every call to the injected
live provider; adding `TILO_RECORD=1` also writes a redacted recording
(PRD 16.1 rule 4) — the adapter's own `redact()` runs first, then
`_scrub_authorization_like` as a provider-agnostic backstop. Redaction runs
on every string *value* before serialising, never on the already-escaped
JSON text, so a match can't straddle syntax `json.dumps` adds. `live_factory`
is zero-argument so nothing here builds a network client unless a call
actually goes live. `embed()` follows the exact same record/replay/redact
shape as `generate()` (ticket P0-06 review fix), keyed by `embed_recording_key`
since an embed request is not a `GenerateRequest` -- a raw `{"input": [...]}`
dict or a bare list/string (PL-02) -- so it cannot go through `model_dump()`."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol

from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

# Backstop scrub for anything written to a recording, whatever provider
# produced it: an "Authorization: ..." header rendered as text, or a bare
# "Bearer <token>" credential. Excludes `"`/`\` from the token class so a
# match can never eat JSON syntax, whether this runs on a raw value
# (the normal path, below) or -- belt and suspenders -- on already-escaped
# JSON text.
_AUTHORIZATION_LIKE_RE = re.compile(r'(?i)(authorization\s*[:=]\s*(?:bearer\s+)?[^\s"\\]+|\bBearer\s+[^\s"\\]+)')


def _scrub_authorization_like(text: str) -> str:
    return _AUTHORIZATION_LIKE_RE.sub("[redacted]", text)


class Redactor(Protocol):  # ModelProvider and SafetyProvider both expose redact()
    def redact(self, text: str) -> str: ...


def redact_strings(value: Any, live_provider: Redactor | None) -> Any:
    """Walks a JSON-able structure and applies `live_provider.redact()` plus
    the Authorization/Bearer backstop to every string (PRD 16.1 rule 4)."""
    if isinstance(value, str):
        if live_provider is not None:
            value = live_provider.redact(value)
        return _scrub_authorization_like(value)
    if isinstance(value, dict):
        # A dict key (e.g. a tool-call argument name) can echo a secret
        # back just as readily as a value, so it is redacted the same way.
        return {redact_strings(key, live_provider): redact_strings(item, live_provider) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_strings(item, live_provider) for item in value]
    return value


def recording_key(role: str, profile_id: str, request: GenerateRequest) -> str:
    """A stable hash of (role, profile, normalised request) — the recording's
    filename stem, so a miss can name exactly the key that would satisfy it."""
    normalised = json.dumps(
        {"role": role, "profile": profile_id, "request": request.model_dump(exclude_none=True)},
        sort_keys=True,
    )
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def embed_recording_key(role: str, profile_id: str, request: Any) -> str:
    """`recording_key`'s counterpart for `embed()`: an embed request is a raw
    JSON-able value (PL-02: a `{"input": [...]}` dict, or a bare list/string),
    not a `GenerateRequest`, so it is normalised directly instead of through
    `model_dump()`. Kept a separate function (rather than overloading
    `recording_key`) so existing `generate()` keys never shift."""
    normalised = json.dumps({"role": role, "profile": profile_id, "embed_request": request}, sort_keys=True)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _join_chunks(chunks: list[GenerateResponse], profile_id: str) -> GenerateResponse:
    """One recorded turn from a live stream: text concatenated, tool calls
    collected, usage from the last chunk that reported it."""
    texts = [c.text for c in chunks if c.text is not None]
    tool_calls = [call for c in chunks for call in (c.tool_calls or [])]
    usage = next((c.usage for c in reversed(chunks) if c.usage), None)
    return GenerateResponse(
        text="".join(texts) if texts else None, profile_id=profile_id, tool_calls=tool_calls or None, usage=usage
    )


class ReplayMissError(Exception):
    """No recording exists for a (role, profile, request) key. Record one
    with `LIVE=1 TILO_RECORD=1`, or use `tilo_providers.fake` for UI work."""


class RecordReplayProvider(ModelProvider):
    def __init__(
        self,
        role: str,
        profile_id: str,
        live_factory: Callable[[], ModelProvider],
        fixtures_dir: Path | str,
        capabilities: set[Capability] | None = None,
    ) -> None:
        self._capabilities = frozenset(capabilities or ())
        self._role = role
        self._profile_id = profile_id
        self._live_factory = live_factory
        self._live_provider: ModelProvider | None = None
        self._recordings_dir = Path(fixtures_dir) / "model-recordings" / role

    def _is_live(self) -> bool:
        return os.environ.get("LIVE") == "1"

    def _is_record(self) -> bool:
        return self._is_live() and os.environ.get("TILO_RECORD") == "1"

    def _live(self) -> ModelProvider:
        if self._live_provider is None:
            self._live_provider = self._live_factory()
        return self._live_provider

    def _path(self, key: str) -> Path:
        return self._recordings_dir / f"{key}.json"

    def _embed_path(self, key: str) -> Path:
        # A distinct filename shape from generate()/stream()'s recordings --
        # keyed by a different hash namespace (`embed_recording_key`), so a
        # separate on-disk name keeps the two kinds obviously distinct too.
        return self._recordings_dir / f"embed-{key}.json"

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        key = recording_key(self._role, self._profile_id, request)
        path = self._path(key)

        if self._is_live():
            response = self._live().generate(request)
            if self._is_record():
                self._write_recording(path, key, response)
            return response

        if path.is_file():
            recorded = json.loads(path.read_text(encoding="utf-8"))
            return GenerateResponse.model_validate(recorded["response"])

        raise ReplayMissError(
            f"EFF-01: no recording for role={self._role!r} profile={self._profile_id!r} key={key!r} "
            f"at {path} — run with LIVE=1 TILO_RECORD=1 to record one"
        )

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        if not self._is_live():
            # Recordings capture one full turn; a replayed stream yields it
            # as a single chunk (router ticket P0-06 owns chunked recordings).
            yield self.generate(request)
            return

        chunks: list[GenerateResponse] = []
        for chunk in self._live().stream(request):
            chunks.append(chunk)
            yield chunk
        if self._is_record():
            key = recording_key(self._role, self._profile_id, request)
            self._write_recording(self._path(key), key, _join_chunks(chunks, self._profile_id))

    def embed(self, request: Any) -> Any:
        # Same record/replay/redact shape as generate() -- see the module
        # docstring and CLAUDE.md's router note (ticket P0-06 review fix):
        # this must never let a bare exception escape past the router, which
        # only maps `ProviderError` subtypes to a fallback/RouterError.
        key = embed_recording_key(self._role, self._profile_id, request)
        path = self._embed_path(key)

        if self._is_live():
            embedding = self._live().embed(request)
            if self._is_record():
                self._write_embed_recording(path, key, embedding)
            return embedding

        if path.is_file():
            recorded = json.loads(path.read_text(encoding="utf-8"))
            return recorded["embedding"]

        raise ReplayMissError(
            f"EFF-01: no recording for role={self._role!r} profile={self._profile_id!r} key={key!r} "
            f"at {path} — run with LIVE=1 TILO_RECORD=1 to record one"
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        # Live: ask the real provider. Replay: the profile's declared caps,
        # so no network client is built just to answer this.
        if self._is_live():
            return self._live().capabilities()
        return set(self._capabilities)

    def price(self) -> PriceQuote:
        raise NotImplementedError("PL-06: price comes from ProvidersConfig.price(profile_id), not a provider")

    def _write_recording(self, path: Path, key: str, response: GenerateResponse) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "role": self._role,
            "profile": self._profile_id,
            "key": key,
            "response": response.model_dump(exclude_none=True),
        }
        # PRD 16.1 rule 4: redact every string value before serialising, not
        # the serialised text -- see the module docstring for why.
        redacted = redact_strings(payload, self._live_provider)
        path.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _write_embed_recording(self, path: Path, key: str, embedding: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"role": self._role, "profile": self._profile_id, "key": key, "embedding": embedding}
        # PRD 16.1 rule 4: same redact-before-serialise rule as `_write_recording` -- an embedding vector
        # is numeric, but a provider may echo request metadata (e.g. a model name) back as a string.
        redacted = redact_strings(payload, self._live_provider)
        path.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n", encoding="utf-8")
