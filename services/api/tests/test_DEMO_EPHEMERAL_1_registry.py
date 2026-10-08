"""DEMO-EPHEMERAL-1 (BQ-DEMO-EPH-1): the registry's caps and sweep (fail closed, never evict), the bucket coming only
from the verified token, an unresolvable principal being refused, and a demo schedule being refused. No network."""

from __future__ import annotations

from typing import Any

import pytest
from _demo_eph_lib import Durable, fresh_registry
from _signin_lib import NOW, PROJECT, Fetch, _key, _token
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from tilo_api import deps, ephemeral, firebase_auth
from tilo_api.firebase_auth import user_id_for


class FakeClock:
    def __init__(self) -> None:
        self.t = 5.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture(autouse=True)
def _reset():
    yield
    ephemeral.configure()


def _full(e: HTTPException) -> tuple[int, str]:
    return e.status_code, e.detail


def test_DEMO_EPHEMERAL_1_a_session_past_its_item_cap_is_refused_and_nothing_else_is_touched():
    reg = fresh_registry(max_items=3)
    mine, other = reg.session("u_a"), reg.session("u_b")
    mine.charge(3)
    with pytest.raises(HTTPException) as refused:
        mine.charge(1)
    assert _full(refused.value) == (429, "demo_capacity")
    assert mine.items == 3 and other.items == 0, "a refusal charges nothing and takes nothing from another session"
    other.charge(3)  # another session is unaffected by the first one being full


def test_DEMO_EPHEMERAL_1_a_session_past_its_byte_cap_is_refused():
    reg = fresh_registry(max_bytes=10)
    session = reg.session("u_a")
    session.charge(1, 10)
    with pytest.raises(HTTPException) as refused:
        session.charge(1, 1)
    assert _full(refused.value) == (429, "demo_capacity")


def test_DEMO_EPHEMERAL_1_the_global_cap_refuses_without_evicting_a_live_session():
    reg = fresh_registry(max_total_items=5, max_items=5)
    first, second = reg.session("u_a"), reg.session("u_b")
    first.store.worlds["w_x"] = object()  # type: ignore[assignment]
    first.charge(4)
    with pytest.raises(HTTPException) as refused:
        second.charge(2)
    assert _full(refused.value) == (503, "demo_capacity")
    assert reg.sessions.keys() == {"u_a", "u_b"} and "w_x" in first.store.worlds, "nobody was evicted"
    assert reg.total_items == 4
    second.charge(1)


def test_DEMO_EPHEMERAL_1_no_new_session_past_the_session_cap_and_a_live_one_still_works():
    reg = fresh_registry(max_sessions=2)
    live = reg.session("u_a")
    reg.session("u_b")
    with pytest.raises(HTTPException) as refused:
        reg.session("u_c")
    assert _full(refused.value) == (503, "demo_capacity")
    assert reg.session("u_a") is live and set(reg.sessions) == {"u_a", "u_b"}


def test_DEMO_EPHEMERAL_1_the_ttl_sweep_frees_memory_and_the_counters():
    clock = FakeClock()
    reg = fresh_registry(clock=clock, ttl_s=100.0, max_sessions=2, max_total_items=10)
    old = reg.session("u_a")
    old.charge(4, 40)
    old.store.tasks["t_x"] = object()  # type: ignore[assignment]
    clock.t += 99
    reg.session("u_b").charge(2)
    clock.t += 2  # u_a is idle past its TTL, u_b is not
    reg.sweep()
    assert set(reg.sessions) == {"u_b"} and reg.total_items == 2 and reg.total_bytes == 0
    assert old.store.tasks == {} and old.dead
    with pytest.raises(HTTPException):
        old.charge(1)  # a run still writing into the dropped session stops
    reg.session("u_c")  # the freed slot is usable again


def test_DEMO_EPHEMERAL_1_every_access_sweeps_without_a_background_thread():
    clock = FakeClock()
    reg = fresh_registry(clock=clock, ttl_s=10.0)
    reg.session("u_a").charge(2)
    clock.t += 11
    reg.session("u_b")
    assert set(reg.sessions) == {"u_b"} and reg.total_items == 0


def _mini(monkeypatch):
    durable = Durable(monkeypatch)
    signer = _key()
    verifier = firebase_auth.FirebaseIdTokenVerifier(
        PROJECT, fetch=Fetch({"k1": signer.public_key()}), clock=lambda: 0.0, wall=lambda: NOW
    )
    app = FastAPI()

    @app.post("/probe")
    def probe(store: Any = Depends(deps.get_store), writer: Any = Depends(deps.get_event_writer)) -> dict[str, bool]:
        return {"ephemeral": store is not durable.store and writer is not durable.store.writer}

    app.dependency_overrides[deps.get_firebase_verifier] = lambda: verifier
    return TestClient(app), signer, durable


def _bearer(signer, provider, sub):
    return {"Authorization": f"Bearer {_token(signer, provider=provider, sub=sub)}"}


def test_DEMO_EPHEMERAL_1_the_bucket_comes_only_from_the_verified_token(monkeypatch):
    client, signer, durable = _mini(monkeypatch)
    reg = fresh_registry()
    anon_a, anon_b = "anon" + "A1" * 10, "anon" + "B2" * 10
    liar = {"X-Tilo-Uid": "u_victim", "X-Tilo-Demo-Session": "false", "X-Tilo-Channel": "web", "X-Uid": "u_victim"}
    for sub in (anon_a, anon_b):
        response = client.post(
            "/probe", headers={**_bearer(signer, "anonymous", sub), **liar}, json={"user_id": "u_victim"}
        )
        assert response.json() == {"ephemeral": True}
    assert set(reg.sessions) == {user_id_for(anon_a), user_id_for(anon_b)}, "a header or a body chose a bucket"
    assert "u_victim" not in reg.sessions

    google = client.post("/probe", headers={**_bearer(signer, "google.com", "uid" + "C3" * 10), **liar})
    assert google.json() == {"ephemeral": False}, "no header turns a Google session into a demo, or a demo into one"
    assert set(reg.sessions) == {user_id_for(anon_a), user_id_for(anon_b)}


def test_DEMO_EPHEMERAL_1_a_request_whose_principal_cannot_be_resolved_is_refused_not_persisted(monkeypatch):
    client, signer, durable = _mini(monkeypatch)
    fresh_registry()
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        refused = client.post("/probe", headers=headers)
        assert refused.status_code == 401, "an unresolvable principal must be refused"

    def broken(request) -> Any:
        raise RuntimeError("boom")

    client.app.dependency_overrides[deps.get_current_principal] = broken  # type: ignore[attr-defined]
    assert client.post("/probe").status_code == 401
    assert durable.records.calls == [] and durable.events.calls == [], "the durable store was never opened"


def test_DEMO_EPHEMERAL_1_the_gates_demo_flag_alone_is_enough(monkeypatch):
    client, signer, durable = _mini(monkeypatch)
    reg = fresh_registry()
    client.app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(user_id="u_p", role="owner")

    @client.app.middleware("http")
    async def gate(request, call_next):  # what the access gate sets from the verified token
        request.state.demo_session = True
        return await call_next(request)

    assert client.post("/probe").json() == {"ephemeral": True} and set(reg.sessions) == {"u_p"}
