"""Shared test doubles for services/channels (the injected clock and the dedupe store).

Kept under a package-unique module name because every test directory has its own conftest.py, so
`from conftest import ...` resolves to whichever one was imported first when the whole suite runs
together. No production code lives here.
"""

from __future__ import annotations

import threading

# A fixed, plausible instant (2026-10-02T09:00:00Z) so timestamps in payloads are realistic.
T0 = 1_790_931_600


class FakeClock:
    """Injected clock: `clock()` returns unix seconds as a float; tests move it with advance()."""

    def __init__(self, start: float = float(T0)) -> None:
        self._now = float(start)
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds


class MemoryDedupeStore:
    """Thread-safe in-memory DedupeStore: `claim(key, ttl_s)` is an atomic set-if-absent that
    returns True for the first claimant and False for every later one until the ttl lapses (by
    the injected clock). Records every call so tests can assert what the handler touched."""

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self._expires: dict[str, float] = {}
        self._lock = threading.Lock()
        self.claims: list[tuple[str, float]] = []

    def claim(self, key: str, ttl_s: float) -> bool:
        with self._lock:
            self.claims.append((key, ttl_s))
            now = self._clock()
            expires = self._expires.get(key)
            if expires is not None and expires > now:
                return False
            self._expires[key] = now + ttl_s
            return True
