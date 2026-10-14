"""Per-user and per-IP token-bucket rate limiting for tilo-api routes (SEC-10).

`RateLimiter` is a small Protocol so a shared store (Redis/Firestore) can replace the default
in-process `InMemoryRateLimiter` via `app.dependency_overrides[get_rate_limiter]`.
 Note: in-process buckets are per Cloud Run instance (up to max instances) and reset on cold start
until a shared store is wired.
"""

from __future__ import annotations

import functools
import inspect
import ipaddress
import logging
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from tilo_api.deps import Principal, get_current_principal

logger = logging.getLogger("tilo_api.rate_limit")

LimitScope = Literal["ip", "user"]
_EXEMPT_PATHS = frozenset({"/health", "/healthz"})
_DEFAULT_MAX_BUCKETS = 10_000
_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "rate_limits.yaml"


class RateLimitConfigError(ValueError):
    """`config/rate_limits.yaml` or `RateLimitConfig` is invalid."""


def _require_int(value: object, name: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise RateLimitConfigError(f"{name} must be an integer >= {minimum}")
    return value


def _require_rate(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RateLimitConfigError(f"{name} must be a finite number > 0")
    rate = float(value)
    if not math.isfinite(rate) or rate <= 0.0:
        raise RateLimitConfigError(f"{name} must be a finite number > 0")
    return rate


@dataclass(frozen=True)
class RateLimitConfig:
    """Token-bucket capacities, refill rates (tokens/second) and trusted XFF hop count (SEC-10)."""

    ip_capacity: int = 600
    ip_refill_per_s: float = 50.0
    user_capacity: int = 120
    user_refill_per_s: float = 10.0
    trusted_hops: int = 1

    def __post_init__(self) -> None:
        ip_cap = _require_int(self.ip_capacity, "ip_capacity", 1)
        user_cap = _require_int(self.user_capacity, "user_capacity", 1)
        _require_int(self.trusted_hops, "trusted_hops", 1)
        ip_rate = _require_rate(self.ip_refill_per_s, "ip_refill_per_s")
        user_rate = _require_rate(self.user_refill_per_s, "user_refill_per_s")
        if ip_cap < user_cap or ip_rate < user_rate:
            raise RateLimitConfigError("IP rate limits must be >= per-user rate limits")


@functools.lru_cache(maxsize=8)
def _load_cached(resolved: Path, mtime_ns: int) -> RateLimitConfig:
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RateLimitConfigError(f"rate_limits.yaml is unreadable ({type(exc).__name__})") from exc
    expected = {f.name for f in fields(RateLimitConfig)}
    if type(raw) is not dict or set(raw) != expected:
        raise RateLimitConfigError(f"rate_limits.yaml must be a mapping with keys {sorted(expected)}")
    return RateLimitConfig(**raw)


def load_rate_limit_config(path: str | Path | None = None) -> RateLimitConfig:
    """Load and validate `config/rate_limits.yaml`."""
    target = Path(path) if path is not None else _CONFIG_PATH
    try:
        stat = target.stat()
    except OSError as exc:
        raise RateLimitConfigError(f"rate_limits.yaml is missing ({type(exc).__name__})") from exc
    return _load_cached(target.resolve(), stat.st_mtime_ns)


_DEFAULT_CONFIG = load_rate_limit_config()


class RateLimiter(Protocol):
    """Store interface for rate-limit token buckets (replaceable by a shared Redis/Firestore backend)."""

    def peek(self, key: str, *, capacity: int, refill_per_s: float) -> tuple[bool, int]:
        """Check whether `key` has at least 1 token without consuming it. Returns `(allowed, retry_after_s)`."""
        ...

    def consume(self, key: str, *, capacity: int, refill_per_s: float) -> tuple[bool, int]:
        """Attempt to consume 1 token from `key`. Returns `(allowed, retry_after_s)`."""
        ...

    def consume_all(self, checks: Sequence[tuple[LimitScope, str, int, float]]) -> tuple[LimitScope | None, int]:
        """Check all buckets before consuming any token. Returns `(None, 0)` or `(limited_scope, retry_after_s)`."""
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
        if type(max_buckets) is not int or max_buckets < 1:
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

    def _available(self, key: str, now: float, capacity: int, refill_per_s: float) -> tuple[float, int]:
        cap = float(capacity)
        bucket = self._buckets.get(key)
        tokens = cap if bucket is None else min(cap, bucket.tokens + max(0.0, now - bucket.updated_at) * refill_per_s)
        if tokens < 1.0:
            retry_after_s = max(1, int(math.ceil(max(0.0, 1.0 - tokens) / refill_per_s - 1e-12)))
            return tokens, retry_after_s
        return tokens, 0

    def peek(self, key: str, *, capacity: int, refill_per_s: float) -> tuple[bool, int]:
        """Check whether `key` currently has at least 1 token without consuming it."""
        if type(capacity) is not int or capacity < 1 or not (math.isfinite(refill_per_s) and refill_per_s > 0):
            raise ValueError("capacity must be >= 1 and refill_per_s must be finite > 0")
        with self._lock:
            tokens, retry_after_s = self._available(key, float(self._clock()), capacity, refill_per_s)
            return tokens >= 1.0, retry_after_s

    def consume(self, key: str, *, capacity: int, refill_per_s: float) -> tuple[bool, int]:
        limited_scope, retry_after_s = self.consume_all((("ip", key, capacity, refill_per_s),))
        return limited_scope is None, retry_after_s

    def consume_all(self, checks: Sequence[tuple[LimitScope, str, int, float]]) -> tuple[LimitScope | None, int]:
        """Check all buckets before consuming any token. Returns `(None, 0)` or `(limited_scope, retry_after_s)`."""
        for _, _, capacity, refill_per_s in checks:
            if type(capacity) is not int or capacity < 1 or not (math.isfinite(refill_per_s) and refill_per_s > 0):
                raise ValueError("capacity must be >= 1 and refill_per_s must be finite > 0")
        now = float(self._clock())
        with self._lock:
            refilled: list[tuple[str, float]] = []
            for limit_scope, key, capacity, refill_per_s in checks:
                tokens, retry_after_s = self._available(key, now, capacity, refill_per_s)
                if tokens < 1.0:
                    return limit_scope, retry_after_s
                refilled.append((key, tokens))

            for key, tokens in refilled:
                self._buckets.pop(key, None)
                self._buckets[key] = _Bucket(tokens=tokens - 1.0, updated_at=now)
            self._evict_if_needed()
            return None, 0

    def _evict_if_needed(self) -> None:
        while len(self._buckets) > self._max_buckets:
            oldest_key = next(iter(self._buckets))
            del self._buckets[oldest_key]


_DEFAULT_LIMITER = InMemoryRateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _DEFAULT_LIMITER


def reset_default_rate_limiter() -> None:
    _DEFAULT_LIMITER.reset()


def get_rate_limit_config() -> RateLimitConfig:
    return load_rate_limit_config()


def _normalize_ip(raw: str) -> str | None:
    token = raw.strip()
    if not token or token == "*":
        return None
    try:
        addr = ipaddress.ip_address(token)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.IPv6Network((addr, 64), strict=False))
    return str(addr)


def _client_ip(scope: Mapping[str, Any], trusted_hops: int = 1) -> str:
    """Take client IP from X-Forwarded-For counting `trusted_hops` from the right (Cloud Run's front end appends);
    never use a client-controlled leftmost entry or '*', and use the socket peer only when XFF is absent."""
    if type(trusted_hops) is not int or trusted_hops < 1:
        raise ValueError("trusted_hops must be >= 1")
    xff_parts = [
        part.strip()
        for k, v in scope.get("headers", ())
        if k.lower() == b"x-forwarded-for"
        for part in v.decode("latin-1").split(",")
        if part.strip()
    ]
    if xff_parts:
        if len(xff_parts) >= trusted_hops:
            normalized = _normalize_ip(xff_parts[-trusted_hops])
            if normalized is not None:
                return normalized
        return "invalid_xff"
    client = scope.get("client")
    if isinstance(client, tuple | list) and client and isinstance(client[0], str) and client[0]:
        peer = client[0].strip()
        if peer and peer != "*":
            return _normalize_ip(peer) or peer
    return "unknown"


async def _resolve_principal(scope: dict[str, Any], fastapi_app: FastAPI) -> Principal | None:
    if scope.get("path") == "/internal/schedules/tick":
        return None
    state = scope.setdefault("state", {})
    if isinstance(state, dict) and isinstance(state.get("principal"), Principal):
        return state["principal"]
    provider = fastapi_app.dependency_overrides.get(get_current_principal, get_current_principal)
    if provider is get_current_principal and not any(
        k.lower() == b"authorization" for k, _ in scope.get("headers", ())
    ):
        return None
    try:
        sig = inspect.signature(provider)
        takes_request = any(
            p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
            )
            for p in sig.parameters.values()
        )
        args = (Request(scope),) if takes_request else ()
        if inspect.iscoroutinefunction(provider):
            candidate = await provider(*args)
        else:
            candidate = await run_in_threadpool(provider, *args)
            if inspect.isawaitable(candidate):
                candidate = await candidate
    except Exception:
        return None
    if isinstance(candidate, Principal):
        if isinstance(state, dict):
            state["principal"] = candidate
        return candidate
    return None


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


