"""D-11 fix round, qa-breaker repro 2 exactly: two concurrent `python -m tilo_harness.skeleton`
processes against the same `--world`/`--run` must not both get a live lease and both write --
one succeeds, the other is refused, and the stored stream stays dense with unique seqs (never
the old bug's 9 events for an 8-event fixture plan, two `world.completed`s, overwritten seq 1-8).

Also pins `FirestoreStore.transact` writing event/view docs with `transaction.create`: a second
attempt at a seq the store already holds must raise, never silently overwrite it.

@pytest.mark.emulator: see test_PRD_15_3_emulator_skeleton_run.py's module docstring.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.emulator

WRITTEN_PER_RUN = 8  # DirectorAgent (2) + LeadAgent (2) + SpecialistAgent (2) + world.requested + world.completed


def _cli_args(*, org_id: str, world_id: str, run_id: str, lease_s: float, step_delay: float) -> list[str]:
    return [
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
        str(lease_s),
        "--step-delay",
        str(step_delay),
    ]


def test_D_11_two_concurrent_cli_runs_on_the_same_world_never_corrupt_the_stream(emulator_host: str, repo_root) -> None:
    from tilo_harness.store import FirestoreStore

    org_id, world_id, run_id = "org_demo", "w_concurrent_cli_1", "r_concurrent_cli_1"
    env = {**os.environ, "FIRESTORE_EMULATOR_HOST": emulator_host}
    args = _cli_args(org_id=org_id, world_id=world_id, run_id=run_id, lease_s=30.0, step_delay=0.3)

    # Started back to back, well inside each other's 30s lease: the second must not also get a
    # live lease on the same world (the qa-breaker repro's exact bug).
    proc_a = subprocess.Popen(args, cwd=repo_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proc_b = subprocess.Popen(args, cwd=repo_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # Generous timeouts (P0-09 follow-up, FR-AGT-01/02/03 ticket brief item 6c): under
    # contention a loser retries the Firestore transaction before giving up as WriterBusy, which
    # can take longer than 60s on a loaded CI runner; the test only cares that exactly one run
    # wins and the stream stays uncorrupted, not how fast the loser gives up.
    out_a, err_a = proc_a.communicate(timeout=180)
    out_b, err_b = proc_b.communicate(timeout=180)

    assert (proc_a.returncode == 0) != (proc_b.returncode == 0), (
        f"D-11: exactly one of the two concurrent runs must succeed, got returncodes "
        f"{proc_a.returncode!r}/{proc_b.returncode!r}\nstderr a:\n{err_a}\nstderr b:\n{err_b}"
    )

    winner_out = out_a if proc_a.returncode == 0 else out_b
    loser_err = err_b if proc_a.returncode == 0 else err_a
    winner_lines = [line for line in winner_out.splitlines() if line.strip()]
    assert len(winner_lines) == 1, f"the winning run must print exactly one JSON line, got:\n{winner_out!r}"
    payload = json.loads(winner_lines[0])
    assert payload == {"written": WRITTEN_PER_RUN, "world_id": world_id, "last_seq": WRITTEN_PER_RUN}
    assert "WriterBusy" in loser_err or "leased" in loser_err.lower(), (
        f"D-11: the losing run must fail because the world was leased, not silently succeed; stderr:\n{loser_err}"
    )

    store = FirestoreStore(project_id="demo-tilo")
    stream = store.read_events(org_id, world_id)
    assert len(stream) == WRITTEN_PER_RUN, (
        f"D-11: the stream must hold exactly one run's worth of events ({WRITTEN_PER_RUN}), "
        f"not a mix of two overlapping runs, got {len(stream)}"
    )
    seqs = [e["seq"] for e in stream]
    assert seqs == list(range(1, WRITTEN_PER_RUN + 1)), f"D-11: the stream must be dense with unique seqs, got {seqs}"
    assert sum(1 for e in stream if e["type"] == "world.completed") == 1, (
        "D-11: exactly one world.completed must have landed, not two overlapping runs' worth"
    )


def test_D_11_firestore_store_create_refuses_to_overwrite_an_existing_event_doc(emulator_host: str) -> None:
    """`FirestoreStore.transact` must use `transaction.create`, never `transaction.set`, for
    event/view docs: attempting to write a seq the store already holds must raise, and the
    original document's content must survive untouched."""
    from google.api_core import exceptions as gax_exceptions
    from tilo_harness.store import FirestoreStore

    org_id, world_id = "org_demo", "w_create_not_overwrite_1"
    store = FirestoreStore(project_id="demo-tilo")

    first_event = {"seq": 1, "id": "01JB5VQ0000000000000005001", "marker": "first"}

    def _write_first(head):
        return dict(head, last_seq=1), first_event, []

    store.transact(org_id, world_id, _write_first)

    second_event = {"seq": 1, "id": "01JB5VQ0000000000000005002", "marker": "second-must-not-land"}

    def _write_second_same_seq(head):
        return dict(head, last_seq=1), second_event, []

    with pytest.raises(gax_exceptions.AlreadyExists):
        store.transact(org_id, world_id, _write_second_same_seq)

    stream = store.read_events(org_id, world_id)
    assert len(stream) == 1
    assert stream[0]["marker"] == "first", "D-11: create() must refuse the overwrite; the original doc must survive"
