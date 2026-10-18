"""CL-INT-2 / FR-WLD-07 ("Pause all stops every agent in <= 2 s and shows a veil ... no event after 2 s except
`world.paused`"; PRD 9.4 HR-3, 10.4 kill switches; seam via #120): `POST /worlds/{id}/pause` during the run.
After the veil is up the run writes nothing else, starts no unit and sends nothing, even when the gate card is
answered afterwards. Sequence: API_CL_INT_2.md.
"""

from __future__ import annotations

import threading
import time

from _clint2_lib import WORK_PREFIXES, index_of, wait_for
from fastapi.testclient import TestClient

PAUSE_BUDGET_S = 2.0  # FR-WLD-07


def test_R_RUN_malformed_layout_finishes_with_failure_instead_of_keyerror(run_flow, caplog):
    rf = run_flow
    rf.build_layout = lambda _plan, *, world_id: {}
    rf.start()
    assert rf.approve().status_code == 200
    wait_for(lambda: rf.events("world.failed"), what="world.failed after malformed layout")
    assert rf.events("world.started") == []
    assert "KeyError" not in caplog.text


def test_R_RUN_start_pause_continue_starts_a_new_run_in_the_same_world_and_finishes(run_flow):
    rf = run_flow
    rf.runner.block_on = "U3"
    rf.start()
    first_approve = []
    approving = threading.Thread(target=lambda: first_approve.append(rf.approve()))
    approving.start()
    assert rf.runner.entered.wait(8), "the first run never reached U3"
    wait_for(lambda: rf.events("artifact.created"), what="recorded progress before pause")
    first_run = rf.store.runs[rf.world_id]
    try:
        assert rf.pause().status_code in (200, 202)
        wait_for(lambda: rf.events("world.paused"), what="the first run to pause")
    finally:
        rf.runner.release.set()
        approving.join(10)
    assert first_approve and first_approve[0].status_code == 200

    continued = rf.flow.client.post(f"/worlds/{rf.world_id}/rerun")
    assert continued.status_code == 200, continued.text
    assert first_run._ended.is_set(), "Continue did not wait for the paused run to stop"
    assert continued.json()["world_id"] == rf.world_id
    wait_for(lambda: rf.events("world.started") if len(rf.events("world.started")) == 2 else [], what="continued run")
    cards = wait_for(
        lambda: [card for card in rf.cards().json() if card["kind"] == "gate"],
        what="the continued run's gate",
    )
    assert rf.answer(cards[-1]["id"], "approve").status_code == 200
    wait_for(lambda: rf.events("world.completed"), what="the continued run to finish")

    assert len({event["run_id"] for event in rf.events("world.started")}) == 2
    assert any("Earlier run completed:" in line for line in rf.compile_calls[-1]["brief"]["constraints"])


def test_FR_WLD_07_pause_all_during_the_run_stops_every_event_except_world_paused(run_flow):
    rf = run_flow
    rf.runner.block_on = "U2"  # the run is mid-flight: U1 done, U2 working
    rf.start()
    approving = threading.Thread(target=rf.approve)
    approving.start()
    try:
        assert rf.runner.entered.wait(8), "the run never reached U2"

        paused = rf.pause(TestClient(rf.app, raise_server_exceptions=False))
        assert paused.status_code in (200, 202), paused.text
        (veil,) = wait_for(lambda: rf.events("world.paused"), what="world.paused")
        assert veil["data"]["reason"] == "pause_all"
        time.sleep(PAUSE_BUDGET_S)  # every agent has stopped within 2 s: from here on, nothing may be written
        rf.runner.release.set()  # the in-flight unit finishes its work after the veil
        approving.join(10)
        assert not approving.is_alive()
        stream = rf.quiet_stream(0.8)
    finally:
        rf.runner.release.set()
        approving.join(5)

    assert rf.store.worlds[rf.world_id].paused is True
    after = [e["type"] for e in stream[index_of(stream, veil) + 1 :]]
    assert after == [], after  # no event after the veil, not even the unit that was in flight
    assert "U3" not in rf.runner.ran and "U4" not in rf.runner.ran  # no new unit starts
    assert rf.outbox_store.all_entries() == [] and rf.adapter.sent == []
    assert [e["type"] for e in stream].count("world.paused") == 1
    assert rf.delivery().status_code == 409


def test_FR_WLD_07_a_gate_answered_after_pause_all_sends_nothing(run_flow):
    rf = run_flow
    _, card = rf.run_to_gate()
    assert rf.pause().status_code in (200, 202)
    (veil,) = wait_for(lambda: rf.events("world.paused"), what="world.paused")

    rf.answer(card["id"], "approve")  # the person's answer is not an agent action; whether it is accepted is open

    stream = rf.quiet_stream(1.0)
    after = [e["type"] for e in stream[index_of(stream, veil) + 1 :]]
    assert not [t for t in after if t.startswith(WORK_PREFIXES)], after
    assert not {"data.transfer", "artifact.delivered", "world.completed"} & set(after), after
    assert rf.adapter.sent == []
    assert not [e for e in rf.outbox_store.all_entries() if e["state"] == "sent"]
    assert rf.delivery().status_code == 409
