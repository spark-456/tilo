"""FR-PA-19 panel cost (section 9, EFF-03, FR-MTR-06): the model is asked only when no rule read the question. A call
reserves its worst case against the person's daily allowance (UTC day) before it is sent and commits what it cost;
a decision that was paid for is cached per person and served again, vetted again, for free. Process-wide and in
memory until a shared store exists (BQ-PPL11B-6). No clock: `now` comes with the question.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.core import ModelAsk, ModelDecision
from tilo_api.assistant.model import ModelDecider

_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"
_EPSILON = 1e-9  # float sums of credits: 46.0 + 4.0 must fit a cap of 50
_CACHED = ("intent", "navigate", "decline", "dropped")


class SpendLedger(Protocol):
    def reserve(self, user: str, day: str, amount: float, cap: float) -> str | None:
        """Atomic: a reservation id when committed + open reservations + amount <= cap, else None (nothing held)."""
        ...

    def commit(self, reservation: str, actual: float) -> None: ...  # closes it; adds actual (>= 0) to the day
    def release(self, reservation: str) -> None: ...  # closes it; adds nothing
    def spent(self, user: str, day: str) -> float: ...  # committed only


class InMemorySpendLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spent: dict[tuple[str, str], float] = {}
        self._open: dict[str, tuple[str, str, float]] = {}

    def reserve(self, user: str, day: str, amount: float, cap: float) -> str | None:
        with self._lock:
            held = sum(a for u, d, a in self._open.values() if (u, d) == (user, day))
            if self._spent.get((user, day), 0.0) + held + amount > cap + _EPSILON:
                return None
            reservation = uuid.uuid4().hex
            self._open[reservation] = (user, day, amount)
            return reservation

    def commit(self, reservation: str, actual: float) -> None:
        with self._lock:
            held = self._open.pop(reservation, None)
            if held is not None:
                key = held[:2]
                self._spent[key] = self._spent.get(key, 0.0) + max(0.0, actual)

    def release(self, reservation: str) -> None:
        with self._lock:
            self._open.pop(reservation, None)

    def spent(self, user: str, day: str) -> float:
        with self._lock:
            return self._spent.get((user, day), 0.0)


@dataclass(frozen=True)
class CachedDecision:
    choice: Literal["intent", "navigate", "decline", "dropped"]
    intent: str | None
    action: Mapping[str, Any] | None
    origin_cost: float
    stored_at: str  # timestamp


class DecisionCache(Protocol):
    def get(self, user: str, key: str, now: str) -> CachedDecision | None: ...
    def put(self, user: str, key: str, value: CachedDecision) -> None: ...


def _moment(stamp: str) -> datetime:
    return datetime.strptime(stamp, _STAMP).replace(tzinfo=UTC)


class InMemoryDecisionCache:
    """One partition per person, least recently used first out, an entry older than the TTL is a miss; values are
    deep-copied in and out, so a caller can never change what is cached."""

    def __init__(self, *, per_user_entries: int, ttl_hours: int) -> None:
        self._max, self._ttl = per_user_entries, timedelta(hours=ttl_hours)
        self._lock = threading.Lock()
        self._parts: dict[str, OrderedDict[str, CachedDecision]] = {}

    def get(self, user: str, key: str, now: str) -> CachedDecision | None:
        with self._lock:
            part = self._parts.get(user)
            found = None if part is None else part.get(key)
            if found is None or part is None:
                return None
            if _moment(now) - _moment(found.stored_at) > self._ttl:
                del part[key]
                return None
            part.move_to_end(key)
            return copy.deepcopy(found)

    def put(self, user: str, key: str, value: CachedDecision) -> None:
        with self._lock:
            part = self._parts.setdefault(user, OrderedDict())
            part[key] = copy.deepcopy(value)
            part.move_to_end(key)
            while len(part) > self._max:
                part.popitem(last=False)


def cache_key(ask: ModelAsk, *, decider_version: str, config_fingerprint: str) -> str:
    """The person and every input the model saw; `now` is not one (a TTL, not a key)."""
    doc = {
        "v": 1,
        "org": ask.org_id,
        "user": ask.user,
        "q": ask.question_key,
        "screen": ask.screen,
        "context": None if ask.context is None else ask.context.json(),
        "plate": ask.plate_fingerprint,
        "menu": ask.menu.fingerprint,
        "decider": decider_version,
        "config": config_fingerprint,
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class MeteredDecider:
    """The only production `Decider`: cache, then reservation, then the model, then the actual cost."""

    def __init__(
        self, inner: ModelDecider, *, ledger: SpendLedger, cache: DecisionCache, config: AssistantConfig
    ) -> None:
        self._inner, self._ledger, self._cache, self._config = inner, ledger, cache, config

    def decide(self, ask: ModelAsk) -> ModelDecision:
        key = cache_key(ask, decider_version=self._inner.version, config_fingerprint=self._config.fingerprint)
        hit = self._cache.get(ask.user, key, ask.now)
        if hit is not None:  # the core vets it again like any reply
            return ModelDecision(hit.choice, hit.intent, hit.action, cached=True, saved=hit.origin_cost)
        amount = self._inner.worst_case_credits()
        reservation = self._ledger.reserve(ask.user, ask.now[:10], amount, self._config.user_day_credits)  # UTC day
        if reservation is None:
            return ModelDecision("budget")
        try:
            decided = self._inner.decide(ask, budget=amount)
        except Exception:
            self._ledger.release(reservation)
            return ModelDecision("unavailable")
        self._ledger.commit(reservation, decided.credits)
        if decided.model_calls > 0 and decided.choice in _CACHED:
            stored = CachedDecision(decided.choice, decided.intent, decided.action, decided.credits, ask.now)  # type: ignore[arg-type]
            self._cache.put(ask.user, key, stored)
        return decided
