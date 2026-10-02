"""CL-INT-2 / FR-AGT-11 ("Retrying a send step never produces a second email"; PRD 8.5 "side effects go through an
outbox, so they happen exactly once"; OB-03, SEC-03): through the whole run. The mock connector sends only through
the outbox; a send that crashes after the provider accepted it is retried; repeated or concurrent approvals of the
same gate write one `approval.resolved`, one outbox entry and one send. Sequence: API_CL_INT_2.md.
"""

from __future__ import annotations

import threading

from _clint2_lib import wait_for
from fastapi.testclient import TestClient


def test_FR_AGT_11_a_send_that_crashed_after_the_connector_recorded_it_is_retried_without_a_second_send(
    crashing_run_flow,
):
    rf = crashing_run_flow
    _, card = rf.run_to_gate()

    assert rf.answer(card["id"], "approve").status_code == 200

    wait_for(lambda: rf.events("world.completed"), timeout=12.0, what="world.completed after the retried send")
    assert rf.adapter.calls >= 2  # the step really was retried ...
    assert len(rf.adapter.sent) == 1  # ... and the second attempt sent nothing new (same idempotency key)
    assert len(rf.events("data.transfer")) == 1 and len(rf.events("artifact.delivered")) == 1
    (entry,) = rf.outbox_store.all_entries()
    assert entry["state"] == "sent" and rf.adapter.sent[0]["idempotency_key"] == entry["idempotency_key"]


def test_FR_AGT_11_answering_approve_again_does_not_send_again(run_flow):
    _, card = run_flow.run_to_gate()

    statuses = [run_flow.answer(card["id"], "approve").status_code for _ in range(3)]

    assert statuses[0] == 200 and 200 not in statuses[1:]  # a card resolves once
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    run_flow.quiet_stream()
    assert len(run_flow.events("approval.resolved")) == 1
    assert len(run_flow.outbox_store.all_entries()) == 1 and len(run_flow.adapter.sent) == 1
    assert len(run_flow.events("data.transfer")) == 1 and len(run_flow.events("world.completed")) == 1


def test_FR_AGT_11_concurrent_approvals_of_one_gate_send_once(run_flow):
    _, card = run_flow.run_to_gate()
    statuses: list[int] = []
    barrier = threading.Barrier(6)

    def approve() -> None:
        client = TestClient(run_flow.app, raise_server_exceptions=False)
        barrier.wait()
        statuses.append(run_flow.answer(card["id"], "approve", client=client).status_code)

    threads = [threading.Thread(target=approve) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert statuses.count(200) == 1, statuses
    assert all(status in (200, 400, 404, 409) for status in statuses), statuses
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    run_flow.quiet_stream()
    assert len(run_flow.events("approval.resolved")) == 1 and len(run_flow.events("data.transfer")) == 1
    assert len(run_flow.outbox_store.all_entries()) == 1 and len(run_flow.adapter.sent) == 1
