"""SEC-15 (docs/prd-supplement-2026-10-05.md section 4): "Deployed access: sign-up asks 'visitor or Google AI
Builder Cup judge?'. Visitors see 'still under construction, not open to the public' and get no access; judges
get live models (never forced to replay). Enforced server-side from the stored declaration."
Acceptance: "A visitor's API calls are refused server-side; a judge's run uses live models."

This file is the visitor half: a deterministic gate on every non-public route, driven only by the stored
declaration (never a header, a query, a cookie or a body field), failing closed when the declaration is missing
or its store is not wired. Contract of the seams: services/api/tests/API_SEC_15.md. Written from the PRD text
before any builder touches it: tests/SEC-15-deployed-access.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from _sec15_lib import (
    CODE_DECLARATION_REQUIRED,
    CODE_UNDER_CONSTRUCTION,
    JUDGE,
    NEWCOMER,
    OTHER,
    PINNED_PUBLIC_LINK_ROUTES,
    PINNED_PUBLIC_ROUTES,
    VISITOR,
    concrete,
    non_public,
    route_table,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import app, deps

NON_PUBLIC = non_public(app)
IDS = [f"{m} {p}" for m, p in NON_PUBLIC]
GATE_CODES = {CODE_UNDER_CONSTRUCTION, CODE_DECLARATION_REQUIRED}
USER_ID = st.from_regex(r"u_[0-9A-Za-z_]{1,48}", fullmatch=True)


def bodies(method: str) -> list[dict]:
    """The request shapes a browser can send to a route: none, an empty JSON object, an empty body of an unknown
    type, a urlencoded form. The gate must answer before the route reads any of them."""
    if method in {"GET", "DELETE"}:
        return [{}]
    return [
        {},
        {"json": {}},
        {"content": b"", "headers": {"content-type": "text/plain"}},
        {"data": {"anything": "x"}},
    ]


def gate_refusal(response) -> str | None:
    """The gate's code when `response` is one of its refusals, else None."""
    if response.status_code != 403:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("code") if isinstance(body, dict) and body.get("code") in GATE_CODES else None


def test_SEC_15_route_table_is_not_empty_and_public_allowlist_is_exactly_the_pinned_set():
    from tilo_api import access  # the module that owns the allowlist

    table = route_table(app)
    assert len(NON_PUBLIC) >= 12, f"the property below must not be vacuous: {len(NON_PUBLIC)} non-public routes"
    assert set(access.PUBLIC_ROUTES) == set(PINNED_PUBLIC_ROUTES), (
        "adding or removing a public route is a decision for the owner: update API_SEC_15.md and this test"
    )
    missing = sorted(set(PINNED_PUBLIC_ROUTES) - set(table))
    assert not missing, f"the pinned public routes are not served: {missing}"


def test_SEC_15_the_mail_link_prefix_is_the_only_extra_public_set_and_is_named_on_purpose():
    """FR-PA-06b (the owner's decision, BQ-PA06B-1): `GET` and `POST` of `/l/<token>` are public to the gate because a
    mail click has no session; the signed single-use token is the credential. Nothing else is public by prefix."""
    from tilo_api import access

    table = route_table(app)
    by_prefix = {r for r in table if access.public_link(r[0], concrete(r[1]))}
    assert by_prefix == set(PINNED_PUBLIC_LINK_ROUTES), "a new public path is the owner's decision: update this test"
    assert set(PINNED_PUBLIC_LINK_ROUTES) <= set(table)
    assert not set(PINNED_PUBLIC_LINK_ROUTES) & set(PINNED_PUBLIC_ROUTES)
    for method, path in [
        ("PUT", "/l/x"),
        ("DELETE", "/l/x"),
        ("GET", "/l/"),
        ("GET", "/l/a/b"),
        ("GET", "/l"),
        ("GET", "/L/x"),
    ]:
        assert not access.public_link(method, path), (method, path)
    assert not access.public_link("GET", "/l/" + "a" * 513)  # past the cap it is an ordinary, gated path
    assert not access.public_link("POST", "/v1/plate") and not access.public_link("GET", "/links/x")


@pytest.mark.parametrize(("method", "path"), NON_PUBLIC, ids=IDS)
def test_SEC_15_visitor_is_refused_server_side_on_every_non_public_route(sec15_factory, method, path):
    sec = sec15_factory(declarations={VISITOR: "visitor"})
    sec.as_user(VISITOR)
    before = sec.snapshot()

    for shape in bodies(method):
        response = sec.call(method, path, **shape)

        assert response.status_code == 403, f"{method} {path} {shape!r}: {response.status_code} {response.text[:200]}"
        body = response.json()
        assert body.get("code") == CODE_UNDER_CONSTRUCTION, body
        text = str(body.get("detail", "")).lower()
        assert "still under construction" in text, body  # the words PRD SEC-15 gives the person
        assert "not open to the public" in text, body

    assert sec.snapshot() == before, "a refused visitor changed state, ran the safety screen or built a router"


