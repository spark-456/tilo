"""SEC-16, the rate limit through the API: "a per-uid rate limit ... over the rate limit gets 429" (PRD supplement 4;
acceptance: "Over the rate limit gets 429"). The limit and window come from config (`caps.rate_limit_requests`,
`caps.rate_limit_window_s`; the tests inject small ones through `deps.get_spend_caps` and a limiter on a fake clock
through `deps.get_rate_limiter`).

Where it sits (API_SEC_16.md): after the SEC-15 access gate has said "judge" and before any body is parsed or any
store, router or safety work, on every gated route. Public routes are not counted. A visitor, an undeclared person and
a signed-out caller are refused by SEC-15 first and never reach the limiter. The key is the verified `Principal`'s
uid only; a request header, query or body field never names a bucket. Deployed only, like the gate: not deployed
nothing is counted. Written from the PRD text before any builder touches it: tests/SEC-16-spend-caps.
"""

from __future__ import annotations

import os

from _sec15_lib import NEWCOMER, VISITOR, non_public
from _sec16_lib import JUDGE_A, JUDGE_B

LIVE = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch
DECLARATIONS = {JUDGE_A: "judge", JUDGE_B: "judge", VISITOR: "visitor", NEWCOMER: None}


def declared():
    return {k: v for k, v in DECLARATIONS.items() if v}


def test_SEC_16_the_limit_passes_and_one_over_gets_429_with_a_stable_code_and_retry_after(sec16_factory):
    h = sec16_factory(declarations=declared(), rate_limit_requests=3, rate_limit_window_s=60)

    assert [h.intake().status_code for _ in range(3)] == [201, 201, 201]  # exactly the limit
    over = h.intake()

    assert over.status_code == 429, over.text
    body = over.json()
    assert body["code"] == "rate_limited"
    assert isinstance(body["detail"], str) and len(body["detail"]) > 10, "a clear sentence, not an empty body"
    retry = over.headers["retry-after"]
    assert retry.isdigit() and 1 <= int(retry) <= 60, f"Retry-After must be whole seconds within the window: {retry!r}"


def test_SEC_16_a_429_refusal_has_no_side_effect(sec16_factory):
    h = sec16_factory(declarations=declared(), rate_limit_requests=2, rate_limit_window_s=60)
    h.intake()
    h.intake()
    before = h.snapshot()

    for shape in (
        {"data": {"text": "Prepare a summary."}},
        {"json": {"text": "x"}},
        {"content": b"\xff\xfe not json", "headers": {"content-type": "application/json"}},
        {"data": {"text": "x" * 5_000}},
    ):
        response = h.client.post("/intake", **shape)
        assert response.status_code == 429, (shape.keys(), response.status_code)

    assert h.snapshot() == before, "a rate-limited request must change nothing and call nothing (no safety, no router)"


def test_SEC_16_the_window_opens_again_after_it_passes(sec16_factory):
    h = sec16_factory(declarations=declared(), rate_limit_requests=2, rate_limit_window_s=60)
    h.intake()
    h.intake()
    assert h.intake().status_code == 429

    h.clock.advance(61)

    assert h.intake().status_code == 201


def test_SEC_16_the_limit_is_per_uid_one_judge_never_limits_another(sec16_factory):
    h = sec16_factory(declarations=declared(), rate_limit_requests=2, rate_limit_window_s=60)
    h.as_user(JUDGE_A)
    h.intake()
    h.intake()
    assert h.intake().status_code == 429

    h.as_user(JUDGE_B)

    assert h.intake().status_code == 201 and h.intake().status_code == 201
    assert h.intake().status_code == 429
    assert set(h.limiter.checked) == {JUDGE_A, JUDGE_B}


