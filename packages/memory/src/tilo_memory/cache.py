"""Result cache (PRD 13.1, FR-MEM-01, FR-MEM-02).

Keyed by the normalised request plus the source fingerprint, with `origin_cost`. Web results are fresh for
7 days, files until their fingerprint changes, email bodies are never cached. A cached result is reused only
if a fit check and the Verifier both accept it; every reuse is one `memory.hit` event and the only thing
credited as saved (PRD 14.3). Deterministic: time comes from the injected clock, the two checks are injected.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from tilo_contracts import EVENT_DATA_MODELS, Event

WEB_FRESH_FOR = timedelta(days=7)  # PRD 13.1: "Web results fresh for 7 days"
Kind = Literal["web", "file", "email_body"]
Reason = Literal["absent", "stale", "not_cacheable", "fit_rejected", "verifier_rejected"]
_KINDS = ("web", "file", "email_body")
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@dataclass(frozen=True)
class CacheRequest:
    kind: Kind
    text: str
    fingerprint: str


@dataclass(frozen=True)
class Fetched:
    value: Any
    origin_cost: float


@dataclass(frozen=True)
class LookupRecord:
    at: datetime
    kind: str
    outcome: Literal["hit", "miss"]
    reason: Reason | None
    saved: float


@dataclass(frozen=True)
class CacheResult:
    value: Any
    outcome: Literal["hit", "miss"]
    reason: Reason | None
    saved: float
    events: list[dict[str, Any]]


@dataclass
class _Entry:
    value: Any
    origin_cost: float
    stored_at: datetime


@dataclass
class ResultCache:
    clock: Callable[[], datetime]
    fit_check: Callable[[CacheRequest, Any], bool]
    verifier: Callable[[CacheRequest, Any], bool]
    lookup_cost: float
    log: list[LookupRecord] = field(default_factory=list)
    credits_saved: float = 0.0
    _entries: dict[tuple[str, str, str], _Entry] = field(default_factory=dict)

    def get_or_fetch(
        self, request: CacheRequest, fetch: Callable[[], Fetched], *, base: dict[str, Any], seq: int
    ) -> CacheResult:
        """Reuse a fresh, accepted result (one `memory.hit`), else call `fetch` and store its result."""
        if request.kind not in _KINDS:
            raise ValueError(f"unknown cache kind; allowed kinds: {', '.join(_KINDS)}")
        now = self.clock()
        key = (request.kind, _normalise(request.text), request.fingerprint)
        reason = self._reject_reason(request, key, now)
        if reason is None:
            entry = self._entries[key]
            saved = max(entry.origin_cost - self.lookup_cost, 0.0)
            self.credits_saved += saved
            self.log.append(LookupRecord(now, request.kind, "hit", None, saved))
            event = _memory_hit_event(base, seq, entry.origin_cost, self.lookup_cost, saved)
            return CacheResult(entry.value, "hit", None, saved, [event])
        fetched = fetch()
        if request.kind != "email_body":
            self._entries[key] = _Entry(fetched.value, fetched.origin_cost, now)
        self.log.append(LookupRecord(now, request.kind, "miss", reason, 0.0))
        return CacheResult(fetched.value, "miss", reason, 0.0, [])

    def _reject_reason(self, request: CacheRequest, key: tuple[str, str, str], now: datetime) -> Reason | None:
        """None when the entry may be reused; otherwise why it is not. The checks see only a fresh entry."""
        if request.kind == "email_body":
            return "not_cacheable"
        entry = self._entries.get(key)
        if entry is None:
            return "absent"
        if request.kind == "web" and now - entry.stored_at > WEB_FRESH_FOR:
            return "stale"
        if not self.fit_check(request, entry.value):
            return "fit_rejected"
        if not self.verifier(request, entry.value):
            return "verifier_rejected"
        return None


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _new_ulid() -> str:
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


def _memory_hit_event(
    base: dict[str, Any], seq: int, origin_cost: float, lookup_cost: float, saved: float
) -> dict[str, Any]:
    """A validated `memory.hit` TiloEvent. `base` holds v/ts/world_id/run_id/actor (PRD 9.3); the harness owns `seq`."""
    data = EVENT_DATA_MODELS["memory.hit"].model_validate(
        {"origin_cost": origin_cost, "lookup_cost": lookup_cost, "saved": saved}
    )
    trace = dict.fromkeys(("model_role", "profile", "tokens_in", "tokens_out", "tool", "latency_ms", "archive_ref"))
    raw = {
        **base,
        "id": _new_ulid(),
        "seq": seq,
        "type": "memory.hit",
        "target": base["world_id"],
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": f"Reused an earlier result and saved {saved:g} credits.",
        "cause": None,
        "vis": "all",
        "authz": None,
        "data": data.model_dump(mode="json", by_alias=True, exclude_unset=True),
        "trace": trace,
    }
    return Event.model_validate(raw).model_dump(mode="json", exclude_unset=True)
