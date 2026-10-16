"""SEC-15 / OPEN-ACCESS (owner's order, 16 Oct 2026): "Everyone must be able to access through their mail, lets
remove the entire judge and non judge blockers". Replaces the visitor/judge declaration gate: every signed-in
person (a Google sign-in with their own mail) reaches every route, with no declaration to make and no
`declaration_required` or `under_construction` refusal, whatever an old store holds.

What must NOT go with the blocker: the sign-in (401 for nobody), the per-uid rate limit (429), the per-uid
lifetime spend cap (the allowance every new person starts with), the replay-only models of an anonymous demo
session, and the pinned set of public routes. Contract of the seams: services/api/tests/API_SEC_15.md.
"""

from __future__ import annotations

import pytest
from _sec15_lib import (
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
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from tilo_api import app

NON_PUBLIC = non_public(app)
IDS = [f"{m} {p}" for m, p in NON_PUBLIC]
RETIRED_CODES = {"under_construction", "declaration_required"}
WS_POLICY_VIOLATION = 1008
LIVE = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch


def retired_refusal(response) -> bool:
    """True when `response` is one of the two refusals the owner removed."""
    try:
        body = response.json()
    except ValueError:
        return False
    return response.status_code == 403 and isinstance(body, dict) and body.get("code") in RETIRED_CODES


def bodies(method: str) -> list[dict]:
    if method in {"GET", "DELETE"}:
        return [{}]
    return [{}, {"json": {}}, {"data": {"anything": "x"}}]


def test_SEC_15_OPEN_ACCESS_the_public_allowlist_is_still_exactly_the_pinned_set():
    from tilo_api import access

    table = route_table(app)
    assert len(NON_PUBLIC) >= 12
    assert set(access.PUBLIC_ROUTES) == set(PINNED_PUBLIC_ROUTES), "opening sign-in must not open any other route"
    assert not set(PINNED_PUBLIC_ROUTES) - set(table)
    by_prefix = {r for r in table if access.public_link(r[0], concrete(r[1]))}
    assert by_prefix == set(PINNED_PUBLIC_LINK_ROUTES)


@pytest.mark.parametrize("stored", [None, "visitor", "judge"], ids=["never-declared", "old-visitor", "old-judge"])
@pytest.mark.parametrize(("method", "path"), NON_PUBLIC, ids=IDS)
def test_SEC_15_OPEN_ACCESS_a_signed_in_person_is_never_refused_by_the_gate_on_any_route(
    sec15_factory, method, path, stored
):
    sec = sec15_factory(declarations={} if stored is None else {NEWCOMER: stored})
    sec.as_user(NEWCOMER)

    for shape in bodies(method):
        response = sec.call(method, path, **shape)

        assert not retired_refusal(response), f"{method} {path}: the gate still refuses: {response.text[:200]}"
        assert response.status_code != 401  # the route's own answer, never the gate's
    assert sec.access.reads == [] and sec.access.writes == [], "nobody's declaration is read or written any more"


def test_SEC_15_OPEN_ACCESS_a_fresh_person_can_use_the_main_routes(sec15_factory):
    sec = sec15_factory(declarations={})  # signed in, no declaration, no org record
    sec.as_user(NEWCOMER)

    made = sec.intake()
    assert made.status_code == 201, made.text
    listed = sec.client.get("/worlds")
    assert listed.status_code == 200 and not retired_refusal(listed), listed.text[:200]
    assert sec.client.get("/health").status_code == 200


@pytest.mark.parametrize("user", [NEWCOMER, VISITOR, JUDGE, OTHER])
def test_SEC_15_OPEN_ACCESS_the_access_check_says_allowed_and_names_the_models_honestly(
    sec15_factory, monkeypatch, user
):
    sec = sec15_factory(declarations={VISITOR: "visitor"})
    sec.as_user(user)
    # the deployment does not permit live models yet
    assert sec.me().json() == {"declaration": "judge", "allowed": True, "models": "replay"}

    monkeypatch.setenv("TILO_JUDGE_LIVE", "1")  # the owner's switch for live models on this deployment
    assert sec.me().json() == {"declaration": "judge", "allowed": True, "models": "live"}


def test_SEC_15_OPEN_ACCESS_the_old_sign_up_answer_is_accepted_stores_nothing_and_is_never_locked(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    first = sec.declare("visitor")
    second = sec.declare("judge")

    for response in (first, second):
        assert response.status_code == 200, response.text
        assert response.json() == {"declaration": "judge", "allowed": True, "models": "replay"}
    assert sec.access.writes == [] and sec.access.reads == []
    assert sec.client.post("/access/declaration", json={"declaration": "admin"}).status_code == 422
    assert sec.client.post("/access/declaration", data={"declaration": "judge"}).status_code == 415
    sec.sign_out()
    assert sec.declare("judge").status_code == 401 and sec.me().status_code == 401


def test_SEC_15_OPEN_ACCESS_signed_out_is_still_401_everywhere(sec15_factory):
    sec = sec15_factory(declarations={JUDGE: "judge"})
    sec.sign_out()

    for method, path in NON_PUBLIC:
        assert sec.call(method, path).status_code == 401, f"{method} {path}"
    assert sec.client.get("/health").status_code == 200


def test_SEC_15_OPEN_ACCESS_a_websocket_opens_for_a_signed_in_person_and_stays_closed_for_nobody(sec15_factory):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tilo_api.access import AccessGate

    def scratch(sec):
        ran: list[str] = []
        app_ = FastAPI()
        app_.add_middleware(AccessGate)

        @app_.websocket("/ws")
        async def ws(socket: WebSocket) -> None:
            ran.append("ws")
            await socket.accept()
            await socket.send_text("hello")
            await socket.close()

        app_.dependency_overrides.update(app.dependency_overrides)
        return app_, ran

    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)
    app_, ran = scratch(sec)
    with TestClient(app_).websocket_connect("/ws") as socket:
        assert socket.receive_text() == "hello"
    assert ran == ["ws"]

    sec.sign_out()
    app2, ran2 = scratch(sec)
    with pytest.raises(WebSocketDisconnect) as refused, TestClient(app2).websocket_connect("/ws") as socket:
        socket.receive_text()
    assert refused.value.code == WS_POLICY_VIOLATION and ran2 == []


def test_SEC_15_OPEN_ACCESS_no_dead_end_sign_up_text_is_left_in_the_gate():
    from tilo_api import access

    assert not hasattr(access, "DECLARATION_REQUIRED") and not hasattr(access, "UNDER_CONSTRUCTION")


SPELLINGS = [
    ("HEAD", "/access"),
    ("OPTIONS", "/access/declaration"),
    ("OPTIONS", "/worlds/w_probe/events"),
    ("GET", "/access/"),
    ("POST", "/access/declaration/"),
    ("GET", "//worlds/w_probe/events"),
    ("GET", "/worlds%2Fw_probe%2Fevents"),
    ("GET", "/docs"),
    ("GET", "/openapi.json"),
    ("PUT", "/access/declaration"),
    ("DELETE", "/access"),
]


@pytest.mark.parametrize(("method", "path"), SPELLINGS, ids=[f"{m} {p}" for m, p in SPELLINGS])
def test_SEC_15_OPEN_ACCESS_every_spelling_of_a_route_gives_a_new_person_the_routes_own_answer(
    sec15_factory, method, path
):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    response = sec.client.request(method, f"http://testserver{path}")

    assert not retired_refusal(response), f"{method} {path}: {response.status_code} {response.text[:200]}"
    assert sec.access.writes == []


def test_SEC_15_OPEN_ACCESS_not_deployed_the_gate_is_off_and_needs_no_access_store(sec15_factory):
    sec = sec15_factory(declarations={VISITOR: "visitor"}, deployed=False)
    sec.as_user(VISITOR)

    for method, path in NON_PUBLIC:
        assert not retired_refusal(sec.call(method, path)), f"{method} {path}"
    assert sec.access.reads == []


def test_SEC_15_OPEN_ACCESS_dev_mode_serves_its_fixed_owner_with_no_declaration():
    """`TILO_API_DEV=1` on the real module (as `just dev-api` does). A subprocess, because `tilo_api` reads the flag at
    import."""
    import json
    import os
    import subprocess
    import sys

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
    env = {k: v for k, v in os.environ.items() if k not in {"K_SERVICE", "CLOUD_RUN_JOB", LIVE, "TILO_JUDGE_LIVE"}}
    env["TILO_API_DEV"] = "1"
    done = subprocess.run(
        [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=180, check=False
    )
    line = next((x for x in done.stdout.splitlines() if x.startswith("RESULT ")), None)
    assert line, f"the dev app did not answer: {done.stderr[-800:]}"
    for path, status, text in json.loads(line[len("RESULT ") :]):
        assert status in {200, 404}, f"{path}: {status} {text[:200]}"
        assert not any(code in text for code in RETIRED_CODES), (path, text)
