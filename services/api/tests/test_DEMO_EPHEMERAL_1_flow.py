"""DEMO-EPHEMERAL-1 (BQ-DEMO-EPH-1): an anonymous demo session stores nothing server-side.

The whole flow (intake, answers, approve, the run to its gate, the owner's approval) runs on the app's own default
storage seams, with recording fakes where the durable ones would be. A demo leaves them untouched; a Google (full)
session writes to them as before; a demo's data is gone after the idle TTL or an explicit drop; one demo cannot see
another's, nor a Google user's; nothing of a demo is logged."""

from __future__ import annotations

import logging
import time

import pytest
from _clint2_lib import FLOW_USER, OTHER_USER, build_run_flow, covering_policy, settle, wait_for
from _demo_eph_lib import Durable, SpyOutbox, as_session, fresh_registry, install_run_seams
from tilo_api import deps, ephemeral

MARKER = "zq-marker-" + "7f3a"  # a distinctive string in the task text, to look for in the logs


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def registry():
    reg = fresh_registry()
    yield reg
    ephemeral.configure()


@pytest.fixture()
def durable(monkeypatch):
    return Durable(monkeypatch)


@pytest.fixture()
def outbox():
    return SpyOutbox()


def _rig(repo_root, monkeypatch, outbox, google=False):
    rf = build_run_flow(repo_root, covered=False)
    install_run_seams(rf, monkeypatch, outbox, google=google)
    return rf


@pytest.fixture()
def demo_rig(repo_root, monkeypatch, registry, durable, outbox):
    rf = _rig(repo_root, monkeypatch, outbox)
    session = registry.session(FLOW_USER)
    session.store.policies["pol_send_ask"] = covering_policy()  # the owner's own L1 policy, in the demo's own store
    as_session(rf, session.store, demo_session=True)
    yield rf
    rf.close()
    rf.app.dependency_overrides.clear()


@pytest.fixture()
def google_rig(repo_root, monkeypatch, registry, durable, outbox):
    rf = _rig(repo_root, monkeypatch, outbox, google=True)
    durable.store.commit(policies={"pol_send_ask": covering_policy()}, create=[("policies", "pol_send_ask")])
    as_session(rf, durable.store, full_session=True)
    durable.records.calls.clear()
    durable.events.calls.clear()
    yield rf
    rf.close()
    rf.app.dependency_overrides.clear()


def test_DEMO_EPHEMERAL_1_a_demo_intake_approve_and_run_writes_nothing_durable(demo_rig, durable, outbox, registry):
    rf = demo_rig
    _, card = rf.run_to_gate()
    assert rf.answer(card["id"], "approve").status_code == 200
    settle(lambda: len(rf.events()), quiet_s=0.5)

    assert durable.writes() == [], "a demo wrote to the durable records or events store"
    assert durable.records.inner.docs == {} and durable.records.inner.queues == {}
    assert outbox.inserts == 0, "a demo reached the process-wide outbox"
    assert rf.adapter.sent == [], "a demo run sent something through a connector"
    assert rf.rig.meta._docs == {} and rf.rig.opened == [], "a demo reached the shared artifact store or raw archive"
    session = registry.sessions[FLOW_USER]
    assert "artifacts" in session._made and "archive" in session._made, "the demo's own seams ran"
    assert rf.world_id in session.store.worlds and session.store.events[rf.world_id], "the demo's data is its own"
    assert session.items > 0


def test_DEMO_EPHEMERAL_1_a_google_session_still_writes_as_before(google_rig, durable, outbox, registry):
    rf = google_rig
    _, card = rf.run_to_gate()
    assert rf.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: rf.events("world.completed"), what="world.completed")

    assert "commit" in durable.records.calls and "transact" in durable.events.calls
    assert durable.records.inner.docs, "the Google session's records were not stored"
    assert outbox.inserts >= 1 and rf.adapter.sent, "the Google session's send did not go through its outbox"
    assert rf.rig.meta._docs and rf.rig.opened, "the Google session's outputs did not reach its artifact store"
    assert registry.sessions == {}, "a Google session never gets an ephemeral bundle"


def test_DEMO_EPHEMERAL_1_a_demos_data_is_gone_after_the_idle_ttl(repo_root, monkeypatch, durable, outbox):
    clock = FakeClock()
    registry = fresh_registry(clock=clock, ttl_s=60.0)
    rf = _rig(repo_root, monkeypatch, outbox)
    as_session(rf, registry.session(FLOW_USER).store, demo_session=True)
    rf.start()
    task = rf.task_id
    clock.t += 59
    assert rf.flow.client.get(f"/tasks/{task}/approaches").status_code == 200  # a request keeps it alive
    clock.t += 59
    assert rf.flow.client.get(f"/tasks/{task}/approaches").status_code == 200
    assert registry.total_items > 0
    clock.t += 61  # idle past the TTL
    assert rf.flow.client.get(f"/tasks/{task}/approaches").status_code == 404
    assert FLOW_USER not in registry.sessions, "a read after expiry creates nothing"
    assert durable.writes() == []
    rf.close()
    rf.app.dependency_overrides.clear()


