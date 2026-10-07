"""Limits on the people writes (PPL-11c S4; SEC-10; BQ-PPL11C-1, -2, -4, -13, -14; tests/API_PPL_11c.md section 7).

* `write_limit`: at most `WRITES_PER_MINUTE` POST attempts a minute per signed-in principal, counted before the body is
  read (a refused attempt, a 413 and a replay count; a read does not). The 61st is a 429 with `Retry-After`.
* `idempotent`: an optional `Idempotency-Key` on a create; the same principal, route, key and body again is the first
  answer, with nothing created twice; another body is a 422; a create that failed leaves the key free and takes no
  slot. Keys are bounded: 16 per principal (its own least recently used goes first, so one caller cannot push out
  another's) and 512 principals, 8,192 stored answers in all. Only principals with a stored answer take a slot; if 512
  or more principals have created something, the least recently used idle principal's keys are forgotten.
* `NoStore`: every `/v1/` answer is `Cache-Control: no-store`, the SEC-15 gate's 403 and a validation 422 included.

Counters and keys live in a `Limits` that belongs to one install's `PeopleStores` (never to the module), keyed by the
stores object's lifetime. They are in memory: a restart or a second instance forgets them (a Firestore-backed `Limits`
is the follow-up). The clock is the `deps.get_clock` seam, read once per request. No model, no log, no value echoed.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
import weakref
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from pydantic import BaseModel
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.people_writes import Refusal

WRITES_PER_MINUTE = 60  # BQ-PPL11C-2 (SEC-10 gives no number)
_KEY = re.compile(r"[A-Za-z0-9_-]{1,64}")
_MAX_KEYS_PER_PRINCIPAL = 16  # a principal's least recently used key is forgotten first, by that principal only
_MAX_KEY_PRINCIPALS = 512  # 16 * 512 = 8,192 stored answers at most; past it the idle, least recently used go first
_MAX_PRINCIPALS = 1_024  # rate-limit counters kept before idle ones are dropped


class _Entry:
    def __init__(self) -> None:
        self.lock = threading.Lock()  # racing retries wait here for the first one
        self.fingerprint = ""
        self.answer: dict[str, Any] | None = None
        self.holders = 0  # callers between lookup and return: an entry with holders is never evicted or dropped


class Limits:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._keys: OrderedDict[str, OrderedDict[tuple[str, str], _Entry]] = OrderedDict()

    def attempt(self, user_id: str, now: float) -> None:
        """Counts one write attempt in the minute ending `now`, or refuses it (the refused one is not counted)."""
        with self._lock:
            if len(self._hits) > _MAX_PRINCIPALS:
                self._hits = {u: h for u, h in self._hits.items() if h and h[-1] > now - 60}
            hits = self._hits.setdefault(user_id, deque())
            while hits and hits[0] <= now - 60:
                hits.popleft()
            if len(hits) >= WRITES_PER_MINUTE:
                wait = min(60, max(1, math.ceil(hits[0] + 60 - now)))
                raise Refusal(429, "rate_limited", headers={"Retry-After": str(wait)}, code="rate_limited")
            hits.append(now)

    def once(
        self, user_id: str, route: str, key: str, body: BaseModel, make: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        if _KEY.fullmatch(key) is None:
            raise Refusal(422, "invalid_idempotency_key")  # never echoes the key
        fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        with self._lock:
            mine = self._keys.setdefault(user_id, OrderedDict())
            self._keys.move_to_end(user_id)
            entry = mine.setdefault((route, key), _Entry())
            mine.move_to_end((route, key))
            entry.holders += 1
        try:
            with entry.lock:
                if entry.answer is not None:
                    if entry.fingerprint != fingerprint:
                        raise Refusal(422, "idempotency_key_reused", code="idempotency_key_reused")
                    return entry.answer
                answer = make()  # a refusal raises: the key stays free (see `finally`)
                entry.fingerprint, entry.answer = fingerprint, answer
                return answer
        finally:
            with self._lock:
                entry.holders -= 1
                held = self._keys.get(user_id)
                if entry.answer is None and entry.holders == 0 and held is not None:
                    if held.get((route, key)) is entry:  # nothing was created: no key, and no principal slot
                        del held[(route, key)]
                    if not held:
                        del self._keys[user_id]
                elif entry.answer is not None:
                    self._evict(user_id)  # only a stored answer can push anything out

    def _evict(self, user_id: str) -> None:
        """Bounds the keys after `user_id` stored one: its own least recently used first, then idle principals."""
        mine = self._keys.get(user_id)
        if mine is not None and len(mine) > _MAX_KEYS_PER_PRINCIPAL:
            for k in [k for k, e in mine.items() if e.holders == 0][: len(mine) - _MAX_KEYS_PER_PRINCIPAL]:
                del mine[k]
        if len(self._keys) > _MAX_KEY_PRINCIPALS:
            for u, m in list(self._keys.items()):
                if len(self._keys) <= _MAX_KEY_PRINCIPALS:
                    break
                if u != user_id and not any(e.holders for e in m.values()):
                    del self._keys[u]


_LIMITS: dict[int, Limits] = {}
_LIMITS_LOCK = threading.Lock()


def limits_of(stores: PeopleStores) -> Limits:
    """The one `Limits` of this install's stores; it goes with them (a fresh `PeopleStores` starts at zero)."""
    with _LIMITS_LOCK:
        found = _LIMITS.get(id(stores))
        if found is None:
            found = _LIMITS[id(stores)] = Limits()
            weakref.finalize(stores, _LIMITS.pop, id(stores), None)
        return found


def write_limit(
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
    clock: Annotated[Callable[[], str], Depends(deps.get_clock)],
) -> None:
    """A dependency of every people POST route; it runs before the body dependency, so before any body is read."""
    limits_of(stores).attempt(principal.user_id, datetime.fromisoformat(clock()).timestamp())


def idempotent(
    request: Request,
    principal: deps.Principal,
    stores: PeopleStores,
    body: BaseModel,
    make: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """`make()` once per (principal, route, key) when the request has an `Idempotency-Key`; always when it has none."""
    key = request.headers.get("idempotency-key")
    if key is None:
        return make()
    return limits_of(stores).once(principal.user_id, request.url.path, key, body, make)


class NoStore:
    """Pure ASGI middleware, outside the SEC-15 gate: no `/v1/` answer is ever cached (PE-22)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        async def no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, no_store)