@pytest.mark.parametrize(("method", "path"), NON_PUBLIC, ids=IDS)
def test_SEC_15_no_declaration_fails_closed_on_every_non_public_route(sec15_factory, method, path):
    sec = sec15_factory(declarations={})  # signed in, never answered the question
    sec.as_user(NEWCOMER)
    before = sec.snapshot()

    for shape in bodies(method):
        response = sec.call(method, path, **shape)

        assert response.status_code == 403, f"{method} {path}: {response.status_code} {response.text[:200]}"
        assert response.json().get("code") == CODE_DECLARATION_REQUIRED, response.text

    assert sec.snapshot() == before


@pytest.mark.parametrize(("method", "path"), NON_PUBLIC, ids=IDS)
def test_SEC_15_judge_is_let_through_the_gate_on_every_non_public_route(sec15_factory, method, path):
    sec = sec15_factory(declarations={JUDGE: "judge"})
    sec.as_user(JUDGE)

    for shape in bodies(method):
        response = sec.call(method, path, **shape)

        assert gate_refusal(response) is None, f"{method} {path}: the gate refused a judge: {response.text[:200]}"
        assert response.status_code != 401  # the route's own answer (404, 415, 422, 2xx), never the gate's


def test_SEC_15_unwired_access_store_closes_every_non_public_route(sec15_factory, monkeypatch):
    """A deployed process whose declarations cannot be read gives nobody access (fail closed)."""
    from tilo_api import rate_limit  # noqa: PLC0415

    # One person calls every non-public route here; the SEC-10 edge limiter (its own tests: test_SEC_10) gets room so
    # the access gate is what answers, as the people rigs do.
    rate_limit.reset_default_rate_limiter()
    wide = rate_limit.RateLimitConfig(
        ip_capacity=1_000_000, ip_refill_per_s=1_000_000.0, user_capacity=1_000_000, user_refill_per_s=1_000_000.0
    )
    monkeypatch.setattr(rate_limit, "get_rate_limit_config", lambda: wide)
    sec = sec15_factory(declarations={JUDGE: "judge"})
    for key in [k for k in app.dependency_overrides if getattr(k, "__name__", "") == "get_access_store"]:
        del app.dependency_overrides[key]
    assert hasattr(deps, "get_access_store"), "deps.get_access_store is the pinned seam (API_SEC_15.md)"
    sec.as_user(JUDGE)
    before = sec.snapshot()

    for method, path in NON_PUBLIC:
        response = sec.call(method, path)
        assert response.status_code in {403, 503}, f"{method} {path}: {response.status_code} {response.text[:200]}"

    assert sec.snapshot() == before
    assert sec.client.get("/health").status_code == 200, "the Cloud Run smoke check never needs the access store"


def test_SEC_15_signed_out_is_401_before_any_declaration_is_read(sec15_factory):
    sec = sec15_factory(declarations={JUDGE: "judge"})
    sec.sign_out()

    for method, path in NON_PUBLIC:
        assert sec.call(method, path).status_code == 401, f"{method} {path}"
    assert sec.access.reads == [], "the declaration store was read for a request with no signed-in person"
    assert sec.client.get("/health").status_code == 200
    assert sec.client.get("/access").status_code == 401


def test_SEC_15_the_gate_runs_before_any_world_lookup_so_there_is_no_oracle(sec15_factory):
    sec = sec15_factory(declarations={VISITOR: "visitor", OTHER: "judge"})
    from _api_lib import WORLD, make_world

    sec.store.worlds[WORLD] = make_world(owner=OTHER)
    sec.as_user(VISITOR)

    known = sec.client.get(f"/worlds/{WORLD}/events")
    unknown = sec.client.get("/worlds/w_does_not_exist/events")

    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert known.status_code == 403 and known.json()["code"] == CODE_UNDER_CONSTRUCTION


def test_SEC_15_a_visitor_can_still_ask_what_it_is_allowed_and_the_health_check_is_public(sec15_factory):
    sec = sec15_factory(declarations={VISITOR: "visitor"})
    sec.as_user(VISITOR)

    me = sec.me()

    assert me.status_code == 200, me.text
    assert me.json() == {"declaration": "visitor", "allowed": False, "models": None}
    assert sec.client.get("/health").status_code == 200
    assert sec.client.get("/healthz").status_code == 200