def test_DEMO_EPHEMERAL_1_a_demos_data_is_gone_after_an_explicit_drop(demo_rig, registry, durable):
    rf = demo_rig
    rf.start()
    old = registry.sessions[FLOW_USER]
    assert rf.flow.client.get(f"/tasks/{rf.task_id}/approaches").status_code == 200
    registry.drop(FLOW_USER)
    assert old.store.tasks == {} and old.store.worlds == {} and old.dead
    assert registry.total_items == 0 and registry.sessions == {}
    assert rf.flow.client.get(f"/tasks/{rf.task_id}/approaches").status_code == 404
    assert durable.writes() == []


def test_DEMO_EPHEMERAL_1_one_demo_cannot_read_another_demos_data_nor_a_google_users(demo_rig, durable, registry):
    rf = demo_rig
    rf.start()
    mine = (rf.task_id, rf.world_id)

    # a Google user's world, in the durable store
    from _pw1b_lib import W2, seed, task, world

    google = "u_google_person"
    seed(durable.store, worlds={W2: world(owner=google)}, tasks={"t_" + "0" * 25 + "1": task(W2, owner=google)})
    durable.records.calls.clear()

    rf.as_member(user_id=OTHER_USER)  # another anonymous demo session
    client = rf.flow.client
    assert client.get(f"/tasks/{mine[0]}/approaches").status_code == 404
    assert client.get(f"/worlds/{mine[1]}/cards").status_code in (403, 404)  # no cards, whichever refusal
    assert [w["id"] for w in client.get("/worlds").json().get("worlds", [])] == []
    assert client.get("/cards").json().get("items", []) == []
    assert client.get(f"/worlds/{W2}/cards").status_code in (403, 404)  # nor the Google user's world
    assert OTHER_USER not in registry.sessions, "reads on a session that does not exist create no slot"

    rf.as_member(user_id=FLOW_USER)  # the owner again still sees its own
    assert client.get(f"/tasks/{mine[0]}/approaches").status_code == 200
    assert durable.writes() == []


def test_DEMO_EPHEMERAL_1_a_google_user_cannot_read_a_demos_data(demo_rig, durable, registry):
    rf = demo_rig
    rf.start()
    task_id, world_id = rf.task_id, rf.world_id
    rf.flow.principal = deps.Principal(user_id=FLOW_USER, role="owner", world_id=world_id, full_session=True)
    assert rf.flow.client.get(f"/tasks/{task_id}/approaches").status_code == 404, "the durable store has no demo data"
    assert durable.writes() == []


def test_DEMO_EPHEMERAL_1_nothing_of_a_demo_is_logged(demo_rig, caplog):
    rf = demo_rig
    caplog.set_level(logging.DEBUG)
    response = rf.flow.intake(text=f"Prepare the weekly supplier summary. {MARKER}")
    assert response.status_code == 201
    rf.task_id, rf.world_id = response.json()["task_id"], ""
    rf.flow.approaches(rf.task_id)
    time.sleep(0.1)
    text = caplog.text
    assert MARKER not in text and FLOW_USER not in text, "a demo's text or uid reached the logs"


def test_DEMO_EPHEMERAL_1_a_full_demo_session_answers_demo_capacity_and_spills_nowhere(
    repo_root, monkeypatch, durable, outbox
):
    registry = fresh_registry(max_items=2)
    rf = _rig(repo_root, monkeypatch, outbox)
    as_session(rf, registry.session(FLOW_USER).store, demo_session=True)
    refused = rf.flow.intake()
    assert refused.status_code == 429 and refused.json()["detail"] == "demo_capacity"
    assert registry.sessions[FLOW_USER].items <= 2
    assert durable.writes() == [] and registry.sessions[FLOW_USER].store.tasks == {}
    rf.close()
    rf.app.dependency_overrides.clear()


def test_DEMO_EPHEMERAL_1_a_demos_upload_lands_in_its_own_store_not_the_shared_one(demo_rig, registry):
    from tilo_api import intake

    before = dict(intake._store._versions)
    response = demo_rig.flow.intake(files=[("notes.csv", b"a,b" + bytes([10]) + b"1,2" + bytes([10]))])
    assert response.status_code == 201, response.text
    assert intake._store._versions == before, "a demo's upload reached the process-wide store"
    assert registry.sessions[FLOW_USER].uploads._versions, "the upload is in the demo's own store"


def test_DEMO_EPHEMERAL_1_the_byte_cap_fires_through_the_upload_route(repo_root, monkeypatch, durable, outbox):
    registry = fresh_registry(max_bytes=100)
    rf = _rig(repo_root, monkeypatch, outbox)
    as_session(rf, registry.session(FLOW_USER).store, demo_session=True)
    refused = rf.flow.intake(files=[("big.csv", b"a,b" + bytes([10]) + b"1,2" + bytes([10]) * 1 + b"x" * 500)])
    assert refused.status_code == 429 and refused.json()["detail"] == "demo_capacity"
    assert durable.writes() == []
    rf.close()
    rf.app.dependency_overrides.clear()


def test_DEMO_EPHEMERAL_1_approve_is_refused_while_a_demo_has_its_runs_going(demo_rig, registry):
    import threading
    from types import SimpleNamespace

    rf = demo_rig
    rf.start()
    store = registry.sessions[FLOW_USER].store
    for n in range(ephemeral.MAX_RUNS):
        store.runs[f"w_busy{n}"] = SimpleNamespace(_ended=threading.Event())
    refused = rf.approve()
    assert refused.status_code == 429 and refused.json()["detail"] == "demo_runs_busy"
    assert not any(t.granted for t in store.tasks.values()), "nothing was granted"
