"""PROD-WIRE slice 1b, ADR-0026 decisions 1, 3, 4 and 8: the real routes over the durable store, the deployed wiring,
and (emulator only) parity with the harness `FirestoreStore`. Interface: `_pw1b_lib.py`.

The first two tests drive intake to approve over a `DurableStore` (the module's `store` fixture replaces conftest's):
every record and event reaches the backend, a restart sees the same state, and a failed commit is 503
`store_unavailable` with nothing changed. The wiring test needs no emulator: a stand-in client that fails on any use
shows that building the store does no I/O. `client_factory` is the injection point.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from _clint1_lib import FLOW_USER
from _pw1b_lib import RUN, W1, commits_fail, part, requested, wire, world
from fastapi.testclient import TestClient
from tilo_api import app, deps, store_door
from tilo_api.durable_store import DurableStore, FirestoreBackend
from tilo_api.world_writer import PREPLAN_LAYOUT, WorldWriterAdapter
from tilo_harness.store import FirestoreStore
from tilo_harness.writer import WorldWriter


@pytest.fixture
def store(pw1b_rig) -> DurableStore:
    """Replaces conftest's plain `store`: the `flow` fixture builds the real app over this durable one."""
    return pw1b_rig.process()[0]


def _drive(flow, store) -> tuple[str, str]:
    wire(flow.app, store)  # the request's path ids are loaded first, as the deployed `get_store` does
    body = flow.client.post("/intake", data={"text": "Compare competitor pricing.", "scenario": "SC-01"}).json()
    skipped = [{"field": q["field"], "answer": None} for q in body["questions"]]
    assert flow.answers(body["task_id"], skipped).status_code == 200
    assert flow.approaches(body["task_id"]).status_code == 200
    approved = flow.approve(body["task_id"], "quick", 50)
    assert approved.status_code == 200, approved.text
    return body["task_id"], body["world_id"]


def test_PROD_WIRE_1b_intake_to_approve_leaves_a_cold_store_equal_to_the_warm_one(flow, store, pw1b_rig) -> None:
    task_id, world_id = _drive(flow, store)
    assert store.tasks[task_id].granted and store.policies, "the scenario's policies were created at approve"
    store.writer.reopen()
    cold, _ = pw1b_rig.process()
    cold.load_task(task_id)
    cold.load_world(world_id)
    cold.load_owner(FLOW_USER)
    assert cold.tasks == store.tasks and cold.worlds == store.worlds and cold.events == store.events
    assert cold.policies == store.policies and cold.policy_worlds == store.policy_worlds
    assert [e["seq"] for e in cold.events[world_id]] == list(range(1, len(cold.events[world_id]) + 1))
    assert not any(cold.pending_events.values()) and not any(store.pending_events.values())


def test_PROD_WIRE_1b_a_failed_commit_on_a_route_is_503_store_unavailable_and_changes_nothing(
    flow, store, pw1b_rig
) -> None:
    wire(flow.app, store)
    with commits_fail(pw1b_rig.backend):
        refused = flow.intake()
    assert (refused.status_code, refused.json()) == (503, {"detail": "store_unavailable"})
    assert store.worlds == {} and store.tasks == {} and store.events == {}, "no record without its events"
    body = flow.new_task()
    task_id, backend = body["task_id"], pw1b_rig.backend
    before, skipped = backend.read("tasks", task_id), [{"field": q["field"], "answer": None} for q in body["questions"]]
    with commits_fail(backend):
        refused = flow.answers(task_id, skipped)
    assert (refused.status_code, refused.json()) == (503, {"detail": "store_unavailable"})
    assert backend.read("tasks", task_id) == before
    assert flow.answers(task_id, skipped).status_code == 200, "the evicted task reloads on the next request"
    assert backend.read("tasks", task_id)["rev"] == before["rev"] + 1


