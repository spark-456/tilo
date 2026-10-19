"""FR-CON-02 / ADR-0035 L2 (LC-12, LC-13): the env gate that picks the outbox store, and the schedule tick's
`dispatch_due()` sweep. Fakes only: a bomb for the Firestore client, `_adr35_l2_fake.OccFirestore`, FakeGmail."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from _adr35_l2_fake import OccFirestore
from _adr35_l2_lib import WORLD_A, WORLD_B, Clock, entry, outbox_id
from fastapi import HTTPException
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors.errors import ProviderUnavailable
from tilo_connectors.fakes import FakeGmail

EMULATOR = {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8999"}
DEV = {"TILO_OUTBOX_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "demo-tilo", **EMULATOR}
DEPLOYED = {"TILO_OUTBOX_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "tilo-dev-123456", "K_SERVICE": "tilo-api"}


class Spy:
    """A client factory that records the project it was asked for and builds the fake, never a real client."""

    def __init__(self) -> None:
        self.projects: list[str] = []
        self.db = OccFirestore()

    def __call__(self, project: str) -> OccFirestore:
        self.projects.append(project)
        return self.db


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TILO_OUTBOX_STORE", "TILO_API_STORE", "TILO_FIRESTORE_PROJECT", "GOOGLE_CLOUD_PROJECT", "K_SERVICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)


@pytest.mark.parametrize("value", [None, "", "memory", "Firestore", "FIRESTORE", "yes", "1", " firestore"])
def test_FR_CON_02_ADR35_L2_gate_anything_but_exactly_firestore_is_in_memory_and_builds_no_client(value) -> None:
    from tilo_api.outbox_firestore import outbox_store_for_env

    spy, env = Spy(), {**DEV}
    env.pop("TILO_OUTBOX_STORE")
    if value is not None:
        env["TILO_OUTBOX_STORE"] = value
    assert outbox_store_for_env(env, client_factory=spy) is None
    assert spy.projects == []


def test_FR_CON_02_ADR35_L2_gate_firestore_with_a_demo_project_and_the_emulator_builds_the_store_with_no_io() -> None:
    from tilo_api.outbox_firestore import FirestoreOutboxStore, outbox_store_for_env

    spy = Spy()
    store = outbox_store_for_env(DEV, client_factory=spy)
    assert isinstance(store, FirestoreOutboxStore) and spy.projects == ["demo-tilo"]
    assert spy.db.touched == [] and spy.db.docs == {}, "building the store reads and writes nothing"


def test_FR_CON_02_ADR35_L2_gate_deployed_opens_the_named_project() -> None:
    from tilo_api.outbox_firestore import FirestoreOutboxStore, outbox_store_for_env

    spy = Spy()
    assert isinstance(outbox_store_for_env(DEPLOYED, client_factory=spy), FirestoreOutboxStore)
    assert spy.projects == ["tilo-dev-123456"]


@pytest.mark.parametrize(
    "env",
    [
        {"TILO_OUTBOX_STORE": "firestore"},
        {**DEV, "TILO_FIRESTORE_PROJECT": ""},
        {**DEV, "TILO_FIRESTORE_PROJECT": "Not A Project"},
        {**DEV, "TILO_FIRESTORE_PROJECT": "tilo-live-123456"},  # outside Cloud Run only a demo- project opens
        {"TILO_OUTBOX_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "demo-tilo"},  # no emulator host, no Cloud Run
        {**DEPLOYED, **EMULATOR},  # a deployed process never talks to an emulator host
        {**DEPLOYED, "GOOGLE_CLOUD_PROJECT": "another-project-1"},
    ],
    ids=["no-project", "empty-project", "bad-project", "live-project-on-a-laptop", "no-emulator", "emulator-deployed",
         "project-mismatch"],
)  # fmt: skip
def test_FR_CON_02_ADR35_L2_gate_firestore_asked_but_not_permitted_is_503_never_memory_and_builds_no_client(
    env,
) -> None:
    from tilo_api.outbox_firestore import outbox_store_for_env

    spy = Spy()
    with pytest.raises(HTTPException) as caught:
        outbox_store_for_env(env, client_factory=spy)
    assert caught.value.status_code == 503 and caught.value.detail == "not_configured"
    assert spy.projects == []


def test_FR_CON_02_ADR35_L2_gate_a_client_that_cannot_be_built_is_503_without_its_text(caplog) -> None:
    from tilo_api.outbox_firestore import outbox_store_for_env

    def bomb(project: str) -> Any:
        raise RuntimeError("SECRET-credentials-path-1234")

    with caplog.at_level(logging.DEBUG), pytest.raises(HTTPException) as caught:
        outbox_store_for_env(DEV, client_factory=bomb)
    assert caught.value.status_code == 503 and "SECRET" not in repr(caught.value) and caught.value.__cause__ is None
    assert "SECRET" not in caplog.text


def test_FR_CON_02_ADR35_L2_deps_unset_keeps_todays_process_wide_memory_store_and_set_picks_firestore(
    monkeypatch,
) -> None:
    from tilo_api import deps, outbox_firestore, store_door

    deps.get_outbox_store.cache_clear()
    first = deps.get_outbox_store()
    assert isinstance(first, InMemoryOutboxStore) and deps.get_outbox_store() is first

    spy = Spy()
    monkeypatch.setattr(store_door, "client_factory", spy)
    for name, value in DEV.items():
        monkeypatch.setenv(name, value)
    deps.get_outbox_store.cache_clear()
    picked = deps.get_outbox_store()
    assert isinstance(picked, outbox_firestore.FirestoreOutboxStore) and spy.projects == ["demo-tilo"]
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "")
    deps.get_outbox_store.cache_clear()
    with pytest.raises(HTTPException) as caught:
        deps.get_outbox_store()
    assert caught.value.status_code == 503
    deps.get_outbox_store.cache_clear()


# --- the tick (LC-12) -----------------------------------------------------------------------------------------------


@pytest.fixture
def sweep(clear_flow, monkeypatch):
    from _fr_agt_14_lib import SchedApi
    from tilo_api import deps
    from tilo_api.deps import WorldRecord
    from tilo_api.outbox_firestore import FirestoreOutboxStore

    rig = SchedApi(clear_flow, monkeypatch)
    clock, db, gmail = Clock(), OccFirestore(), FakeGmail()
    store = FirestoreOutboxStore(db, clock=clock)
    rig.flow.app.dependency_overrides[deps.get_outbox_store] = lambda: store
    rig.flow.app.dependency_overrides[deps.get_connector_adapters] = lambda: {"gmail": gmail}
    monkeypatch.setenv("TILO_OUTBOX_STORE", "firestore")
    for world in (WORLD_A, WORLD_B):
        rig.store.worlds[world] = WorldRecord(owner="u_owner", districts={})  # unpaused
    rig.store.worlds[WORLD_B].paused = True
    rig.clock_, rig.db, rig.gmail, rig.outbox = clock, db, gmail, store
    return rig


def test_FR_CON_02_ADR35_L2_the_tick_sends_a_dead_instances_due_entry_once(sweep) -> None:
    sweep.outbox._insert_if_absent(entry(1))
    sweep.outbox._insert_if_absent(entry(2, undo=3600))  # not due: inside its undo window
    answer = sweep.tick()
    assert answer.status_code == 200, answer.text
    assert [m["idempotency_key"] for m in sweep.gmail.sent] == [entry(1)["idempotency_key"]]
    assert sweep.outbox.get(outbox_id(1))["state"] == "sent"
    assert sweep.outbox.get(outbox_id(2))["state"] == "scheduled"
    assert sweep.tick().status_code == 200
    assert len(sweep.gmail.sent) == 1, "the next tick sends nothing again"


def test_FR_CON_02_ADR35_L2_the_tick_leaves_a_paused_worlds_entry_unsent(sweep) -> None:
    sweep.outbox._insert_if_absent(entry(1, world=WORLD_B))
    assert sweep.tick().status_code == 200
    assert sweep.gmail.sent == [] and sweep.outbox.get(outbox_id(1))["state"] == "queued"


def test_FR_CON_02_ADR35_L2_the_tick_keeps_an_ambiguous_attempt_ambiguous_and_never_marks_it_failed(sweep) -> None:
    class Down(FakeGmail):
        def send_reply(self, *args: Any, **kwargs: Any) -> dict:
            raise ProviderUnavailable("503 from the provider")

    from tilo_api import deps

    sweep.flow.app.dependency_overrides[deps.get_connector_adapters] = lambda: {"gmail": Down()}
    sweep.outbox._insert_if_absent(entry(1))
    assert sweep.tick().status_code == 200
    assert sweep.outbox.retry_state(outbox_id(1))["ambiguous"] is True
    assert sweep.outbox.get(outbox_id(1))["state"] == "sending", "never failed while it may have been sent"


def test_FR_CON_02_ADR35_L2_the_tick_sweeps_nothing_unless_the_store_is_firestore_and_a_failure_never_fails_it(
    sweep, monkeypatch
) -> None:
    sweep.outbox._insert_if_absent(entry(1))
    monkeypatch.delenv("TILO_OUTBOX_STORE")
    assert sweep.tick().status_code == 200 and sweep.gmail.sent == []

    monkeypatch.setenv("TILO_OUTBOX_STORE", "firestore")
    from tilo_api import deps

    def broken() -> Any:
        raise HTTPException(status_code=503, detail="not_configured")

    sweep.flow.app.dependency_overrides[deps.get_outbox_store] = broken
    answer = sweep.tick()
    assert answer.status_code == 200 and answer.json() == {"fired": 0}, "the sweep is best effort"


def test_FR_CON_02_ADR35_L2_the_tick_never_fails_an_entry_it_has_no_adapter_for(sweep) -> None:
    from tilo_api import deps

    sweep.outbox._insert_if_absent(entry(1))
    sweep.outbox._insert_if_absent({**entry(2), "connector": "drive"})
    sweep.flow.app.dependency_overrides[deps.get_connector_adapters] = lambda: {"gmail": sweep.gmail}
    assert sweep.tick().status_code == 200
    assert sweep.outbox.get(outbox_id(2))["state"] == "queued", "an unwired connector's entry waits, never failed"
    sweep.flow.app.dependency_overrides[deps.get_connector_adapters] = lambda: {}
    sweep.outbox._insert_if_absent(entry(3))
    assert sweep.tick().status_code == 200
    assert sweep.outbox.get(outbox_id(3))["state"] == "queued", "with no adapters nothing is claimed"
