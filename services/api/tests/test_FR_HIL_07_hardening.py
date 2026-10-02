"""FR-HIL-07 review fixes (PR #120): no cross-world starvation by hung writers, daemon attempt
threads, the paused event's actor, malformed store records never half-apply or 500, and dispatch
config validation. Complements test_FR_HIL_07_kill_switches.py (unchanged)."""

from __future__ import annotations

import threading
import time

import pytest
from _api_lib import (
    OWNER,
    WORLD,
    FakeEventWriter,
    as_part_write_deadline,
    as_principal,
    as_writer,
    base_policy,
    make_district,
    make_principal,
    make_world,
    validate_event,
)
from tilo_api import app, deps

HEALTHY_WORLD = "w_healthy"


class _HungExceptHealthy(FakeEventWriter):
    """Never answers for any world but HEALTHY_WORLD, like a hung harness for those worlds."""

    def __init__(self, store: deps.Store) -> None:
        super().__init__(store)
        self.gate = threading.Event()

    def append(self, world_id: str, event: dict) -> dict:
        if world_id != HEALTHY_WORLD:
            self.gate.wait()
        return super().append(world_id, event)


def _abandon_after(seconds: float) -> None:
    app.dependency_overrides[deps.get_attempt_abandon_after_s] = lambda: seconds


def test_FR_HIL_07_hung_writers_in_many_worlds_never_starve_a_healthy_world(client, store):
    writer = _HungExceptHealthy(store)
    as_writer(writer)
    as_part_write_deadline(0.05)
    _abandon_after(0.1)
    hung = [f"w_hung_{i}" for i in range(12)]  # more than any shared pool could serve
    for i, world_id in enumerate(hung):
        owner = f"u_hung_{i}"
        store.worlds[world_id] = make_world(owner=owner)
        store.policies[f"pol_hung_{i}"] = base_policy(id_=f"pol_hung_{i}", owner=owner, level="L2")
        store.policy_worlds[f"pol_hung_{i}"] = world_id
    store.worlds[HEALTHY_WORLD] = make_world(owner=OWNER)
    store.policies["pol_ok"] = base_policy(id_="pol_ok", owner=OWNER, level="L2")
    store.policy_worlds["pol_ok"] = HEALTHY_WORLD
    try:
        for _ in range(3):  # enough calls to hit each hung world's abandon cap
            for i, world_id in enumerate(hung):
                as_principal(make_principal(user_id=f"u_hung_{i}", world_id=world_id))
                assert client.post(f"/worlds/{world_id}/autopilot/stop").status_code in (200, 202)
            time.sleep(0.12)

        as_principal(make_principal(user_id=OWNER, world_id=HEALTHY_WORLD))
        started = time.monotonic()
        resp = client.post(f"/worlds/{HEALTHY_WORLD}/pause")
        elapsed = time.monotonic() - started
        assert resp.status_code == 200, resp.text
        assert resp.json()["pending"] == 0
        assert elapsed < 2.0, f"healthy world's Pause all took {elapsed:.2f}s behind other worlds' hung writers"
        assert [e["type"] for e in store.events[HEALTHY_WORLD]].count("world.paused") == 1
    finally:
        writer.gate.set()


def test_FR_HIL_07_attempt_threads_are_daemon_so_a_hung_writer_cannot_block_exit(client, store):
    writer = _HungExceptHealthy(store)
    as_writer(writer)
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_a"] = base_policy(id_="pol_a", owner=OWNER, level="L2")
    store.policy_worlds["pol_a"] = WORLD
    as_principal(make_principal(user_id=OWNER, world_id=WORLD))
    before = {t for t in threading.enumerate()}
    try:
        assert client.post(f"/worlds/{WORLD}/autopilot/stop").status_code == 202
        started = [t for t in threading.enumerate() if t not in before and t.is_alive()]
        assert started, "expected the hung attempt's thread to still be running"
        assert all(t.daemon for t in started), "an attempt thread is joined at interpreter exit"
    finally:
        writer.gate.set()


def test_FR_HIL_07_pause_all_world_paused_actor_is_the_principals_user_id(client, store, writer):
    store.worlds[WORLD] = make_world(owner=OWNER)
    as_principal(make_principal(user_id=OWNER, world_id=WORLD, channel="whatsapp"))
    assert client.post(f"/worlds/{WORLD}/pause").status_code == 200
    paused = [e for e in store.events[WORLD] if e["type"] == "world.paused"]
    assert len(paused) == 1
    assert paused[0]["actor"] == OWNER
    validate_event(paused[0])


def test_FR_HIL_07_pause_all_lowers_policies_before_it_waits_on_the_writer(client, store):
    class Slow(FakeEventWriter):
        def append(self, world_id: str, event: dict) -> dict:
            time.sleep(0.3)
            return super().append(world_id, event)

    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_a"] = base_policy(id_="pol_a", owner=OWNER, level="L3")
    store.policy_worlds["pol_a"] = WORLD
    seen: list[str] = []

    class Spy(Slow):
        def append(self, world_id: str, event: dict) -> dict:
            seen.append(store.policies["pol_a"]["level"])  # level at the first write attempt
            return super().append(world_id, event)

    as_writer(Spy(store))
    as_principal(make_principal(user_id=OWNER, world_id=WORLD))
    assert client.post(f"/worlds/{WORLD}/pause").status_code == 200
    assert seen and seen[0] == "L1", "levels must already be L1 when the first write is attempted"


def _two_owned_policies(store, *, bad_id: str):
    store.worlds[WORLD] = make_world(owner=OWNER, districts={"d1": make_district("D1", "s")})
    for pid in (bad_id, "pol_good_1", "pol_good_2"):
        store.policies[pid] = base_policy(id_=pid, owner=OWNER, level="L3")
        store.policy_worlds[pid] = WORLD


