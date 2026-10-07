"""NFR-07 (PRD 17.1): "Pause all or `STOP AUTOPILOT` -> effective | <= 2 s and <= 5 s".

Reading of the two numbers (the table gives no column for them, so this is the PRD's own pairing, in the
order the row names the two actions, and it matches the FR rows that own each number):
  * Pause all           <= 2 s  -- FR-WLD-07 "Pause all stops every agent in <= 2 s" (PRD 8, row FR-WLD-07).
  * `STOP AUTOPILOT`    <= 5 s  -- FR-HIL-07 "sets all policies to L1 in <= 5 s" (PRD 10.6) and FR-CHN-06.
Default taken where the PRD is silent: "effective" means the state a later check sees, i.e. every policy
of the owner at L1 and, for Pause all, the world flagged paused with `world.paused` first in line for the
event writer (PRD 10.4, PI-13, PI-18). WhatsApp is out of scope here (SD-01, ADR-0019): the app route is
the only path that exists in tilo-api, and it is the one measured.

FR-HIL-07's own tests assert the same numbers on the response. These add what they do not: the effective
state observed from outside while the request is still in flight (so it cannot be waiting on writer I/O),
the bounds the code enforces (config and call budget) against the PRD numbers, and a property over
policy count, writer latency and backlog. Time is the real in-process clock; nothing sleeps for a bound.
"""

from __future__ import annotations

import threading
import time

from _api_lib import (
    OWNER,
    WORLD,
    BlockingEventWriter,
    SlowEventWriter,
    as_principal,
    as_writer,
    base_policy,
    make_pending_part,
    make_principal,
    make_world,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import deps, dispatch

PAUSE_BOUND_S = 2.0  # NFR-07, first number (FR-WLD-07)
STOP_BOUND_S = 5.0  # NFR-07, second number (FR-HIL-07)


def _policies(store, n: int, *, level: str = "L3") -> list[str]:
    store.worlds[WORLD] = make_world(owner=OWNER)
    ids = []
    for i in range(n):
        pid = f"pol_nfr07_{i}"
        store.policies[pid] = base_policy(id_=pid, owner=OWNER, level=level, action_type="send_email")
        store.policy_worlds[pid] = WORLD
        ids.append(pid)
    return ids


def _all_l1(store, ids: list[str]) -> bool:
    return all(store.policies[p]["level"] == "L1" and store.policies[p]["history"][-1]["level"] == "L1" for p in ids)


def _seconds_until(predicate, *, within_s: float, started: float) -> float | None:
    """Seconds since `started` when `predicate` first held, polling every 5 ms; None if it never did."""
    while time.monotonic() - started <= within_s:
        if predicate():
            return time.monotonic() - started
        time.sleep(0.005)
    return None


def _post_in_thread(client, path: str, result: dict, **kwargs) -> threading.Thread:
    def call() -> None:
        started = time.monotonic()
        result["resp"] = client.post(path, **kwargs)
        result["elapsed"] = time.monotonic() - started

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    return thread


def test_NFR_07_enforced_bounds_are_inside_the_prd_numbers():
    """The deadlines the kill-switch code enforces (config/dispatch.yaml and the call budget) are inside
    the PRD numbers: a single writer attempt on the pause path is bounded by 2 s, a whole call by 5 s."""
    part_deadline = deps.get_part_write_deadline_s()  # real config, no override in this test
    abandon_after = deps.get_attempt_abandon_after_s()

    assert 0 < part_deadline <= PAUSE_BOUND_S, f"a writer attempt may wait {part_deadline} s, Pause all needs <= 2 s"
    assert 0 < abandon_after < STOP_BOUND_S, f"a lost attempt is resent after {abandon_after} s, over the 5 s bound"
    assert 0 < dispatch._CALL_BUDGET_S <= STOP_BOUND_S, f"a call's write budget is {dispatch._CALL_BUDGET_S} s"
    assert deps._MAX_DISPATCH_S < STOP_BOUND_S, "config may not set a per-attempt wait that outlasts the 5 s bound"


def test_NFR_07_pause_all_is_effective_within_2s_while_the_writer_never_returns(client, store):
    """Pause all against a writer whose append never returns: from outside, every policy is L1 and the
    world is paused within 2 s of the call, with `world.paused` still waiting at the writer. So the 2 s
    does not depend on event I/O."""
    ids = _policies(store, 50, level="L3")
    blocking = BlockingEventWriter(store)
    as_writer(blocking)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD, channel="web"))

    result: dict = {}
    started = time.monotonic()
    thread = _post_in_thread(client, f"/worlds/{WORLD}/pause", result, json={"channel": "web"})
    try:
        effective_at = _seconds_until(
            lambda: store.worlds[WORLD].paused and _all_l1(store, ids), within_s=PAUSE_BOUND_S, started=started
        )
        assert effective_at is not None, "Pause all was not effective (paused flag and every policy at L1) in 2 s"
        assert effective_at <= PAUSE_BOUND_S
        assert blocking.entered.wait(timeout=PAUSE_BOUND_S), "the call never reached the writer"
        assert not store.events.get(WORLD), "the writer never returned, so no event can have landed yet"
        thread.join(timeout=STOP_BOUND_S + 3.0)
        assert not thread.is_alive(), "Pause all never returned against a writer that never returns"
        assert result["elapsed"] <= STOP_BOUND_S, f"Pause all answered after {result['elapsed']:.2f} s"
        assert result["resp"].status_code in (200, 202)
        assert result["resp"].json()["paused"] is True
    finally:
        blocking.release()
        thread.join(timeout=5.0)


