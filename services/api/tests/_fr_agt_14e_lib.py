"""Helpers for the FR-AGT-14e acceptance tests (Cloud Tasks hand-off of scheduled runs; interface: API_FR_AGT_14e.md).

Package-unique name, like `_fr_agt_14_lib.py` (whose `SchedApi`, `FakeTasksClient` and `task_body` these build on).
Nothing here is business logic: shared setup, a network block and the two assertions "this call was refused" and
"nothing was touched".
"""

from __future__ import annotations

import copy
import socket
from datetime import datetime
from typing import Any

import pytest
from _agt05_lib import CLEAR, work_plan
from _fr_agt_14_lib import MON_0330Z, SchedApi, l3_budget_policy
from tilo_harness.schedule import RunStart, slot_key

POLICY_ID = "pol_auto_budget"
CODE = r"^[a-z][a-z0-9_]{0,63}$"
RAN_BODY = {"ran": 1}  # the 200 body of a task that executed starts with this (plus "state")
LOOPBACK = ("127.0.0.1", "::1", "localhost")


def block_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Nothing leaves the process (no Cloud Tasks, no Google certificates): any connect to a non-loopback host raises.
    Returns the list of refused addresses, which a test may assert is empty."""
    refused: list[Any] = []
    real_connect = socket.socket.connect

    def connect(self: socket.socket, address: Any, *args: Any, **kwargs: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in LOOPBACK:  # the test client's own socketpair is loopback
            refused.append(address)
            raise OSError("network blocked in this test")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    return refused


def armed(rig: SchedApi, **policy: Any) -> Any:
    """The source task approved by the owner (a person's grant), its run quiet at the gate, and the owner's standing L3
    budget policy installed for what is scheduled later (needs a rig built with a `RunFlow`)."""
    source = rig.source_run_task()
    rig.store.policies[POLICY_ID] = l3_budget_policy(**policy)
    return source


def run_start(rig: SchedApi, schedule_id: str, **over: Any) -> RunStart:
    """The `RunStart` the Ticker would build for one slot of a stored schedule."""
    record = rig.schedules.get(schedule_id)
    slot = over.pop("slot", MON_0330Z)
    fields: dict[str, Any] = {
        "idempotency_key": slot_key(schedule_id, slot), "schedule_id": schedule_id,
        "owner_user_id": record.owner_user_id, "title": record.title, "approved_brief_ref": record.approved_brief_ref,
        "prior_world_id": None, "budget_cap": record.budget_cap, "slot": slot, "skipped": 0,
        "cache_namespace": schedule_id,
    }  # fmt: skip
    return RunStart(**{**fields, **over})


def gateless(rig: SchedApi) -> None:
    """From now on the Director's plan has no send (U1 -> U2 -> U3, no gate), so a run ends in `world.completed`
    without waiting for a person. The CL-INT-2 rig reads `compile_plan` at call time, so this takes effect at once."""
    rf = rig.rf
    assert rf is not None

    def compile_plan(*, brief: dict, approach: dict, budget_cap: float, context: Any = None) -> dict:
        rf.timeline.append("compile")
        rf.compile_calls.append({"brief": copy.deepcopy(brief), "approach": copy.deepcopy(approach), "cap": budget_cap})
        rf.last_plan = work_plan(approach["id"], budget_cap, first=CLEAR[0])
        return copy.deepcopy(rf.last_plan)

    rf.compile_plan = compile_plan  # type: ignore[method-assign]


def refused(response: Any) -> bool:
    """A call the route turned down without running anything: 422 (a body that is not what a task carries) or a 2xx with
    `ran` 0 (a permanent refusal Cloud Tasks must not retry)."""
    if response.status_code == 422:
        return True
    if 200 <= response.status_code < 300:
        body = response.json()
        return isinstance(body, dict) and body.get("ran") == 0
    return False


def assert_record_untouched(rig: SchedApi, schedule_id: str, due: datetime = MON_0330Z) -> None:
    record = rig.schedules.get(schedule_id)
    assert (record.next_due, record.failures, record.last_error, record.last_world_id, record.last_slot) == (
        due,
        0,
        None,
        None,
        None,
    ), schedule_id


def snapshot(rig: SchedApi) -> dict[str, Any]:
    """What a refused or ignored call must leave exactly as it was: the worlds, every world's event count, the runs
    and the number of plans the Director compiled."""
    return {
        "worlds": set(rig.store.worlds),
        "events": {w: len(e) for w, e in rig.store.events.items()},
        "runs": set(rig.store.runs),
        "compiled": len(rig.rf.compile_calls) if rig.rf is not None else None,
    }


def assert_unchanged(rig: SchedApi, before: dict[str, Any]) -> None:
    now = snapshot(rig)
    assert now["worlds"] == before["worlds"], "a world was created"
    assert now["events"] == before["events"], "an event was written"
    assert now["runs"] == before["runs"], "a run was started"
    assert now["compiled"] == before["compiled"], "a plan was compiled"
