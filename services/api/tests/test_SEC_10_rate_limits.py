"""SEC-10: Per-user and per-IP rate limits on services/api public routes with 429, clear JSON message,
Retry-After header, replaceable store interface, X-Forwarded-For rightmost trusted hop, config validation,
and local load / web-client cadence tests (fake providers).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from tilo_api import app
from tilo_api.access import InMemoryAccessStore
from tilo_api.deps import Principal, Store, WorldRecord, get_access_store, get_current_principal, get_store
from tilo_api.rate_limit import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RateLimitConfigError,
    RateLimiter,
    get_rate_limit_config,
    get_rate_limiter,
    load_rate_limit_config,
)


class FakeClock:
    def __init__(self, initial: float = 1000.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _seed_store() -> Store:
    store = Store()
    store.worlds["w_sec10"] = WorldRecord(owner="u_alice", districts={})
    return store


def test_SEC_10_token_bucket_refill_and_retry_after() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    for _ in range(3):
        assert limiter.consume("user:u_alice", capacity=3, refill_per_s=0.5) == (True, 0)

    assert limiter.consume("user:u_alice", capacity=3, refill_per_s=0.5) == (False, 2)
    clock.advance(1.0)
    assert limiter.consume("user:u_alice", capacity=3, refill_per_s=0.5) == (False, 1)
    clock.advance(1.0)
    assert limiter.consume("user:u_alice", capacity=3, refill_per_s=0.5) == (True, 0)


def test_SEC_10_bounded_bucket_eviction_prevents_memory_exhaustion() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock, max_buckets=5)

    for idx in range(10):
        clock.advance(0.1)
        allowed, _ = limiter.consume(f"ip:198.51.100.{idx}", capacity=2, refill_per_s=1.0)
        assert allowed is True

    assert limiter.bucket_count <= 5


def test_SEC_10_per_user_rate_limit_429_message_and_isolation() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    cfg = RateLimitConfig(ip_capacity=50, ip_refill_per_s=10.0, user_capacity=3, user_refill_per_s=0.25)
    store = _seed_store()
    access_store = InMemoryAccessStore()
    current_user = {"id": "u_alice"}

    def principal_with_request(request: Request) -> Principal:
        return Principal(
            user_id=current_user["id"],
            role="owner",
            world_id=request.path_params.get("world_id") or "w_sec10",
        )

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_access_store] = lambda: access_store
    app.dependency_overrides[get_current_principal] = principal_with_request
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_rate_limit_config] = lambda: cfg

    try:
        client = TestClient(app)
        assert client.get("/access").status_code == 200
        assert client.get("/worlds/w_sec10/cards").status_code == 200
        assert client.get("/worlds/w_sec10/cards").status_code == 200

        blocked = client.get("/access")
        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"] == "4"
        payload = blocked.json()
        assert payload["code"] == "rate_limit_exceeded"
        assert payload["scope"] == "user"
        assert payload["retry_after_s"] == 4
        assert "Rate limit exceeded" in payload["detail"]
        assert "4 seconds" in payload["detail"]

        # Another authenticated user on the same client IP is not blocked by Alice's user bucket
        current_user["id"] = "u_bob"
        store.worlds["w_sec10_bob"] = WorldRecord(owner="u_bob", districts={})
        assert client.get("/worlds/w_sec10_bob/cards").status_code == 200

        # A broken principal provider never causes a 500 in the rate-limit gate; falls back to IP limit
        def broken_principal(_request: Request) -> Principal:
            raise RuntimeError("auth provider failure")

        app.dependency_overrides[get_current_principal] = broken_principal
        assert client.get("/health").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_SEC_10_per_ip_xff_trusted_hops_separates_clients_and_resists_leftmost_forgery() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    cfg = RateLimitConfig(ip_capacity=2, ip_refill_per_s=0.5, user_capacity=2, user_refill_per_s=0.5, trusted_hops=1)

    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_rate_limit_config] = lambda: cfg

    try:
        client = TestClient(app)
        # Client A (198.51.100.1 appended by Cloud Run front end) uses its 2 tokens
        assert client.get("/access", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 401
        assert client.get("/worlds/w_sec10/cards", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 401

        # Forged leftmost XFF entries cannot change Client A's bucket when Cloud Run appends 198.51.100.1 on the right
        forged_1 = client.get("/access", headers={"X-Forwarded-For": "203.0.113.99, 198.51.100.1"})
        forged_2 = client.get("/access", headers={"X-Forwarded-For": "*, 198.51.100.1"})
        assert forged_1.status_code == 429
        assert forged_2.status_code == 429
        assert forged_1.headers["Retry-After"] == "2"
        payload = forged_1.json()
        assert payload["code"] == "rate_limit_exceeded"
        assert payload["scope"] == "ip"
        assert payload["retry_after_s"] == 2

        # Client B (198.51.100.2) behind the SAME socket peer gets its own separate bucket
        assert client.get("/access", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 401
        assert client.get("/access", headers={"X-Forwarded-For": "203.0.113.5, 198.51.100.2"}).status_code == 401
        assert client.get("/access", headers={"X-Forwarded-For": "203.0.113.6, 198.51.100.2"}).status_code == 429

        # With trusted_hops=2, the 2nd hop from the right is used and leftmost forgery is still ignored
        cfg_2hops = RateLimitConfig(
            ip_capacity=2, ip_refill_per_s=0.5, user_capacity=2, user_refill_per_s=0.5, trusted_hops=2
        )
        app.dependency_overrides[get_rate_limit_config] = lambda: cfg_2hops
        assert (
            client.get("/access", headers={"X-Forwarded-For": "203.0.113.77, 198.51.100.1, 10.0.0.1"}).status_code
            == 429
        )

        assert client.get("/health").status_code == 200
        assert client.get("/healthz").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_SEC_10_checks_both_buckets_before_consuming_either_and_validates_config(tmp_path: Path) -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    cfg = RateLimitConfig(ip_capacity=2, ip_refill_per_s=0.5, user_capacity=2, user_refill_per_s=0.5)
    store = _seed_store()
    signed_in = {"active": True}

    def maybe_principal() -> Principal:
        if not signed_in["active"]:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="signed out")
        return Principal(user_id="u_alice", role="owner", world_id="w_sec10")

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_current_principal] = maybe_principal
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_rate_limit_config] = lambda: cfg

    try:
        client = TestClient(app)
        # Alice uses 1 user token and 1 IP token on 198.51.100.10 (1 left in each)
        assert client.get("/worlds/w_sec10/cards", headers={"X-Forwarded-For": "198.51.100.10"}).status_code == 200
        # An unauthenticated request on 198.51.100.10 uses the 2nd IP token (0 left on IP 198.51.100.10)
        signed_in["active"] = False
        assert client.get("/access", headers={"X-Forwarded-For": "198.51.100.10"}).status_code == 401
        # Alice now hits 429 on IP 198.51.100.10; her remaining user token must NOT be consumed
        signed_in["active"] = True
        refused = client.get("/worlds/w_sec10/cards", headers={"X-Forwarded-For": "198.51.100.10"})
        assert refused.status_code == 429
        assert refused.json()["scope"] == "ip"
        # From another IP (198.51.100.11), Alice can still spend her 2nd user token
        assert client.get("/worlds/w_sec10/cards", headers={"X-Forwarded-For": "198.51.100.11"}).status_code == 200
    finally:
        app.dependency_overrides.clear()

    loaded = load_rate_limit_config()
    assert loaded.ip_capacity >= loaded.user_capacity
    assert loaded.ip_refill_per_s >= loaded.user_refill_per_s
    assert loaded.trusted_hops >= 1

    with pytest.raises(RateLimitConfigError):
        RateLimitConfig(ip_capacity=0, ip_refill_per_s=10.0, user_capacity=1, user_refill_per_s=1.0)
    with pytest.raises(RateLimitConfigError):
        RateLimitConfig(ip_capacity=10, ip_refill_per_s=10.0, user_capacity=20, user_refill_per_s=1.0)
    with pytest.raises(RateLimitConfigError):
        RateLimitConfig(ip_capacity=20, ip_refill_per_s=1.0, user_capacity=10, user_refill_per_s=5.0)

    bad_yaml = tmp_path / "rate_limits.yaml"
    bad_yaml.write_text("ip_capacity: 0\n", encoding="utf-8")
    with pytest.raises(RateLimitConfigError):
        load_rate_limit_config(bad_yaml)


def test_SEC_10_default_limits_sustain_web_client_polling_cadence_for_several_minutes() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    store = Store()
    for wid in ("w_a1", "w_a2", "w_a3"):
        store.worlds[wid] = WorldRecord(owner="u_alice", districts={})
        store.events[wid] = []
    for wid in ("w_b1", "w_b2", "w_b3"):
        store.worlds[wid] = WorldRecord(owner="u_bob", districts={})
        store.events[wid] = []

    current_user = {"id": "u_alice"}

    def principal(request: Request) -> Principal:
        return Principal(
            user_id=current_user["id"],
            role="owner",
            world_id=request.path_params.get("world_id"),
        )

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_current_principal] = principal
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    try:
        client = TestClient(app)
        headers = {"X-Forwarded-For": "198.51.100.42"}
        # Drive 3 minutes (180 s) of two users behind one NAT IP each polling 3 open worlds at 1 req/s + ordinary calls
        for second in range(180):
            current_user["id"] = "u_alice"
            for wid in ("w_a1", "w_a2", "w_a3"):
                assert client.get(f"/worlds/{wid}/events", headers=headers).status_code == 200
            if second % 5 == 0:
                assert client.get("/worlds/w_a1/cards", headers=headers).status_code == 200

            current_user["id"] = "u_bob"
            for wid in ("w_b1", "w_b2", "w_b3"):
                assert client.get(f"/worlds/{wid}/events", headers=headers).status_code == 200
            if second % 5 == 0:
                assert client.get("/worlds/w_b1/cards", headers=headers).status_code == 200

            clock.advance(1.0)
    finally:
        app.dependency_overrides.clear()


def test_SEC_10_replaceable_shared_store_interface() -> None:
    calls: list[list[tuple[str, str]]] = []

    class CustomSharedLimiter:
        def consume(self, key: str, *, capacity: int, refill_per_s: float) -> tuple[bool, int]:
            return False, 7

        def consume_all(
            self, checks: list[tuple[str, str, int, float]] | tuple[tuple[str, str, int, float], ...]
        ) -> tuple[str | None, int]:
            calls.append([(scope, key) for scope, key, _, _ in checks])
            return "ip", 7

    custom: RateLimiter = CustomSharedLimiter()  # type: ignore[assignment]
    app.dependency_overrides[get_rate_limiter] = lambda: custom
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="u_alice", role="owner", world_id="w_sec10"
    )
    try:
        client = TestClient(app)
        res = client.get("/worlds/w_sec10/cards")
        assert res.status_code == 429
        assert res.headers["Retry-After"] == "7"
        assert res.json()["retry_after_s"] == 7
        assert calls == [[("ip", "ip:testclient"), ("user", "user:u_alice")]]
    finally:
        app.dependency_overrides.clear()


def test_SEC_10_ip_checked_before_principal_verify_once_and_async_provider() -> None:
    import warnings

    from fastapi import HTTPException

    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    cfg = RateLimitConfig(ip_capacity=2, ip_refill_per_s=0.5, user_capacity=2, user_refill_per_s=0.5)
    store = _seed_store()
    verify_calls = {"count": 0}

    def bad_token_provider(_request: Request) -> Principal:
        verify_calls["count"] += 1
        raise HTTPException(status_code=401, detail="bad token")

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_rate_limit_config] = lambda: cfg
    app.dependency_overrides[get_current_principal] = bad_token_provider

    try:
        client = TestClient(app)
        xff = {"X-Forwarded-For": "198.51.100.77", "Authorization": "Bearer bad.token"}
        # First 2 bad-token requests exhaust the IP bucket for 198.51.100.77
        assert client.get("/access", headers=xff).status_code == 401
        assert client.get("/access", headers=xff).status_code == 401
        calls_at_exhaustion = verify_calls["count"]

        # Subsequent flood of bad tokens from the exhausted IP is refused BEFORE resolving the principal
        for _ in range(5):
            flood = client.get("/access", headers=xff)
            assert flood.status_code == 429
            assert flood.json()["scope"] == "ip"
        assert verify_calls["count"] == calls_at_exhaustion

        # Async principal providers are awaited cleanly without 'coroutine was never awaited' warnings
        async def async_ok_principal(request: Request) -> Principal:
            return Principal(user_id="u_alice", role="owner", world_id=request.path_params.get("world_id") or "w_sec10")

        async def async_bad_principal(_request: Request) -> Principal:
            raise HTTPException(status_code=401, detail="async unauthorized")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            app.dependency_overrides[get_current_principal] = async_ok_principal
            xff_async = {"X-Forwarded-For": "198.51.100.88"}
            assert client.get("/worlds/w_sec10/cards", headers=xff_async).status_code == 200
            assert client.get("/worlds/w_sec10/cards", headers=xff_async).status_code == 200
            limited = client.get("/worlds/w_sec10/cards", headers={"X-Forwarded-For": "198.51.100.89"})
            assert limited.status_code == 429
            assert limited.json()["scope"] == "user"

            app.dependency_overrides[get_current_principal] = async_bad_principal
            assert client.get("/worlds/w_sec10/cards", headers={"X-Forwarded-For": "198.51.100.90"}).status_code == 401

        unawaited = [w for w in caught if "was never awaited" in str(w.message)]
        assert unawaited == []
    finally:
        app.dependency_overrides.clear()


def test_SEC_10_local_load_test_trips_cleanly_and_recovers() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    cfg = RateLimitConfig(ip_capacity=100, ip_refill_per_s=20.0, user_capacity=15, user_refill_per_s=5.0)
    store = _seed_store()

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id="u_alice", role="owner", world_id="w_sec10"
    )
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_rate_limit_config] = lambda: cfg

    try:
        client = TestClient(app)

        def _hit(_: int) -> tuple[int, str | None, dict]:
            resp = client.get("/worlds/w_sec10/cards")
            return resp.status_code, resp.headers.get("Retry-After"), resp.json()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_hit, range(40)))

        ok_count = sum(1 for status, _, _ in results if status == 200)
        limited = [(status, retry, body) for status, retry, body in results if status == 429]

        assert ok_count == 15
        assert len(limited) == 25
        for _, retry_hdr, body in limited:
            assert retry_hdr is not None and int(retry_hdr) >= 1
            assert body["code"] == "rate_limit_exceeded"
            assert body["scope"] == "user"
            assert "Rate limit exceeded" in body["detail"]

        clock.advance(1.0)
        recovered = client.get("/worlds/w_sec10/cards")
        assert recovered.status_code == 200
    finally:
        app.dependency_overrides.clear()
