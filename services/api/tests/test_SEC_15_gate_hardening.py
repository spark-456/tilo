"""SEC-15 gate hardening (security review round 1): the gate must hold for every ASGI scope and every spelling of a
route, not only the plain GET and POST the first tests send. A websocket route is closed before it is accepted for a
visitor, a person who never declared and an unwired store, and still works for a judge; HEAD, OPTIONS, a trailing or
doubled slash, an encoded slash, the docs routes and the wrong verb on the sign-up route all get a visitor the same
refusal body, with no handler run and no state touched. Interface: services/api/tests/API_SEC_15.md."""

from __future__ import annotations

import pytest
from _sec15_lib import JUDGE, NEWCOMER, VISITOR
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from tilo_api.access import DECLARATION_REQUIRED, UNDER_CONSTRUCTION

VISITOR_BODY = {"detail": UNDER_CONSTRUCTION, "code": "under_construction"}
NEWCOMER_BODY = {"detail": DECLARATION_REQUIRED, "code": "declaration_required"}
WS_POLICY_VIOLATION = 1008


def scratch_app(sec):
    """A scratch app under the real gate with a websocket route and a plain route, wired to the same fake principal
    and access store as the real app. Nothing is added to `tilo_api.app`, so the route-table tests are untouched."""
    from fastapi import FastAPI
    from tilo_api import app
    from tilo_api.access import AccessGate

    ran: list[str] = []
    scratch = FastAPI()
    scratch.add_middleware(AccessGate)

    @scratch.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        ran.append("ws")
        await socket.accept()
        await socket.send_text("secret")
        await socket.close()

    @scratch.get("/data")
    def data() -> dict[str, str]:
        ran.append("data")
        return {"secret": "x"}

    scratch.dependency_overrides.update(app.dependency_overrides)
    return scratch, ran


def connect(scratch):
    from fastapi.testclient import TestClient

    with TestClient(scratch).websocket_connect("/ws") as socket:
        return socket.receive_text()


@pytest.mark.parametrize(("user", "declarations"), [(VISITOR, {VISITOR: "visitor"}), (NEWCOMER, {})])
def test_SEC_15_a_websocket_is_closed_before_accept_for_a_visitor_and_an_undeclared_person(
    sec15_factory, user, declarations
):
    sec = sec15_factory(declarations=declarations)
    sec.as_user(user)
    scratch, ran = scratch_app(sec)

    with pytest.raises(WebSocketDisconnect) as refused:
        connect(scratch)

    assert refused.value.code == WS_POLICY_VIOLATION
    assert ran == [], "the websocket handler ran for a person with no access"


def test_SEC_15_a_websocket_is_closed_when_the_access_store_is_not_wired_or_nobody_is_signed_in(sec15_factory):
    sec = sec15_factory(declarations={JUDGE: "judge"})
    sec.as_user(JUDGE)
    scratch, ran = scratch_app(sec)
    for key in [k for k in scratch.dependency_overrides if getattr(k, "__name__", "") == "get_access_store"]:
        del scratch.dependency_overrides[key]

    with pytest.raises(WebSocketDisconnect) as unwired:
        connect(scratch)
    sec.as_user(JUDGE)
    scratch2, _ = scratch_app(sec)
    sec.sign_out()
    with pytest.raises(WebSocketDisconnect) as signed_out:
        connect(scratch2)

    assert unwired.value.code == signed_out.value.code == WS_POLICY_VIOLATION
    assert ran == []


def test_SEC_15_a_judge_connects_to_the_websocket_and_the_same_app_serves_http(sec15_factory):
    from fastapi.testclient import TestClient

    sec = sec15_factory(declarations={JUDGE: "judge"})
    sec.as_user(JUDGE)
    scratch, ran = scratch_app(sec)

    assert connect(scratch) == "secret"
    assert TestClient(scratch).get("/data").status_code == 200
    assert ran == ["ws", "data"]


def test_SEC_15_the_websocket_gate_is_off_when_not_deployed(sec15_factory):
    sec = sec15_factory(declarations={VISITOR: "visitor"}, deployed=False)
    sec.as_user(VISITOR)
    scratch, _ = scratch_app(sec)

    assert connect(scratch) == "secret"


# --- the http spellings the reviewer tried by hand -----------------------------------------------------------

REQUESTS = [
    ("HEAD", "/health"),
    ("HEAD", "/access"),
    ("OPTIONS", "/health"),
    ("OPTIONS", "/access/declaration"),
    ("OPTIONS", "/worlds/w_probe/events"),
    ("GET", "/health/"),
    ("GET", "/access/"),
    ("POST", "/access/declaration/"),
    ("GET", "//health"),
    ("GET", "//access"),
    ("GET", "//worlds/w_probe/events"),
    ("GET", "/worlds%2Fw_probe%2Fevents"),
    ("GET", "/health%2Fz"),
    ("GET", "/docs"),
    ("GET", "/redoc"),
    ("GET", "/openapi.json"),
    ("PUT", "/access/declaration"),
    ("DELETE", "/access/declaration"),
    ("PATCH", "/access/declaration"),
    ("DELETE", "/access"),
]


@pytest.mark.parametrize(("method", "path"), REQUESTS, ids=[f"{m} {p}" for m, p in REQUESTS])
def test_SEC_15_a_visitor_gets_the_same_refusal_for_every_spelling_of_a_route(sec15_factory, method, path):
    sec = sec15_factory(declarations={VISITOR: "visitor"})
    sec.as_user(VISITOR)
    before = sec.snapshot()

    response = sec.client.request(method, f"http://testserver{path}")

    assert response.status_code == 403, f"{method} {path}: {response.status_code} {response.text[:200]}"
    if method != "HEAD":  # a HEAD answer carries no body
        assert response.json() == VISITOR_BODY, f"{method} {path}: {response.text[:200]}"
    assert sec.snapshot() == before
    assert sec.access.writes == []


@pytest.mark.parametrize(("method", "path"), REQUESTS[:4] + REQUESTS[16:], ids=lambda v: str(v))
def test_SEC_15_an_undeclared_person_gets_declaration_required_for_the_same_spellings(sec15_factory, method, path):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    response = sec.client.request(method, f"http://testserver{path}")

    assert response.status_code == 403, f"{method} {path}: {response.status_code}"
    if method != "HEAD":
        assert response.json() == NEWCOMER_BODY
    assert sec.access.writes == []
