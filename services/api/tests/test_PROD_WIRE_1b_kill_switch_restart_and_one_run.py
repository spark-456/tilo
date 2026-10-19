"""PROD-WIRE slice 1b, ADR-0026 decision 3 (the kill-switch exception) and decision 5 (no second run, and the one
`world.failed` of a restart). Interface: `_pw1b_lib.py`. Over memory by default, on the emulator under `-m emulator`.

FR-HIL-07: Pause all, Stop all and revoke are applied here first and committed after. If the commit fails the change
stays applied in this process (a run still stops, FR-WLD-07) and the answer is 503 "not saved"; if only the drain
fails the answer stays 202 `pending`, and the parts wait in the durable queue. HR-1: a world must not look busy forever
after a restart, and a started world is never started twice.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _api_lib import as_principal, make_principal, ulid
from _pw1b_lib import (
    OWNER,
    P1,
    P2,
    RESTARTED,
    RUN,
    T1,
    W1,
    W2,
    FlakyWriter,
    commits_fail,
    ended,
    part,
    policy,
    requested,
    seed,
    started,
    task,
    wire,
    world,
)  # fmt: skip
from tilo_api import app, runs
from tilo_api.world_writer import PREPLAN_LAYOUT
from tilo_harness.writer import WorldWriter

T2 = "t_" + ulid(2)
SWITCHES = [f"/worlds/{W1}/pause", f"/worlds/{W1}/autopilot/stop", f"/policies/{P1}/revoke"]
PAUSED = part(
    3, type="world.paused", actor=OWNER, target=W1, summary="Paused.", data={"reason": "pause_all", "channel": "web"}
)


def _switch_rig(rig):
    store, writer = rig.process()
    seed(
        store, worlds={W1: world(), W2: world()}, policies={P1: policy(P1, level="L2"), P2: policy(P2, level="L3")},
        policy_worlds={P1: W1, P2: W2},
    )  # fmt: skip
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=W1))
    return store, writer


@pytest.mark.parametrize("path", SWITCHES)
def test_PROD_WIRE_1b_a_kill_switch_stays_applied_here_and_answers_503_not_saved_when_its_commit_fails(
    client, pw1b_rig, path: str
) -> None:
    store, _ = _switch_rig(pw1b_rig)
    wire(app, store)
    with commits_fail(pw1b_rig.backend):
        response = client.post(path)
    assert response.status_code == 503 and "not saved" in response.text.lower().replace("_", " ")
    assert store.policies[P1]["level"] == "L1", "applied in this process, so a run still stops"
    assert store.worlds[W1].paused is path.endswith("/pause")
    assert pw1b_rig.backend.read("policies", P1)["record"]["level"] == "L2", "and not saved"


def test_PROD_WIRE_1b_a_kill_switch_keeps_its_202_when_the_drain_fails_and_the_queue_survives_a_restart(
    client, pw1b_rig
) -> None:
    store, writer = _switch_rig(pw1b_rig)
    wire(app, store, FlakyWriter(writer))  # the commit works; every append to the event store fails
    response = client.post(f"/worlds/{W1}/pause")
    assert response.status_code == 202 and response.json()["paused"] is True and response.json()["pending"] >= 1
    assert pw1b_rig.backend.read("worlds", W1)["paused"] is True and not pw1b_rig.stream(W1)
    assert {"world.paused", "policy.changed"} <= {p["type"] for p in pw1b_rig.backend.queue(W1)}
    cold, _ = pw1b_rig.process()
    cold.load_world(W1, settle=True)  # the restart resends the queued parts by id
    types = [e["type"] for e in pw1b_rig.stream(W1)]
    assert types.count("world.paused") == 1 and types.count("policy.changed") == 1
    assert pw1b_rig.backend.queue(W1) == []


def test_PROD_WIRE_1b_stop_all_on_a_cold_store_loads_the_owners_policies_and_worlds_first(client, pw1b_rig) -> None:
    _, writer = _switch_rig(pw1b_rig)
    writer.reopen()
    cold, _ = pw1b_rig.process()
    wire(app, cold)  # only W1 is loaded by the request; P1 and P2 and W2 are in the backend alone
    response = client.post(f"/worlds/{W1}/autopilot/stop")
    assert response.status_code == 200 and response.json()["stopped"] == 2
    assert [pw1b_rig.backend.read("policies", p)["record"]["level"] for p in (P1, P2)] == ["L1", "L1"]
    assert [[e["type"] for e in pw1b_rig.stream(w)] for w in (W1, W2)] == [["policy.changed"]] * 2


def _stopped_process(rig, parts: list[dict], *, paused: bool = False) -> None:
    """An earlier process that wrote `parts` for W1 (a started world, as its record and stream say) and exited."""
    warm, writer = rig.process()
    seed(warm, worlds={W1: world(paused=paused)}, tasks={T1: task(granted=True)}, parts={W1: parts})
    warm.drain(W1)
    writer.reopen()


def _failures(rig) -> list[dict]:
    return [e for e in rig.stream(W1) if e["type"] == "world.failed"]


def test_PROD_WIRE_1b_a_world_whose_stream_has_world_started_never_gets_a_second_run(
    pw1b_rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stopped_process(pw1b_rig, [requested(1), started(2)])
    cold, _ = pw1b_rig.process()
    cold.load_world(W1, settle=True)
    made: list[tuple] = []
    monkeypatch.setattr(runs, "Run", lambda *a: (made.append(a), SimpleNamespace(main=lambda: None))[1])
    runs.start_run(cold, cold.load_task(T1, settle=True), approach={}, budget_cap=40.0, seams=None)
    assert made == [] and cold.runs == {}, "world.started is in the stream: no second run, in any process"
    seed(cold, worlds={W2: world()}, tasks={T2: task(W2, granted=True)}, parts={W2: [requested(4, W2)]})
    runs.start_run(cold, cold.tasks[T2], approach={}, budget_cap=40.0, seams=None)
    assert len(made) == 1, "a world that never started still gets its run"


def test_PROD_WIRE_1b_a_restart_writes_exactly_one_world_failed_for_a_world_that_started(pw1b_rig) -> None:
    _stopped_process(pw1b_rig, [requested(1), started(2)])
    cold, cold_writer = pw1b_rig.process()
    cold.load_world(W1, settle=True)
    (failed,) = _failures(pw1b_rig)
    assert failed["actor"] == "system" and failed["data"] == {"reason": RESTARTED, "unit": None}
    assert failed["run_id"] == RUN and pw1b_rig.stream(W1)[-1] == failed and cold.events[W1] == pw1b_rig.stream(W1)
    cold_writer.reopen()
    again, _ = pw1b_rig.process()
    again.load_world(W1, settle=True)
    assert len(_failures(pw1b_rig)) == 1, "a terminal event is in the stream: a second process adds nothing"


@pytest.mark.parametrize("case", ["paused", "completed", "never started", "a run of its own"])
def test_PROD_WIRE_1b_a_restart_writes_no_world_failed_when(pw1b_rig, case: str) -> None:
    parts = {
        "paused": [requested(1), started(2), PAUSED], "completed": [requested(1), started(2), ended(3)],
        "never started": [requested(1)], "a run of its own": [requested(1), started(2)],
    }[case]  # fmt: skip
    _stopped_process(pw1b_rig, parts, paused=case == "paused")
    cold, _ = pw1b_rig.process()
    if case == "a run of its own":
        cold.runs[W1] = object()
    cold.load_world(W1, settle=True)
    assert _failures(pw1b_rig) == [] and [e["type"] for e in pw1b_rig.stream(W1)] == [p["type"] for p in parts]


def test_PROD_WIRE_1b_a_restart_leaves_the_failure_to_whoever_holds_the_lease(pw1b_rig) -> None:
    _stopped_process(pw1b_rig, [requested(1), started(2)])
    rival = WorldWriter(
        pw1b_rig.events, org_id=pw1b_rig.org, world_id=W1, run_id=RUN, layout=PREPLAN_LAYOUT, writer_id="rival"
    )
    rival.open()
    cold, _ = pw1b_rig.process()
    assert cold.load_world(W1, settle=True) is not None and _failures(pw1b_rig) == [], (
        "a busy lease is skipped, never raised"
    )
    rival.close()
    later, _ = pw1b_rig.process()
    later.load_world(W1, settle=True)
    assert len(_failures(pw1b_rig)) == 1
