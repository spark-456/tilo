"""FR-PA-15b (stacked on FR-PA-15; FR-PA-05, PE-12, PE-26, PE-21): the reminder sweep and the nudge routes in tilo-api.

The Scheduler's tick offers a nudge for each work item due today or past due to `NudgeGate`, which raises an
`alert.raised` nudge in the person's Desk world only inside their window, under their daily cap, once per item, rule
and day; the person snoozes it from `POST /v1/nudges/{id}/snooze` and it returns once. The gate's state lives behind a
store seam (a Firestore document per person; an in-memory fake here). No model, provider or network.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest
from _ppl11a_lib import PRIYA, SAM, own_item
from _ppl11c_lib import emitted, work_rig
from fastapi import Request
from google.api_core.exceptions import AlreadyExists, FailedPrecondition
from tilo_api import nudge_sweep
from tilo_channels.nudges import MemoryNudgeStore

SRC = pathlib.Path(nudge_sweep.__file__)
TODAY = "2026-10-06"  # NOW is 10:00Z = 15:30 in Asia/Kolkata


def _rig(people_rig: Any, monkeypatch: pytest.MonkeyPatch, items: list[tuple[str, str | None]]) -> tuple[Any, Request]:
    rig = work_rig(people_rig)
    for item_id, due in items:
        rig.add("work_items", own_item(item_id, PRIYA, due=due, due_text=None))
    store = MemoryNudgeStore()
    rig.app.dependency_overrides[nudge_sweep.get_nudge_store] = lambda: store
    monkeypatch.setenv(nudge_sweep.ENV_NUDGES, "1")
    request = Request({"type": "http", "app": rig.app, "headers": [], "method": "POST", "path": "/"})
    return rig, request


def _alerts(rig: Any) -> list[dict[str, Any]]:
    return [p for _w, p in emitted(rig) if p["type"] == "alert.raised"]


def test_FR_PA_15b_the_sweep_is_off_unless_switched_on(people_rig: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    rig, request = _rig(people_rig, monkeypatch, [("wi_due", TODAY)])
    monkeypatch.delenv(nudge_sweep.ENV_NUDGES)

    assert nudge_sweep.sweep(request, "2026-10-06T10:00:00.000Z") == 0
    assert _alerts(rig) == []


def test_FR_PA_15b_the_sweep_raises_a_nudge_for_work_due_today_or_past_due_only(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, request = _rig(
        people_rig,
        monkeypatch,
        [("wi_due", TODAY), ("wi_late", "2026-10-01"), ("wi_later", "2026-10-20"), ("wi_nodue", None)],
    )
    rig.add("work_items", own_item("wi_sams", SAM, due="2026-10-01", due_text=None))  # another person's own item
    rig.add("work_items", own_item("wi_done", PRIYA, due="2026-10-01", due_text=None, status="done"))

    assert nudge_sweep.sweep(request, "2026-10-06T10:00:00.000Z") == 3  # wi_due, wi_late and wi_sams (her own plate)
    mine = [(w, p) for w, p in emitted(rig) if p["type"] == "alert.raised" and p["target"] == PRIYA]
    assert [w for w, _p in mine] == ["w_desk_priya"] * 2
    texts = sorted(p["summary"] for _w, p in mine)
    assert texts == ["A work item is due within 24 hours.", "A work item is overdue."]
    for _w, part in mine:
        assert part["severity"] == "nudge" and part["vis"] == [] and part["authz"] is None
        assert part["actor"] == "system" and part["data"]["card_id"] is None
        assert "wi_" not in part["summary"] and "Water" not in part["summary"]
    assert [p["target"] for _w, p in emitted(rig)].count(SAM) == 1  # her own overdue item went to her own Desk world


def test_FR_PA_15b_a_second_pass_and_a_retry_raise_nothing_new_and_the_cap_holds(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, request = _rig(people_rig, monkeypatch, [(f"wi_late{n}", "2026-10-01") for n in range(7)])
    now = "2026-10-06T10:00:00.000Z"

    first = nudge_sweep.sweep(request, now)
    assert first == 5 and len(_alerts(rig)) == 5  # the daily cap for PRIYA
    assert nudge_sweep.sweep(request, "2026-10-06T10:05:00.000Z") == 0  # same day: no duplicate, still capped
    assert len(_alerts(rig)) == 5
    assert nudge_sweep.sweep(request, "2026-10-07T04:00:00.000Z") == 5  # next local day (09:30): the cap resets
    assert len(_alerts(rig)) == 10


def test_FR_PA_15b_nothing_is_raised_outside_the_persons_window(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, request = _rig(people_rig, monkeypatch, [("wi_late", "2026-10-01")])

    assert nudge_sweep.sweep(request, "2026-10-06T02:00:00.000Z") == 0  # 07:30 in Kolkata
    assert nudge_sweep.sweep(request, "2026-10-06T13:00:00.000Z") == 0  # 18:30
    assert _alerts(rig) == []
    assert nudge_sweep.sweep(request, "2026-10-06T03:30:00.000Z") == 1  # 09:00 exactly
    assert len(_alerts(rig)) == 1


def test_FR_PA_15b_a_flagged_row_is_never_nudged(people_rig: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    plate = {
        "today": TODAY,
        "rows": [
            {"ref": {"kind": "work_item", "id": "wi_flag"}, "flagged": True, "due": "2026-10-01"},
            {"ref": {"kind": "work_item", "id": "wi_ok"}, "flagged": False, "due": "2026-10-02"},
            {"ref": {"kind": "mail", "id": "msg_1"}, "flagged": False, "due": None},
            {"ref": {"kind": "work_item", "id": "wi_open"}, "flagged": False, "due": None},
        ],
    }
    got = nudge_sweep.candidates(plate, PRIYA)
    assert [(n.item_id, n.rule) for n in got] == [("wi_ok", "overdue")]


def test_FR_PA_15b_a_seam_that_is_not_wired_sends_nothing_and_raises_nothing(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, request = _rig(people_rig, monkeypatch, [("wi_late", "2026-10-01")])
    rig.unwire("people_stores")  # production default: 503

    assert nudge_sweep.sweep(request, "2026-10-06T10:00:00.000Z") == 0
    assert _alerts(rig) == []


def test_FR_PA_15b_the_person_snoozes_their_own_nudge_and_it_returns_once(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, request = _rig(people_rig, monkeypatch, [("wi_late", "2026-10-01")])
    assert nudge_sweep.sweep(request, "2026-10-06T10:00:00.000Z") == 1

    listed = rig.client.get("/v1/nudges").json()["nudges"]
    assert len(listed) == 1 and listed[0]["snoozed_until"] is None and listed[0]["rule"] == "overdue"
    alert_id = listed[0]["alert_id"]

    snoozed = rig.client.post(f"/v1/nudges/{alert_id}/snooze", json={"choice": "hour"})
    assert snoozed.status_code == 200 and snoozed.headers["cache-control"] == "no-store"
    assert snoozed.json()["snoozed_until"] == "2026-10-06T11:00:00.000Z"
    assert rig.client.get("/v1/nudges").json()["nudges"][0]["snoozed_until"] == "2026-10-06T11:00:00.000Z"

    assert nudge_sweep.sweep(request, "2026-10-06T10:30:00.000Z") == 0  # not yet
    assert nudge_sweep.sweep(request, "2026-10-06T11:00:00.000Z") == 1  # back, once
    assert nudge_sweep.sweep(request, "2026-10-06T11:30:00.000Z") == 0
    assert len(_alerts(rig)) == 2 and _alerts(rig)[0]["id"] != _alerts(rig)[1]["id"]


def test_FR_PA_15b_the_snooze_route_refuses_strangers_unknowns_and_bad_bodies(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, request = _rig(people_rig, monkeypatch, [("wi_late", "2026-10-01")])
    nudge_sweep.sweep(request, "2026-10-06T10:00:00.000Z")
    alert_id = rig.client.get("/v1/nudges").json()["nudges"][0]["alert_id"]

    rig.as_user(SAM)
    assert rig.client.get("/v1/nudges").json() == {"nudges": []}
    assert rig.client.post(f"/v1/nudges/{alert_id}/snooze", json={"choice": "hour"}).status_code == 404
    rig.as_user(PRIYA)
    assert rig.client.post("/v1/nudges/not-an-id/snooze", json={"choice": "hour"}).status_code == 404
    unknown = "01JB5VQ0000000000000000000"
    assert rig.client.post(f"/v1/nudges/{unknown}/snooze", json={"choice": "hour"}).status_code == 404
    for body in ({"choice": "next week"}, {"choice": "hour", "user": SAM}, {}):
        assert rig.client.post(f"/v1/nudges/{alert_id}/snooze", json=body).status_code == 422
    rig.sign_out()
    assert rig.client.post(f"/v1/nudges/{alert_id}/snooze", json={"choice": "hour"}).status_code == 401


class _Snap:
    def __init__(self, data: dict[str, Any] | None, stamp: int) -> None:
        self._data, self.update_time, self.exists = data, stamp, data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else dict(self._data)


class _Ref:
    def __init__(self, client: _Client, path: str) -> None:
        self._c, self._p = client, path

    def get(self) -> _Snap:
        held = self._c.docs.get(self._p)
        return _Snap(None if held is None else held[0], 0 if held is None else held[1])

    def create(self, data: dict[str, Any]) -> None:
        if self._p in self._c.docs:
            raise AlreadyExists("exists")
        self._c.docs[self._p] = (dict(data), 1)

    def update(self, data: dict[str, Any], option: Any = None) -> None:
        held = self._c.docs[self._p]
        if option is not None and option != held[1]:
            raise FailedPrecondition("changed")
        self._c.docs[self._p] = (dict(data), held[1] + 1)


class _Client:
    def __init__(self) -> None:
        self.docs: dict[str, tuple[dict[str, Any], int]] = {}
        self.before_write: Any = None

    def document(self, path: str) -> _Ref:
        return _Ref(self, path)

    def write_option(self, *, last_update_time: int) -> int:
        if self.before_write is not None:  # a rival instance writes between this one's read and its write
            hook, self.before_write = self.before_write, None
            hook()
        return last_update_time


def test_FR_PA_15b_the_persistent_store_is_one_document_a_person_and_survives_a_second_instance() -> None:
    client = _Client()
    first = nudge_sweep.FirestoreNudgeStore(client, org_id="org_x")
    second = nudge_sweep.FirestoreNudgeStore(client, org_id="org_x")

    def bump(state: dict[str, Any]) -> int:
        state["n"] = state.get("n", 0) + 1
        return state["n"]

    assert first.update("u_a", bump) == 1 and second.update("u_a", bump) == 2  # another instance sees the first
    assert second.update("u_b", bump) == 1  # per person
    assert set(client.docs) == {"orgs/org_x/nudge_state/u_a", "orgs/org_x/nudge_state/u_b"}
    assert set(client.docs["orgs/org_x/nudge_state/u_a"][0]) == {"state"}

    def boom(state: dict[str, Any]) -> None:
        state["n"] = 99
        raise RuntimeError("emit failed")

    with pytest.raises(RuntimeError):
        first.update("u_a", boom)
    assert second.update("u_a", bump) == 3  # a failed transaction recorded nothing
    with pytest.raises(ValueError):
        first.update("../u_a", bump)


def test_FR_PA_15b_a_lost_race_is_read_again_and_applied_on_the_newer_state() -> None:
    client = _Client()
    store = nudge_sweep.FirestoreNudgeStore(client, org_id="org_x")
    rival = nudge_sweep.FirestoreNudgeStore(client, org_id="org_x")

    def add(label: str) -> Any:
        def fn(state: dict[str, Any]) -> list[str]:
            state.setdefault("seen", []).append(label)
            return list(state["seen"])

        return fn

    store.update("u_a", add("first"))
    client.before_write = lambda: rival.update("u_a", add("rival"))
    assert store.update("u_a", add("mine")) == ["first", "rival", "mine"]  # nothing of the rival's was overwritten


def test_FR_PA_15b_the_sweep_path_imports_no_provider_model_or_network_client() -> None:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported & {"tilo_providers", "anthropic", "openai", "httpx", "requests", "urllib", "socket"} == set()
    assert "get_router" not in SRC.read_text(encoding="utf-8")