class _Untouched:
    """A Firestore client that fails the test on any use: building the store must do no I/O."""

    def __getattr__(self, name: str):
        raise AssertionError(f"the client was used while building the store: {name}")


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch):
    for name in ("TILO_API_DEV", "LIVE", "FIRESTORE_EMULATOR_HOST"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "K_SERVICE": "tilo-api",
        "TILO_API_STORE": "firestore",
        "TILO_FIRESTORE_PROJECT": "tilo-dev",
    }.items():
        monkeypatch.setenv(name, value)
    client, asked = _Untouched(), []
    monkeypatch.setattr(store_door, "client_factory", lambda project: (asked.append(project), client)[1])
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    yield client, asked
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


def test_PROD_WIRE_1b_deployed_seams_return_the_durable_store_and_an_adapter_over_the_firestore_events(
    deployed,
) -> None:
    client, asked = deployed
    store, writer = deps.get_store(), deps.get_event_writer()
    assert isinstance(store, DurableStore) and isinstance(store.backend, FirestoreBackend)
    assert store.backend.client is client and isinstance(writer, WorldWriterAdapter) and store.writer is writer
    assert deps.get_store() is store and deps.get_event_writer() is writer, "a success is cached per config"
    assert asked == ["tilo-dev"], "one client for both seams"
    opened = store_door.open_api_store(firestore_client_factory=lambda project: client)
    assert (
        isinstance(opened.records, FirestoreBackend) and opened.records.client is client and opened.events is not None
    )


@pytest.mark.emulator
def test_PROD_WIRE_1b_a_deployed_route_serves_a_world_an_earlier_process_wrote(
    pw1b_emulator_host, monkeypatch: pytest.MonkeyPatch
) -> None:
    from google.cloud import firestore

    client, world_id = firestore.Client(project="demo-pw1b"), f"w_pw1b_{uuid.uuid4().hex[:12]}"
    for name, value in {
        "K_SERVICE": "tilo-api",
        "TILO_API_STORE": "firestore",
        "TILO_FIRESTORE_PROJECT": "demo-pw1b",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(store_door, "client_factory", lambda project: client)
    earlier = DurableStore(FirestoreBackend(client, org_id=deps.ORG_ID), FirestoreStore("demo-pw1b"))
    earlier.writer = WorldWriterAdapter(earlier, earlier.events_backend)
    earlier.commit(
        worlds={world_id: world()}, create=[("worlds", world_id)], parts={world_id: [requested(1, world_id)]}
    )
    earlier.drain(world_id)
    earlier.writer.reopen()
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal("u_pw1b_owner", "owner", world_id)
    try:
        response = TestClient(app).get(f"/worlds/{world_id}/events")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
    assert response.status_code == 200 and [e["id"] for e in response.json()["events"]] == [requested(1)["id"]]


@pytest.mark.emulator
def test_PROD_WIRE_1b_parity_the_api_adapter_writes_the_documents_the_harness_store_writes(pw1b_emulator_host) -> None:
    from google.cloud import firestore

    client = firestore.Client(project="demo-pw1b")
    orgs = {kind: f"org_pw1b_{uuid.uuid4().hex[:12]}" for kind in ("api", "harness")}
    clock = lambda: datetime(2026, 10, 7, 1, 0, tzinfo=UTC)  # noqa: E731
    records = deps.Store(worlds={W1: world()})
    adapter = WorldWriterAdapter(
        records, store_door.FirestoreApiStore("demo-pw1b", client).events, org_id=orgs["api"], clock=clock
    )
    harness = WorldWriter(
        FirestoreStore("demo-pw1b"), org_id=orgs["harness"], world_id=W1, run_id=RUN, layout=PREPLAN_LAYOUT,
        writer_id="tilo-api", clock=clock,
    )  # fmt: skip
    harness.open()
    keys = ("type", "actor", "target", "summary", "level", "district", "item", "severity", "cause", "authz")
    for p in (requested(1), part(2), part(3, severity="blocked")):
        adapter.append(W1, p)
        harness.emit(**{k: p[k] for k in keys}, data=p["data"], credits=p["credits"], vis=p["vis"], event_id=p["id"])

    def documents(kind: str, path: str) -> dict:
        return {d.id: d.to_dict() for d in client.collection(f"orgs/{orgs[kind]}/worlds/{W1}/{path}").stream()}

    for path in ("events", "views/shared/events"):
        assert documents("api", path) == documents("harness", path) and len(documents("api", path)) == 3
