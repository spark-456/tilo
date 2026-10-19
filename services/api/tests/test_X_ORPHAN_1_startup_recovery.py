"""X-ORPHAN-1 / HR-1: restart recovery runs before the API accepts requests."""

import asyncio
from types import SimpleNamespace

import pytest
from _pw1b_lib import RUN, W1, part, requested, seed, started, world
from fastapi import HTTPException
from tilo_api import durable_store, events

REASON = "Tilo restarted during this run; start it again"


def interrupted(rig, *, release=True):
    warm, writer = rig.process()
    seed(warm, worlds={W1: world()}, parts={W1: [requested(1), started(2)]})
    warm.drain(W1)
    if release:
        writer.reopen()
    return writer


def test_X_ORPHAN_1_startup_records_registered_failure_before_serving(monkeypatch, pw1b_rig):
    import tilo_api

    interrupted(pw1b_rig)
    cold, writer = pw1b_rig.process()
    monkeypatch.setenv("TILO_API_STORE", "firestore")
    monkeypatch.setattr(durable_store, "deployed", lambda: (cold, writer))
    monkeypatch.setattr(durable_store, "close_deployed", writer.reopen)
    monkeypatch.setattr(tilo_api._appcheck, "warm_up", lambda: None)

    async def start():
        async with tilo_api._lifespan(tilo_api.app):
            failures = [e for e in pw1b_rig.stream(W1) if e["type"] == "world.failed"]
            assert len(failures) == 1
            assert failures[0]["data"] == {"reason": REASON, "unit": None}
            assert failures[0]["id"] == events.world_failed_part(W1, REASON, RUN)["id"]

    asyncio.run(start())


def test_X_ORPHAN_1_startup_is_idempotent_across_processes(pw1b_rig):
    interrupted(pw1b_rig)
    for _ in range(2):
        cold, writer = pw1b_rig.process()
        cold.recover_started_worlds()
        cold.recover_started_worlds()
        writer.reopen()
    assert [e["type"] for e in pw1b_rig.stream(W1)] == ["world.requested", "world.started", "world.failed"]


@pytest.mark.parametrize("state", ["unstarted", "failed", "completed", "paused", "live"])
def test_X_ORPHAN_1_startup_preserves_non_orphan_worlds(pw1b_rig, state):
    warm, writer = pw1b_rig.process()
    parts = [requested(1)]
    if state != "unstarted":
        parts.append(started(2))
    if state == "failed":
        parts.append(events.world_failed_part(W1, "Already stopped", RUN))
    if state == "completed":
        parts.append(part(3, type="world.completed", target=W1, data={"credits_used": 0, "deliverable_count": 0}))
    seed(warm, worlds={W1: world(paused=state == "paused")}, parts={W1: parts})
    warm.drain(W1)
    writer.reopen()
    before = pw1b_rig.stream(W1)
    cold, writer = pw1b_rig.process()
    if state == "live":
        cold.runs[W1] = SimpleNamespace()
    cold.recover_started_worlds()
    assert pw1b_rig.stream(W1) == before
    writer.reopen()


def test_X_ORPHAN_1_startup_respects_another_writers_live_lease(pw1b_rig):
    warm_writer = interrupted(pw1b_rig, release=False)
    cold, writer = pw1b_rig.process()
    before = pw1b_rig.stream(W1)
    cold.recover_started_worlds()
    assert pw1b_rig.stream(W1) == before
    warm_writer.reopen()
    cold.recover_started_worlds()
    assert pw1b_rig.stream(W1)[-1]["type"] == "world.failed"
    writer.reopen()


def test_X_ORPHAN_1_unconfigured_startup_opens_no_store(monkeypatch):
    monkeypatch.delenv("TILO_API_STORE", raising=False)

    def refuse():
        pytest.fail("An unconfigured startup must not open a store")

    monkeypatch.setattr(durable_store, "deployed", refuse)
    durable_store.recover_deployed()


def test_X_ORPHAN_1_store_outage_does_not_prevent_startup(monkeypatch):
    monkeypatch.setenv("TILO_API_STORE", "firestore")

    def unavailable():
        raise HTTPException(503, "store_unavailable")

    monkeypatch.setattr(durable_store, "deployed", unavailable)
    durable_store.recover_deployed()