_CAPABILITY_MISSING = (
    NotImplementedError,
    AttributeError,
    TypeError,
    ValueError,
)  # missing or malformed peek/consume_all contract: fail closed


def _store_unusable(limiter: object) -> JSONResponse:
    logger.error(
        "rate limiter store lacks or violated peek/consume_all contract, failing closed: %s",
        type(limiter).__name__,
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Rate limiter store is unusable.", "code": "rate_limiter_unavailable"},
    )


async def _decide(scope: dict[str, Any], fastapi_app: FastAPI) -> JSONResponse | None:
    try:
        limiter: RateLimiter = fastapi_app.dependency_overrides.get(get_rate_limiter, get_rate_limiter)()
        cfg: RateLimitConfig = fastapi_app.dependency_overrides.get(get_rate_limit_config, get_rate_limit_config)()
    except Exception as exc:
        logger.warning("rate limit configuration unavailable, failing open: %s", type(exc).__name__)
        return None

    peek_fn, consume_fn = getattr(limiter, "peek", None), getattr(limiter, "consume_all", None)
    if not callable(peek_fn) or not callable(consume_fn):
        return _store_unusable(limiter)

    ip_key = f"ip:{_client_ip(scope, cfg.trusted_hops)}"
    try:
        ip_ok, ip_retry_s = peek_fn(ip_key, capacity=cfg.ip_capacity, refill_per_s=cfg.ip_refill_per_s)
        if not ip_ok:
            return _rate_limit_response("ip", ip_retry_s)
    except _CAPABILITY_MISSING:
        return _store_unusable(limiter)
    except Exception as exc:
        logger.warning("rate limiter store failed, failing open: %s", type(exc).__name__)
        return None

    principal = await _resolve_principal(scope, fastapi_app)
    checks: list[tuple[LimitScope, str, int, float]] = [
        ("ip", ip_key, cfg.ip_capacity, cfg.ip_refill_per_s),
    ]
    if principal is not None:
        checks.append(("user", f"user:{principal.user_id}", cfg.user_capacity, cfg.user_refill_per_s))

    try:
        limited_scope, retry_after_s = consume_fn(checks)
        if limited_scope is not None:
            return _rate_limit_response(limited_scope, retry_after_s)
    except _CAPABILITY_MISSING:
        return _store_unusable(limiter)
    except Exception as exc:
        logger.warning("rate limiter store failed, failing open: %s", type(exc).__name__)
        return None
    return None


class RateLimitGate:
    """Outermost ASGI middleware enforcing per-user and per-IP token-bucket rate limits (SEC-10)."""

    def __init__(self, inner: Any, *, fastapi_app: FastAPI) -> None:
        self._inner = inner
        self._app = fastapi_app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        kind = scope.get("type")
        if kind == "lifespan" or (kind == "http" and scope.get("path", "") in _EXEMPT_PATHS):
            await self._inner(scope, receive, send)
            return
        if kind not in {"http", "websocket"}:
            return

        refusal = await _decide(scope, self._app)
        if refusal is None:
            await self._inner(scope, receive, send)
        elif kind == "http":
            await refusal(scope, receive, send)
        else:
            await receive()
            await send({"type": "websocket.close", "code": 1008})