FORGERIES = [
    {"headers": {"X-Tilo-Declaration": "judge"}},
    {"headers": {"X-Declaration": "judge", "X-Tilo-Role": "judge", "X-Judge": "1"}},
    {"headers": {"Cookie": "declaration=judge; judge=1; role=judge"}},
    {"headers": {"X-Forwarded-User": JUDGE, "X-Goog-Authenticated-User-Email": "accounts.google.com:judge"}},
    {"params": {"declaration": "judge", "judge": "1", "role": "judge", "allowed": "true"}},
]


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(route=st.sampled_from(NON_PUBLIC), forgery=st.sampled_from(FORGERIES), user_id=USER_ID)
def test_SEC_15_property_a_client_supplied_judge_claim_never_opens_a_route(sec15_factory, route, forgery, user_id):
    sec = sec15_factory(declarations={user_id: "visitor"})
    sec.as_user(user_id)
    method, path = route
    shape = dict(forgery)
    if method not in {"GET", "DELETE"}:
        shape["json"] = {"declaration": "judge", "role": "judge", "allowed": True, "user_id": JUDGE}

    response = sec.call(method, path, **shape)

    assert gate_refusal(response) == CODE_UNDER_CONSTRUCTION, f"{method} {path} {forgery}: {response.status_code}"


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    route=st.sampled_from(NON_PUBLIC),
    declaration=st.sampled_from([None, "visitor", "judge"]),
    user_id=USER_ID,
)
def test_SEC_15_property_the_decision_depends_only_on_the_stored_declaration(
    sec15_factory, route, declaration, user_id
):
    sec = sec15_factory(declarations={} if declaration is None else {user_id: declaration})
    sec.as_user(user_id)
    method, path = route

    response = sec.call(method, path)

    expected = {None: CODE_DECLARATION_REQUIRED, "visitor": CODE_UNDER_CONSTRUCTION, "judge": None}[declaration]
    assert gate_refusal(response) == expected, f"{declaration}: {method} {path}: {response.status_code}"


def test_SEC_15_each_person_has_their_own_declaration(sec15_factory):
    sec = sec15_factory(declarations={VISITOR: "visitor", JUDGE: "judge"})

    sec.as_user(JUDGE)
    assert gate_refusal(sec.client.get(concrete("/worlds/{world_id}/events"))) is None
    sec.as_user(VISITOR)
    assert gate_refusal(sec.client.get(concrete("/worlds/{world_id}/events"))) == CODE_UNDER_CONSTRUCTION
    sec.as_user(JUDGE)
    assert gate_refusal(sec.client.get(concrete("/worlds/{world_id}/events"))) is None


# --- regression guards: dev mode and CI are unchanged (these pass before and after the feature) -------------


def test_SEC_15_not_deployed_the_gate_is_off_and_needs_no_access_store(sec15_factory):
    """No K_SERVICE / CLOUD_RUN_JOB: the whole existing suite and `just dev-api` run as before. A stored
    'visitor' is not enforced and no access store is required (the pinned seam is simply not consulted)."""
    sec = sec15_factory(declarations={VISITOR: "visitor"}, deployed=False)
    for key in [k for k in app.dependency_overrides if getattr(k, "__name__", "") == "get_access_store"]:
        del app.dependency_overrides[key]
    sec.as_user(VISITOR)

    for method, path in NON_PUBLIC:
        assert gate_refusal(sec.call(method, path)) is None, f"{method} {path}"
    assert sec.access.reads == []


def test_SEC_15_dev_mode_serves_its_fixed_owner_with_no_declaration():
    """`TILO_API_DEV=1` on the real module (as `just dev-api` does): the one dev owner has no declaration and
    must still reach its routes. Runs in a subprocess because `tilo_api` reads the flag at import."""
    script = (
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "import tilo_api\n"
        "c = TestClient(tilo_api.app, base_url='http://localhost:8080')\n"
        "out = []\n"
        "for path in ('/worlds/w_none/events', '/tasks/t_none/approaches', '/health'):\n"
        "    r = c.get(path)\n"
        "    out.append([path, r.status_code, r.text])\n"
        "print('RESULT ' + json.dumps(out))\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in {"K_SERVICE", "CLOUD_RUN_JOB", "LIVE", "TILO_JUDGE_LIVE"}}
    env["TILO_API_DEV"] = "1"
    done = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=180, check=False
    )
    line = next((x for x in done.stdout.splitlines() if x.startswith("RESULT ")), None)
    assert line, f"the dev app did not answer: {done.stderr[-800:]}"
    results = json.loads(line[len("RESULT ") :])
    for path, status, text in results:
        assert status in {200, 404}, f"{path}: {status} {text[:200]}"
        assert CODE_UNDER_CONSTRUCTION not in text and CODE_DECLARATION_REQUIRED not in text, (path, text)
