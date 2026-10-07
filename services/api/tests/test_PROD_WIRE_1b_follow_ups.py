"""PROD-WIRE slice 1b, the slice 1a review items finished here (ADR-0026 decision 4): the adapter's per-world lock table
is bounded, a shutdown (SIGTERM) closes the deployed writers and is harmless where none is open, and a `WriterBusy` that
reaches a route after the one retry is 503 `store_unavailable`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _pw1b_lib import part
from fastapi.testclient import TestClient
from tilo_api import app, deps, durable_store
from tilo_api.world_writer import WorldWriterAdapter
from tilo_harness.store import MemoryStore
from tilo_harness.writer import WriterBusy


def test_PROD_WIRE_1b_the_adapter_lock_table_is_bounded_however_many_worlds_it_sees() -> None:
    store = deps.Store(worlds={f"w_pw1b_{n}": deps.WorldRecord(owner="u_pw1b_owner", districts={}) for n in range(20)})
    adapter = WorldWriterAdapter(store, MemoryStore())
    size = len(adapter._locks)
    for world_id in store.worlds:
        adapter.append(world_id, part(1))
        adapter.reopen()
    assert len(adapter._locks) == size == 256, "a fixed table: it never grows with the worlds seen"


def test_PROD_WIRE_1b_a_shutdown_closes_every_deployed_writer_and_is_harmless_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[str] = []
    monkeypatch.setattr(durable_store, "_opened", {})
    with TestClient(app):  # nothing deployed: the shutdown hook finds no writer
        pass
    monkeypatch.setattr(durable_store, "_opened", {("a",): (None, SimpleNamespace(reopen=lambda: closed.append("a")))})
    with TestClient(app):
        assert closed == []
    assert closed == ["a"], "the lifespan's shutdown released the writer's leases"


def test_PROD_WIRE_1b_a_writer_busy_that_reaches_a_route_is_503_store_unavailable() -> None:
    handler = app.exception_handlers[WriterBusy]
    response = handler(SimpleNamespace(), WriterBusy("world busy"))
    assert response.status_code == 503 and response.body == b'{"detail":"store_unavailable"}'


def test_PROD_WIRE_1b_an_in_place_commit_after_an_ambiguous_one_reads_the_rev_again_and_an_evicted_world_reloads(
    pw1b_rig,
) -> None:
    from _pw1b_lib import OWNER, W1, commits_fail, seed, world
    from fastapi import HTTPException

    store, _ = pw1b_rig.process()
    seed(store, worlds={W1: world()})
    store.load_owner(OWNER)
    record = store.worlds[W1]
    record.paused = True  # a kill switch's change, applied here first
    with commits_fail(pw1b_rig.backend, applied=True), pytest.raises(HTTPException):
        store.commit(worlds={W1: record}, evict=False)
    assert store.worlds[W1] is record, "an in-place change stays applied here"
    store.commit(worlds={W1: record}, evict=False)  # the rev the failed commit made unknown is read, not refused
    assert pw1b_rig.backend.read("worlds", W1)["rev"] == 3
    with commits_fail(pw1b_rig.backend), pytest.raises(HTTPException):
        store.commit(worlds={W1: world()})
    assert W1 not in store.worlds
    store.load_owner(OWNER)  # the eviction made the next `load_owner` look again
    assert store.worlds[W1].paused is True