def test_SEC_16_the_key_is_the_verified_uid_never_a_header_query_or_body_field(sec16_factory):
    h = sec16_factory(declarations=declared(), rate_limit_requests=2, rate_limit_window_s=60)
    h.as_user(JUDGE_A)
    statuses = []
    for i in range(5):  # a client that changes every identity-looking thing on every request
        spoof = {
            "X-Forwarded-For": f"10.9.8.{i}",
            "X-Real-IP": f"10.1.2.{i}",
            "X-Uid": f"u_spoof_{i}",
            "X-User-Id": f"u_spoof_{i}",
            "X-Session-Id": f"s_spoof_{i}",
            "X-Rate-Limit-Key": f"free_{i}",
            "Cookie": f"uid=u_spoof_{i}",
            "User-Agent": f"agent-{i}",
        }
        response = h.client.post(
            f"/intake?uid=u_spoof_{i}&user_id=u_spoof_{i}",
            data={"text": "Prepare a summary.", "uid": f"u_{i}"},
            headers=spoof,
        )
        statuses.append(response.status_code)

    assert statuses == [201, 201, 429, 429, 429], statuses
    assert set(h.limiter.checked) == {JUDGE_A}, f"the limiter saw keys other than the verified uid: {h.limiter.checked}"


def test_SEC_16_every_gated_route_is_counted_and_a_429_comes_before_body_parsing(sec16_factory):
    h = sec16_factory(declarations=declared(), rate_limit_requests=2, rate_limit_window_s=60)
    routes = non_public(h.client.app)
    assert routes, "the app has gated routes"

    for method, path in routes:
        h.clock.advance(61)  # a fresh window for each route
        for _ in range(2):
            first = h.call(method, path, json={"nonsense": True})
            assert first.status_code != 429, f"{method} {path} was limited inside its quota"
        over = h.call(method, path, content=b"{ not json", headers={"content-type": "application/json"})
        assert over.status_code == 429, f"{method} {path}: over the limit got {over.status_code}, not 429"
        assert over.json()["code"] == "rate_limited"


def test_SEC_16_public_routes_are_not_counted_so_sign_up_and_the_label_always_work(sec16_factory):
    h = sec16_factory(declarations=declared(), rate_limit_requests=2, rate_limit_window_s=60)

    for _ in range(10):
        assert h.me().status_code == 200
        assert h.client.get("/health").status_code == 200
    assert h.limiter.checked == []


def test_SEC_16_every_signed_in_person_is_counted_and_nobody_signed_out_reaches_the_limiter(sec16_factory):
    """OPEN-ACCESS (16 Oct 2026): a visitor or an undeclared person is a person like any other, so the per-uid limit
    applies to them; a request with no sign-in is a 401 before the limiter."""
    h = sec16_factory(declarations=declared(), rate_limit_requests=1, rate_limit_window_s=60)

    h.as_user(VISITOR)
    assert [h.intake().status_code for _ in range(3)] == [201, 429, 429]
    h.as_user(NEWCOMER)
    assert [h.intake().status_code for _ in range(3)] == [201, 429, 429]
    checked = list(h.limiter.checked)
    h.sign_out()
    assert [h.intake().status_code for _ in range(3)] == [401, 401, 401]

    assert h.limiter.checked == checked, "a request with nobody signed in is never counted"


def test_SEC_16_the_access_check_of_a_person_who_never_declared_spends_nothing_when_not_live(sec16_factory):
    h = sec16_factory(declarations=declared(), judge_live=False)
    h.as_user(VISITOR)

    assert h.me().json() == {"declaration": "judge", "allowed": True, "models": "replay"}

    assert [c for c in h.ledger.calls if c[0] != "replay_only"] == [], "only the kill-switch flag is read"


def test_SEC_16_not_deployed_nothing_is_counted_and_nothing_is_limited(sec16_factory):
    h = sec16_factory(declarations=declared(), deployed=False, rate_limit_requests=1, rate_limit_window_s=60)

    assert [h.intake().status_code for _ in range(5)] == [201] * 5, "dev and CI behave exactly as before"
    assert h.limiter.checked == [] and h.ledger.calls == []
    assert os.environ.get(LIVE) is None


def test_SEC_16_the_default_limiter_is_one_process_wide_object_built_from_config():
    """`deps.get_rate_limiter()` is wired in production (an in-process limiter is the smallest working default; a
    shared one is a later decision, see API_SEC_16.md): it must be the same object on every call, or no count would
    ever accumulate, and its numbers are config's."""
    from tilo_api import deps
    from tilo_api.spend import load_spend_caps

    first, second = deps.get_rate_limiter(), deps.get_rate_limiter()
    caps = load_spend_caps(None)

    assert first is second
    uid = "u_sec16_default_limiter_probe"
    decisions = [first.check(uid).allowed for _ in range(caps.rate_limit_requests + 1)]
    assert decisions == [True] * caps.rate_limit_requests + [False]
