"""SEC-10: Per-user and per-IP rate limits on services/api public routes with 429, clear JSON message,
Retry-After header, replaceable store interface, and local load test (fake providers).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from tilo_api import app
from tilo_api.access import InMemoryAccessStore
from tilo_api.deps import Principal, Store, WorldRecord, get_access_store, get_current_principal, get_store
from tilo_api.rate_limit import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RateLimiter,
    get_rate_limit_config,
    get_rate_limiter,
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

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_access_store] = lambda: access_store
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=current_user["id"], role="owner", world_id="w_sec10"
    )
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
        app.dependency_overrides[get_current_principal] = lambda: Principal(
            user_id="u_bob", role="owner", world_id="w_sec10_bob"
        )
        assert client.get("/worlds/w_sec10_bob/cards").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_SEC_10_per_ip_rate_limit_resists_xff_spoofing_and_exempts_healthz() -> None:
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)
    cfg = RateLimitConfig(ip_capacity=2, ip_refill_per_s=0.5, user_capacity=50, user_refill_per_s=10.0)

    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_rate_limit_config] = lambda: cfg

    try:
        client = TestClient(app)
        r1 = client.get("/access", headers={"X-Forwarded-For": "203.0.113.1"})
        r2 = client.get("/worlds/w_sec10/cards", headers={"X-Forwarded-For": "203.0.113.2"})
        assert r1.status_code == 401
        assert r2.status_code == 401

        r3 = client.get("/access", headers={"X-Forwarded-For": "203.0.113.3"})
        assert r3.status_code == 429
        assert r3.headers["Retry-After"] == "2"
        payload = r3.json()
        assert payload["code"] == "rate_limit_exceeded"
        assert payload["scope"] == "ip"
        assert payload["retry_after_s"] == 2

        assert client.get("/health").status_code == 200
        assert client.get("/healthz").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_SEC_10_replaceable_shared_store_interface() -> None:
    calls: list[str] = []

    class CustomSharedLimiter:
        def consume(self, key: str, *, capacity: int, refill_per_s: float) -> tuple[bool, int]:
            calls.append(key)
            return False, 7

    custom: RateLimiter = CustomSharedLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: custom
    try:
        client = TestClient(app)
        res = client.get("/worlds/w_sec10/cards")
        assert res.status_code == 429
        assert res.headers["Retry-After"] == "7"
        assert res.json()["retry_after_s"] == 7
        assert calls == ["ip:testclient"]
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
