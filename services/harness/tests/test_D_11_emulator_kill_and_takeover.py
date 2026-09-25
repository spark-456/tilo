"""D-11 (crash recovery, PRD 22.2, ticket brief items 6 and 10): killing the harness skeleton
mid-run leaves a valid, dense event prefix whose views agree with it -- not a partial write --
and a new writer takes over once the killed writer's lease expires, continuing at
`last_seq + 1` read from the store, without overwriting anything already written.

P0-09 only promises a valid prefix and a clean takeover (resuming the interrupted run itself is
FR-AGT-10, a later ticket).

@pytest.mark.emulator: see test_PRD_15_3_emulator_skeleton_run.py's module docstring.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest
from conftest import sequential_ulid, world_requested_kwargs

pytestmark = pytest.mark.emulator

LEASE_S = 3.0
STEP_DELAY_S = 0.3


def _wait_for_events(store: object, org_id: str, world_id: str, *, min_count: int, timeout_s: float) -> list[dict]:
    """Polls the store until at least `min_count` events land (or `timeout_s` elapses), rather
    than guessing a sleep: a cold subprocess pays google-cloud-firestore's and google-adk's own
    import cost (several seconds each, observed) before its first write, and that cost varies a
    lot run to run, so a fixed sleep is either too short (flaky) or too long (risks the run
    finishing before the kill)."""
    deadline = time.monotonic() + timeout_s
    events: list[dict] = []
    while time.monotonic() < deadline:
        events = store.read_events(org_id, world_id)  # type: ignore[attr-defined]
        if len(events) >= min_count:
            return events
        time.sleep(0.2)
    return events


def test_D_11_kill_mid_run_leaves_a_valid_dense_prefix_whose_views_agree(emulator_host: str, repo_root) -> None:
    from tilo_harness.store import FirestoreStore
    from tilo_harness.validator import EventValidator

    org_id, world_id, run_id = "org_demo", "w_kill_mid_run_1", "r_kill_mid_run_1"
    store = FirestoreStore(project_id="demo-tilo")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tilo_harness.skeleton",
            "--org",
            org_id,
            "--world",
            world_id,
            "--run",
            run_id,
            "--lease-s",
            str(LEASE_S),
            "--step-delay",
            str(STEP_DELAY_S),
        ],
        cwd=repo_root,
        env={**os.environ, "FIRESTORE_EMULATOR_HOST": emulator_host},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Wait for at least 2 of the run's 8 events to land -- proof the process is genuinely
        # mid-run, not just started -- then kill it well before it can finish on its own.
        _wait_for_events(store, org_id, world_id, min_count=2, timeout_s=45.0)
    finally:
        proc.kill()
        proc.wait(timeout=15)

    stream = store.read_events(org_id, world_id)
    assert stream, "at least one event must have been written before the kill"
    assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1)), (
        f"D-11: a killed run must leave no seq gap and no partial write, got seq {[e['seq'] for e in stream]}"
    )

    validator = EventValidator.from_repo(repo_root)
    still_broken = {e["seq"]: p for e in stream if (p := validator.problems(e))}
    assert still_broken == {}, f"D-11: the killed prefix must still validate: {still_broken}"

    shared_view = store.read_view(org_id, world_id, "shared")
    expected_shared_ids = [e["id"] for e in stream if e["vis"] == "all"]
    assert [e["id"] for e in shared_view] == expected_shared_ids, (
        "D-11: the shared view must agree with the killed prefix (same vis='all' events, same order)"
    )
    assert [e["seq"] for e in shared_view] == list(range(1, len(shared_view) + 1)), (
        "D-11: the shared view's vseq must still be dense after the kill"
    )


def test_D_11_new_writer_takes_over_after_the_killed_writers_lease_expires(
    emulator_host: str, village_basic_layout: dict
) -> None:
    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import WorldWriter

    org_id, world_id, run_id = "org_demo", "w_kill_takeover_1", "r_kill_takeover_1"
    store = FirestoreStore(project_id="demo-tilo")

    crashed = WorldWriter(
        store,
        org_id=org_id,
        world_id=world_id,
        run_id=run_id,
        layout=village_basic_layout,
        writer_id="writer_crashed",
        lease_s=LEASE_S,
    )
    crashed.open()
    first = crashed.append(_built_event(1, sequential_ulid(9001)))
    # crashed "dies" here without calling .close() -- the lease is left to expire on its own.

    time.sleep(LEASE_S + 1.0)

    successor = WorldWriter(
        store,
        org_id=org_id,
        world_id=world_id,
        run_id=run_id,
        layout=village_basic_layout,
        writer_id="writer_successor",
        lease_s=LEASE_S,
    )
    successor.open()  # must not raise WriterBusy: the crashed writer's lease has expired
    resumed = successor.append(_built_event(2, sequential_ulid(9002), cause=first["id"]))

    assert resumed["seq"] == 2, "D-11: the successor must continue at last_seq + 1 read from the store"
    stored = store.read_events(org_id, world_id)
    assert [e["seq"] for e in stored] == [1, 2]
    assert stored[0]["id"] == first["id"], "D-11: takeover must never overwrite an existing event"


def _built_event(seq: int, event_id: str, *, cause: str | None = None) -> dict:
    return {
        "v": "1.0",
        "id": event_id,
        "seq": seq,
        "ts": "2026-09-29T09:30:00.000Z",
        "world_id": "w_kill_takeover_1",
        "run_id": "r_kill_takeover_1",
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "cause": cause,
        "vis": "all",
        "authz": None,
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
        **world_requested_kwargs(target="w_kill_takeover_1"),
    }
