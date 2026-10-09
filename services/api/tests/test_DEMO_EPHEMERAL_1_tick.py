"""DEMO-EPHEMERAL-1: the scheduler tick and Cloud Tasks delivery have no person. With the production `deps.get_store`
(no override, no Firebase principal) they get the durable store, never the sign-in 401."""

from __future__ import annotations

import pytest
from _fr_agt_14_lib import MON_0330Z, SchedApi, task_body
from _fr_agt_14e_lib import armed, block_network
from tilo_api import deps, durable_store


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    return block_network(monkeypatch)


@pytest.fixture
def rig(run_flow, monkeypatch):
    rig = SchedApi(run_flow.flow, monkeypatch, rf=run_flow)
    rig.clock.set(MON_0330Z)
    return rig


def test_DEMO_EPHEMERAL_1_the_tasks_delivery_runs_a_google_schedule_on_the_durable_store(rig, monkeypatch):
    source = armed(rig)
    rig.insert(source, "sched_a")
    ov, used = rig.app.dependency_overrides, []
    writer = ov[deps.get_event_writer]()
    ov.pop(deps.get_store)  # the production store seam
    ov.pop(deps.get_current_principal)  # and no Firebase principal: the request carries only the Tasks OIDC token
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setattr(durable_store, "deployed", lambda: used.append(1) or (rig.store, writer))
    response = rig.task_call(task_body("sched_a", MON_0330Z))
    assert response.status_code == 200 and response.json().get("ran") == 1, response.text
    assert used, "the tick did not use the durable store"
