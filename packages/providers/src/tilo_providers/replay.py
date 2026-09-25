"""tilo_providers.replay — record-and-replay `ModelProvider` (EFF-01, PRD
6.6 "Record and replay" row). Default mode (`LIVE` unset) replays a
recording from `fixtures/model-recordings/<role>/<key>.json`, keyed by a
stable hash of the role, profile and normalised request; a miss raises
`ReplayMissError` naming the key, so a failure always says exactly what to
record. `LIVE=1` sends every call to the injected live provider; adding
`TILO_RECORD=1` also writes a redacted recording — only the
`ModelProvider`-level request/response ever reaches the file, never a
header, API key or env value (PRD 16.1 rule 4). `live_factory` is a
zero-argument callable so nothing here imports an adapter module or builds a
network client unless a call actually goes live."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote


def recording_key(role: str, profile_id: str, request: GenerateRequest) -> str:
    """A stable hash of (role, profile, normalised request) — the recording's
    filename stem, so a miss can name exactly the key that would satisfy it."""
    normalised = json.dumps(
        {"role": role, "profile": profile_id, "request": request.model_dump(exclude_none=True)},
        sort_keys=True,
    )
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
        # Built lazily on the first live call, then reused.
        if self._live_provider is None:
            self._live_provider = self._live_factory()
        return self._live_provider

    def _path(self, key: str) -> Path:
        return self._recordings_dir / f"{key}.json"

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

    def embed(self, request: object) -> object:
        raise NotImplementedError("EFF-01: record-and-replay embed lands with the router ticket P0-06")

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
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