def _assert_all_lowered_with_event(store, ids):
    for pid in ids:
        assert store.policies[pid]["level"] == "L1", pid
    landed = {e["data"]["policy_id"] for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"}
    assert landed == set(ids)
    assert not store.pending_events.get(WORLD)


@pytest.mark.parametrize("bad_mapping", [None, 7, ["w_x"], {"w": 1}, ""])
@pytest.mark.parametrize("route", ["stop", "pause"])
def test_FR_HIL_07_non_string_policy_world_mapping_falls_back_to_the_request_world(
    client, store, writer, bad_mapping, route
):
    _two_owned_policies(store, bad_id="pol_bad")
    store.policy_worlds["pol_bad"] = bad_mapping  # type: ignore[assignment]
    as_principal(make_principal(user_id=OWNER, world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop" if route == "stop" else f"/worlds/{WORLD}/pause")
    assert resp.status_code == 200, resp.text
    _assert_all_lowered_with_event(store, ["pol_bad", "pol_good_1", "pol_good_2"])


@pytest.mark.parametrize("bad_world", [None, 7, "not a record", {"districts": {}}])
@pytest.mark.parametrize("route", ["stop", "pause"])
def test_FR_HIL_07_non_world_record_target_is_treated_as_no_layout(client, store, writer, bad_world, route):
    _two_owned_policies(store, bad_id="pol_bad")
    store.worlds["w_corrupt"] = bad_world  # type: ignore[assignment]
    store.policy_worlds["pol_bad"] = "w_corrupt"
    as_principal(make_principal(user_id=OWNER, world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop" if route == "stop" else f"/worlds/{WORLD}/pause")
    assert resp.status_code in (200, 202), resp.text
    for pid in ("pol_bad", "pol_good_1", "pol_good_2"):
        assert store.policies[pid]["level"] == "L1", pid
    # pol_bad's stream is the corrupt world's: its part is committed or still pending, never lost.
    kept = {
        e["data"]["policy_id"]
        for w in (*store.events.values(), *store.pending_events.values())
        for e in w
        if e["type"] == "policy.changed"
    }
    assert kept == {"pol_bad", "pol_good_1", "pol_good_2"}
    landed = {e["data"]["policy_id"] for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"}
    assert landed == {"pol_good_1", "pol_good_2"}


def test_FR_HIL_07_revoke_with_a_malformed_mapping_still_lowers_and_emits(client, store, writer):
    _two_owned_policies(store, bad_id="pol_bad")
    store.policy_worlds["pol_bad"] = 7  # type: ignore[assignment]
    as_principal(make_principal(user_id=OWNER, world_id=WORLD))
    assert client.post("/policies/pol_bad/revoke").status_code == 200
    assert store.policies["pol_bad"]["level"] == "L1"
    assert [e["data"]["policy_id"] for e in store.events[WORLD]] == ["pol_bad"]


def test_FR_HIL_07_revoke_without_a_mapping_is_routed_to_the_principals_world(client, store, writer):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_unmapped"] = base_policy(id_="pol_unmapped", owner=OWNER, level="L2")
    as_principal(make_principal(user_id=OWNER, world_id=WORLD))
    assert client.post("/policies/pol_unmapped/revoke").status_code == 200
    changed = [e for e in store.events[WORLD] if e["type"] == "policy.changed"]
    assert [e["data"]["change"] for e in changed] == ["revoked"]


class _FailsWith(FakeEventWriter):
    def __init__(self, store: deps.Store, exc: Exception) -> None:
        super().__init__(store)
        self.exc = exc
        self.reopened = 0

    def append(self, world_id: str, event: dict) -> dict:
        if not self.reopened:
            raise self.exc
        return super().append(world_id, event)

    def reopen(self) -> None:
        self.reopened += 1


class WriterBusy(Exception):  # matched by class name: tilo-api cannot import the harness
    pass


def _one_policy(store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_a"] = base_policy(id_="pol_a", owner=OWNER, level="L2")
    store.policy_worlds["pol_a"] = WORLD
    as_principal(make_principal(user_id=OWNER, world_id=WORLD))


def test_FR_HIL_07_reopen_only_on_writer_busy(client, store):
    _one_policy(store)
    busy = _FailsWith(store, WriterBusy("head has moved"))
    as_writer(busy)
    assert client.post(f"/worlds/{WORLD}/autopilot/stop").status_code == 200
    assert busy.reopened == 1


def test_FR_HIL_07_no_reopen_after_an_event_rejected_conflict(client, store):
    _one_policy(store)
    rejected = _FailsWith(store, deps.EventRejected("same id, different content"))
    as_writer(rejected)
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp.status_code == 202
    assert rejected.reopened == 0


@pytest.mark.parametrize("bad", ["0", "-1", "nan", "inf", "'soon'", "null"])
def test_FR_HIL_07_dispatch_config_must_be_positive_and_finite(tmp_path, monkeypatch, caplog, bad):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "dispatch.yaml").write_text(
        f"dispatch:\n  part_write_deadline_s: {bad}\n  attempt_abandon_after_s: {bad}\n", encoding="utf-8"
    )
    monkeypatch.setattr(deps, "_REPO_ROOT", tmp_path)
    with caplog.at_level("WARNING"):
        assert deps.get_part_write_deadline_s() == deps._DEFAULT_PART_WRITE_DEADLINE_S
        assert deps.get_attempt_abandon_after_s() == deps._DEFAULT_ABANDON_AFTER_S
    assert "using default" in caplog.text
