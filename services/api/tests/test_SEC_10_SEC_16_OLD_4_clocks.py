"""OLD-4: both real limiter layers must follow the acceptance harness's clock."""

from tilo_api.rate_limit import RateLimitConfig, get_rate_limit_config


def test_SEC_10_SEC_16_OLD_4_edge_limit_remains_enforced_and_refills_on_the_fake_clock(sec16_factory):
    h = sec16_factory(rate_limit_requests=10, uid_lifetime_minor=100_000)
    h.client.app.dependency_overrides[get_rate_limit_config] = lambda: RateLimitConfig(
        ip_capacity=2, user_capacity=2, ip_refill_per_s=1 / 60, user_refill_per_s=1 / 60
    )
    assert [h.intake().status_code for _ in range(2)] == [201, 201]
    before = h.snapshot()
    refused = h.intake()
    assert refused.status_code == 429
    assert refused.json()["code"] == "rate_limit_exceeded"
    assert refused.headers["retry-after"].isdigit()
    assert h.snapshot() == before

    h.clock.advance(121)
    assert [h.intake().status_code for _ in range(2)] == [201, 201]
    assert h.intake().status_code == 429