def test_NFR_07_stop_autopilot_is_effective_within_5s_while_the_writer_never_returns(client, store):
    """STOP AUTOPILOT with 200 policies against a writer that never returns: every policy is at L1,
    seen from outside, within 5 s, and the response itself comes back inside 5 s."""
    ids = _policies(store, 200, level="L3")
    blocking = BlockingEventWriter(store)
    as_writer(blocking)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    result: dict = {}
    started = time.monotonic()
    thread = _post_in_thread(client, f"/worlds/{WORLD}/autopilot/stop", result)
    try:
        effective_at = _seconds_until(lambda: _all_l1(store, ids), within_s=STOP_BOUND_S, started=started)
        assert effective_at is not None, "STOP AUTOPILOT did not put all 200 policies at L1 within 5 s"
        assert effective_at <= STOP_BOUND_S
        thread.join(timeout=STOP_BOUND_S + 3.0)
        assert not thread.is_alive(), "STOP AUTOPILOT never returned against a writer that never returns"
        assert result["elapsed"] <= STOP_BOUND_S, f"STOP AUTOPILOT answered after {result['elapsed']:.2f} s"
        assert result["resp"].status_code in (200, 202)
        assert result["resp"].json()["stopped"] == 200
        assert result["resp"].json()["pending"] >= 1, "events that could not be written stay pending, not lost"
    finally:
        blocking.release()
        thread.join(timeout=5.0)


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    n_policies=st.integers(min_value=0, max_value=40),
    backlog=st.integers(min_value=0, max_value=4),
    delay_s=st.sampled_from([0.0, 0.01, 0.05]),
)
def test_NFR_07_pause_all_effective_and_world_paused_first_within_2s_property(
    client, store, n_policies, backlog, delay_s
):
    """For any policy count, backlog and writer latency in range: Pause all returns inside 2 s, every
    policy is L1, the world is paused and `world.paused` is the first event the writer committed."""
    # Hypothesis reuses the function-scoped fixtures across examples: start every example from a clean store.
    store.policies.clear()
    store.policy_worlds.clear()
    store.events.clear()
    store.pending_events.clear()
    ids = _policies(store, n_policies, level="L2")
    if backlog:
        store.pending_events[WORLD] = [make_pending_part(policy_id=f"pol_backlog_{i}") for i in range(backlog)]
    as_writer(SlowEventWriter(store, delay_s=delay_s))
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD, channel="web"))

    started = time.monotonic()
    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})
    elapsed = time.monotonic() - started

    assert resp.status_code in (200, 202), resp.text
    assert elapsed <= PAUSE_BOUND_S, f"Pause all took {elapsed:.2f} s with {n_policies} policies, delay {delay_s}"
    assert store.worlds[WORLD].paused is True
    assert _all_l1(store, ids)
    types = [e["type"] for e in store.events.get(WORLD, [])]
    assert types and types[0] == "world.paused", f"world.paused must be committed first, got {types[:3]}"


def test_NFR_07_stop_autopilot_with_a_healthy_writer_is_effective_and_confirmed_within_5s(client, store):
    """The common case, 200 policies and a writer that takes 10 ms per event: effective and confirmed
    (web and email) inside 5 s, one `policy.changed` per policy on the writer by then."""
    ids = _policies(store, 200, level="L3")
    as_writer(SlowEventWriter(store, delay_s=0.01))
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    started = time.monotonic()
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    elapsed = time.monotonic() - started

    assert resp.status_code in (200, 202), resp.text
    assert elapsed <= STOP_BOUND_S, f"STOP AUTOPILOT took {elapsed:.2f} s"
    assert _all_l1(store, ids)
    assert {c["channel"] for c in resp.json()["confirmations"]} == {"web", "email"}
    landed = [e for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"]
    pending = resp.json()["pending"]
    assert len(landed) + pending == 200, "every policy.changed either landed or is still pending, none lost"
