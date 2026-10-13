"""DEMO-EPHEMERAL-1: slots are taken only by a first write, an empty idle session may be evicted (never one with data),
a demo's concurrent runs are capped, the byte and item caps fire through every seam, and a demo's people stores are
the in-memory ones (the Firestore opener is never reached)."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
from _demo_eph_lib import fresh_registry
from fastapi import HTTPException
from fastapi.testclient import TestClient
from tilo_api import app, deps, ephemeral, people_firestore


class FakeClock:
    def __init__(self) -> None:
        self.t = 5.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture(autouse=True)
def _reset():
    yield
    ephemeral.configure()
    app.dependency_overrides.clear()
    deps.get_people_stores.cache_clear()


def _full(e: HTTPException) -> tuple[int, str]:
    return e.status_code, e.detail


def test_DEMO_EPHEMERAL_1_a_read_holds_no_slot_and_creates_no_session():
    reg = fresh_registry(max_sessions=1)
    readers = [reg.session(f"u_{n}") for n in range(5)]  # reads: nobody stored anything
    assert reg.sessions == {} and reg.total_items == 0
    readers[3].charge(1)  # the first write takes the slot
    assert set(reg.sessions) == {"u_3"}


def test_DEMO_EPHEMERAL_1_an_empty_idle_session_is_evicted_for_a_new_one_but_never_one_with_data():
    clock = FakeClock()
    reg = fresh_registry(clock=clock, max_sessions=2, ttl_s=10_000.0)
    empty, full = reg.session("u_a"), reg.session("u_b")
    empty.charge(1)
    empty.refund(1, 0)  # registered, holds nothing
    full.charge(1)
    clock.t += 30
    with pytest.raises(HTTPException):  # the empty one is not yet idle past 60 s
        reg.session("u_c").charge(1)
    clock.t += 40
    reg.session("u_b")  # the one with data is touched
    reg.session("u_c").charge(1)
    assert set(reg.sessions) == {"u_b", "u_c"} and empty.dead
    clock.t += 1000
    with pytest.raises(HTTPException) as refused:  # both hold data: nothing may be evicted
        reg.session("u_d").charge(1)
    assert _full(refused.value) == (503, "demo_capacity") and set(reg.sessions) == {"u_b", "u_c"}


def test_DEMO_EPHEMERAL_1_a_demo_may_have_only_a_few_runs_at_once():
    session = fresh_registry().session("u_a")
    session.charge(1)
    runs = [SimpleNamespace(_ended=threading.Event()) for _ in range(ephemeral.MAX_RUNS)]
    session.store.runs.update({f"w_{n}": r for n, r in enumerate(runs)})
    with pytest.raises(HTTPException) as refused:
        session.store.admit_run()
    assert _full(refused.value) == (429, "demo_runs_busy")
    runs[0]._ended.set()
    session.store.admit_run()


def test_DEMO_EPHEMERAL_1_the_seams_charge_bytes_so_the_byte_cap_fires_through_them():
    from tilo_memory.artifacts import NewVersion, Origin, Scope

    reg = fresh_registry(max_bytes=200)
    session = reg.session("u_a")
    with pytest.raises(HTTPException) as refused:  # an artifact blob
        session.artifacts.put(
            Scope(org_id="org_tilo", world_id="w_x", owner="u_a"),
            NewVersion(media_type="text/markdown", content=b"x" * 500, run_id="r_x", origin=Origin(kind="upload")),
        )
    assert _full(refused.value) == (429, "demo_capacity")
    with pytest.raises(HTTPException):  # an upload
        session.uploads.put(
            artifact_id=None, filename="a.txt", content=b"x" * 500, content_type=None, task_id="t_x", received_at="x"
        )
    archive = session.open_archive(org_id="org_tilo", run_id="r_x")
    with pytest.raises(HTTPException):  # a raw-archive line, counted in bytes (not characters)
        archive.append("tool_call", {"text": "é" * 120})
    assert session.nbytes <= 200 and reg.total_bytes == session.nbytes, "refused writes give their charge back"


def test_DEMO_EPHEMERAL_1_the_item_cap_fires_through_the_people_store():
    session = fresh_registry(max_items=0).session("u_a")
    with pytest.raises(HTTPException) as refused:
        session.people  # the demo's own person record is the first item
    assert _full(refused.value) == (429, "demo_capacity")


def _demo_client(user: str) -> TestClient:
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=user, role="owner", demo_session=True
    )
    return TestClient(app, raise_server_exceptions=False)


BODY = {
    "display_name": "Sam", "aliases": [], "email": "sam@example.com", "time_zone": "Asia/Kolkata",
    "preferred_channel": "web",
}  # fmt: skip


def test_DEMO_EPHEMERAL_1_a_demo_uses_in_memory_people_stores_and_never_opens_firestore(monkeypatch):
    fresh_registry()
    opened: list[int] = []

    def forbidden(*a: Any, **k: Any) -> Any:
        opened.append(1)
        raise RuntimeError("a demo opened the Firestore people stores")

    monkeypatch.setattr(people_firestore, "open_people_stores", forbidden)
    deps.get_people_stores.cache_clear()
    client = _demo_client("u_demo_p")
    made = client.post("/v1/people", json=BODY)
    assert made.status_code == 201, made.text
    assert client.post("/v1/people", json=BODY).status_code == 409  # the real person store's address reservation
    listed = client.get("/v1/work-items")
    assert listed.status_code == 200, listed.text
    assert opened == []


def test_DEMO_EPHEMERAL_1_the_people_item_cap_answers_demo_capacity_on_the_route():
    fresh_registry(max_items=2)  # the demo's own person, then one more
    client = _demo_client("u_demo_q")
    assert client.post("/v1/people", json=BODY).status_code == 201
    refused = client.post("/v1/people", json={**BODY, "email": "b@example.com"})
    assert refused.status_code == 429 and "demo_capacity" in refused.text
