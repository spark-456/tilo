"""Per-user and per-IP token-bucket rate limiting for tilo-api routes (SEC-10).

`RateLimiter` is a small Protocol so a shared store (Redis/Firestore) can replace the default
in-process `InMemoryRateLimiter` via `app.dependency_overrides[get_rate_limiter]`.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from tilo_api.deps import Principal, get_current_principal

LimitScope = Literal["ip", "user"]
_EXEMPT_PATHS = frozenset({"/health", "/healthz"})
_DEFAULT_MAX_BUCKETS = 10_000


@dataclass(frozen=True)
class RateLimitConfig:
    """Token-bucket capacities and refill rates (tokens/second) for per-IP and per-user limits."""

    ip_capacity: int = 120
    ip_refill_per_s: float = 2.0
    user_capacity: int = 60
    user_refill_per_s: float = 1.0


class RateLimiter(Protocol):
    """Store interface for rate-limit token buckets (replaceable by a shared Redis/Firestore backend)."""

    def consume(self, key: str, *, capacity: int, refill_per_s: float) -> tuple[bool, int]:
        """Attempt to consume 1 token from `key`. Returns `(allowed, retry_after_s)`."""
        ...


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class InMemoryRateLimiter:
    """Thread-safe in-process token bucket limiter with bounded key eviction."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_buckets: int = _DEFAULT_MAX_BUCKETS,
    ) -> None:
        if max_buckets < 1:
            raise ValueError("max_buckets must be >= 1")
        self._clock = clock
        self._max_buckets = max_buckets
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    @property
    def bucket_count(self) -> int:
        with self._lock:
            return len(self._buckets)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def consume(self, key: str, *, capacity: int, refill_per_s: float) -> tuple[bool, int]:
        if capacity < 1 or not (math.isfinite(refill_per_s) and refill_per_s > 0):
            raise ValueError("capacity must be >= 1 and refill_per_s must be finite > 0")
        now = float(self._clock())
        cap = float(capacity)
        with self._lock:
            bucket = self._buckets.pop(key, None)
            if bucket is None:
                tokens = cap
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                tokens = min(cap, bucket.tokens + elapsed * refill_per_s)

            if tokens >= 1.0:
                self._buckets[key] = _Bucket(tokens=tokens - 1.0, updated_at=now)
                self._evict_if_needed()
                return True, 0

            self._buckets[key] = _Bucket(tokens=tokens, updated_at=now)
            self._evict_if_needed()
            deficit = max(0.0, 1.0 - tokens)
            retry_after_s = max(1, int(math.ceil(deficit / refill_per_s - 1e-12)))
            return False, retry_after_s

    def _evict_if_needed(self) -> None:
        while len(self._buckets) > self._max_buckets:
            oldest_key = next(iter(self._buckets))
            del self._buckets[oldest_key]


_DEFAULT_LIMITER = InMemoryRateLimiter()
_LAST_PYTEST_GUARD = threading.Lock()
_LAST_PYTEST_ID: str | None = None


def get_rate_limiter() -> RateLimiter:
    global _LAST_PYTEST_ID
    test_id = os.environ.get("PYTEST_CURRENT_TEST")
    with _LAST_PYTEST_GUARD:
        if test_id != _LAST_PYTEST_ID:
            _LAST_PYTEST_ID = test_id
            _DEFAULT_LIMITER.reset()
    return _DEFAULT_LIMITER


def get_rate_limit_config() -> RateLimitConfig:
    return RateLimitConfig()


def _client_ip(scope: dict[str, Any]) -> str:
    """Use the ASGI connection peer address, never spoofable X-Forwarded-For headers."""
    client = scope.get("client")
    if isinstance(client, tuple | list) and client and isinstance(client[0], str) and client[0]:
        return client[0]
    return "unknown"


def _resolve_principal(fastapi_app: FastAPI) -> Principal | None:
    provider = fastapi_app.dependency_overrides.get(get_current_principal, get_current_principal)
    try:
        candidate = provider()
    except HTTPException:
        return None
    return candidate if isinstance(candidate, Principal) else None


def _rate_limit_response(limit_scope: LimitScope, retry_after_s: int) -> JSONResponse:
    safe_retry = max(1, int(retry_after_s))
    unit = "second" if safe_retry == 1 else "seconds"
    msg = f"Rate limit exceeded ({limit_scope} limit). Please retry after {safe_retry} {unit}."
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(safe_retry)},
        content={
            "detail": msg,
            "code": "rate_limit_exceeded",
            "scope": limit_scope,
            "retry_after_s": safe_retry,
        },
    )


class RateLimitGate:
    """ASGI middleware enforcing per-user and per-IP token-bucket rate limits on public routes (SEC-10)."""

    def __init__(self, inner: Any, *, fastapi_app: FastAPI) -> None:
        self._inner = inner
        self._app = fastapi_app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path", "") in _EXEMPT_PATHS:
            await self._inner(scope, receive, send)
            return

        limiter: RateLimiter = self._app.dependency_overrides.get(get_rate_limiter, get_rate_limiter)()
        cfg: RateLimitConfig = self._app.dependency_overrides.get(get_rate_limit_config, get_rate_limit_config)()

        principal = _resolve_principal(self._app)
        if principal is not None:
            user_ok, user_retry = limiter.consume(
                f"user:{principal.user_id}",
                capacity=cfg.user_capacity,
                refill_per_s=cfg.user_refill_per_s,
            )
            if not user_ok:
                await _rate_limit_response("user", user_retry)(scope, receive, send)
                return

        ip_ok, ip_retry = limiter.consume(
            f"ip:{_client_ip(scope)}",
            capacity=cfg.ip_capacity,
            refill_per_s=cfg.ip_refill_per_s,
        )
        if not ip_ok:
            await _rate_limit_response("ip", ip_retry)(scope, receive, send)
            return

        await self._inner(scope, receive, send)
