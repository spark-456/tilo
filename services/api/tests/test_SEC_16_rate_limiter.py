"""SEC-16, the rate limiter on its own: "a per-uid rate limit ... over the rate limit gets 429" (PRD supplement 4).

`tilo_api.spend.RateLimiter(*, limit, window_s, clock)` is a sliding-window limiter keyed by the verified uid string it
is given (the HTTP wiring is in test_SEC_16_api_rate_limit.py). `check(uid)` returns a decision with `allowed` and
`retry_after_s`: a whole number of seconds, at least 1, never more than the window, rounded up. A denied check is not
recorded (a flood cannot extend its own lock-out). Written from the PRD text before any builder touches it.
"""

from __future__ import annotations

import threading

import pytest
from _sec16_lib import FakeClock
from hypothesis import given, settings
from hypothesis import strategies as st


def limiter(limit=3, window_s=60, clock=None):
    from tilo_api.spend import RateLimiter

    return RateLimiter(limit=limit, window_s=window_s, clock=clock or FakeClock())


def test_SEC_16_the_limit_is_allowed_and_one_over_is_denied_with_a_retry_after():
    clock = FakeClock(1_020.0)
    rl = limiter(3, 60, clock)

    assert [rl.check("u_a").allowed for _ in range(3)] == [True, True, True]  # exactly the limit passes
    over = rl.check("u_a")  # one over does not

    assert over.allowed is False
    assert over.retry_after_s == 60
    assert type(over.retry_after_s) is int


def test_SEC_16_retry_after_counts_down_and_is_rounded_up():
    clock = FakeClock(1_020.0)
    rl = limiter(2, 60, clock)
    rl.check("u_a")
    rl.check("u_a")

    clock.advance(30)
    assert rl.check("u_a").retry_after_s == 30
    clock.advance(0.2)
    assert rl.check("u_a").retry_after_s == 30, (
        "29.8 s left rounds up to 30, never down to 29 (a 429 must not lie early)"
    )
    clock.advance(29.7)
    assert rl.check("u_a").retry_after_s == 1, "never 0 while still denied"


def test_SEC_16_the_window_slides_open_again_and_denied_checks_are_not_recorded():
    clock = FakeClock(1_020.0)
    rl = limiter(3, 60, clock)
    for _ in range(3):
        assert rl.check("u_a").allowed
    for _ in range(20):  # a flood while denied
        clock.advance(2)
        assert rl.check("u_a").allowed is False

    clock.advance(20)  # 1,020 + 60 has passed: the three allowed hits have left the window
    assert rl.check("u_a").allowed is True, "denied attempts must not extend the lock-out"


def test_SEC_16_each_uid_has_its_own_window():
    rl = limiter(2, 60)
    assert rl.check("u_a").allowed and rl.check("u_a").allowed
    assert rl.check("u_a").allowed is False
    assert rl.check("u_b").allowed and rl.check("u_b").allowed, "one uid's flood never limits another"
    assert rl.check("u_b").allowed is False


def test_SEC_16_idle_uid_buckets_expire_and_active_uid_remains_limited():
    clock = FakeClock(0.0)
    rl = limiter(1, 5, clock)
    rl.IDLE_TTL_S = 5
    assert rl.check("idle").allowed
    assert rl.check("active").allowed
    clock.advance(4)
    assert rl.check("active").allowed is False
    clock.advance(2)
    assert rl.check("fresh").allowed
    assert "idle" not in rl._hits
    assert "active" in rl._hits


def test_SEC_16_uid_bucket_count_is_bounded():
    rl = limiter(1, 5)
    rl.MAX_UIDS = 5
    for i in range(5):
        assert rl.check(f"uid-{i}").allowed
    assert len(rl._hits) <= rl.MAX_UIDS
    assert rl.check("uid-5").allowed is False
    assert rl.check("uid-0").allowed is False, "capacity pressure must not erase an active uid's window"


def test_SEC_16_idle_ttl_never_shortens_a_longer_rate_window():
    clock = FakeClock(0.0)
    rl = limiter(1, 3_600, clock)
    assert rl.check("uid").allowed
    clock.advance(1_801)
    assert rl.check("uid").allowed is False
    assert "uid" in rl._hits


def test_SEC_16_a_uid_is_a_uid_only_whatever_it_looks_like():
    """The key is exactly the string given: no case folding, trimming or prefix matching that two different
    people's ids could collide through (and no way for one to share a bucket with a victim)."""
    rl = limiter(1, 60)
    assert rl.check("u_a").allowed
    for other in ("U_A", "u_a ", " u_a", "u_a\x00", "u_", "u_ab", "u_a/../u_b"):
        assert rl.check(other).allowed, f"{other!r} is a different uid"


def test_SEC_16_the_limit_and_window_come_from_the_caller_not_a_literal():
    rl = limiter(1, 5)
    clock_free = rl.check("u_a")
    assert clock_free.allowed and rl.check("u_a").retry_after_s <= 5


def test_SEC_16_concurrent_checks_never_let_more_than_the_limit_through():
    clock = FakeClock(1_020.0)
    rl = limiter(10, 60, clock)
    results: list[bool] = []
    gate = threading.Barrier(40)

    def hit() -> None:
        gate.wait()
        results.append(rl.check("u_a").allowed)

    threads = [threading.Thread(target=hit) for _ in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert results.count(True) == 10, f"exactly the limit passes under a race, got {results.count(True)}"


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, None])
def test_SEC_16_a_limit_that_is_not_a_positive_integer_is_refused(bad):
    with pytest.raises((TypeError, ValueError)):
        limiter(limit=bad)


@pytest.mark.parametrize("bad", [0, -60, 0.5, True, None])
def test_SEC_16_a_window_that_is_not_a_positive_integer_is_refused(bad):
    with pytest.raises((TypeError, ValueError)):
        limiter(window_s=bad)


@settings(max_examples=75, deadline=None)
@given(
    limit=st.integers(min_value=1, max_value=6),
    window=st.integers(min_value=1, max_value=30),
    hits=st.lists(
        st.tuples(st.sampled_from(["u_a", "u_b", "u_c"]), st.floats(min_value=0, max_value=20, allow_nan=False)),
        max_size=60,
    ),
)
def test_SEC_16_property_a_uid_never_gets_more_than_the_limit_in_any_window(limit, window, hits):
    clock = FakeClock(0.0)
    rl = limiter(limit, window, clock)
    allowed_at: dict[str, list[float]] = {}
    for uid, gap in hits:
        clock.advance(gap)
        decision = rl.check(uid)
        if decision.allowed:
            allowed_at.setdefault(uid, []).append(clock.now)
        else:
            assert 1 <= decision.retry_after_s <= window
    for uid, times in allowed_at.items():
        for i, t in enumerate(times):
            in_window = [x for x in times if t - window < x <= t]
            assert len(in_window) <= limit, f"{uid}: {len(in_window)} allowed within {window}s of t={t}"
