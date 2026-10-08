"""FR-TEAM-04 on tilo-api (issue #621): the five stop-and-ask switches through routes.

Done-when: "Must-ask rules from the PRD can't be switched off; every change is logged." Every switch is Owner-only
(PRD 10.1 gives an Approver no policy rights, so not even `weekend`); a stored state whose Must-ask key is False is
read as on; a change is logged as one `team_rule.changed` event (ADR-0027). The `weekend`
switch is read on the scheduled-run path: on, a weekend slot is held (not skipped, not counted) until Monday.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from _team_routes_lib import APPROVER, MEMBER, OWNER, VIEWER, state, team_api


def _switches(view: dict) -> dict[str, bool]:
    return {s["key"]: s["on"] for s in view["switches"]}


def test_FR_TEAM_04_the_five_switches_are_served_with_their_must_ask_lock() -> None:
    with team_api() as api:
        rows = api.as_(VIEWER).get().json()["switches"]
    assert [(r["key"], r["on"], r["must_ask"]) for r in rows] == [
        ("spend", True, True), ("share", True, True), ("undo", True, True), ("tools", True, False),
        ("weekend", False, False),
    ]  # fmt: skip


def test_FR_TEAM_04_a_stored_must_ask_switch_that_is_off_is_read_as_on() -> None:
    from tilo_api.team_store import effective_switches

    stored = {"spend": False, "share": False, "undo": False, "tools": True, "weekend": False}
    assert effective_switches(state(switches=stored))["spend"] is True
    with team_api(state(switches=stored)) as api:
        served = _switches(api.get().json())
        assert (served["spend"], served["share"], served["undo"]) == (True, True, True)
        api.put("/v1/team/switches/weekend", {"on": True})
        assert api.store.read().switches["spend"] is True  # a write never carries the stale False forward


def test_FR_TEAM_04_the_owner_turns_an_optional_switch_and_the_change_is_logged() -> None:
    with team_api() as api:
        response = api.put("/v1/team/switches/weekend", {"on": True})
        assert response.status_code == 200, response.text
        assert _switches(response.json())["weekend"] is True
        assert api.store.read().switches["weekend"] is True
        [(_world, part)] = api.writer.parts  # logged as a registered `team_rule.changed` (ADR-0027), not a log line
    assert part["type"] == "team_rule.changed" and part["actor"] == OWNER and part["data"]["key"] == "weekend"


def test_FR_TEAM_04_a_must_ask_switch_cannot_go_off_through_the_route() -> None:
    with team_api() as api:
        for key in ("spend", "share", "undo"):
            assert api.put(f"/v1/team/switches/{key}", {"on": False}).status_code == 409
        assert all(api.store.read().switches[k] for k in ("spend", "share", "undo"))


@pytest.mark.parametrize("actor", [APPROVER, MEMBER, VIEWER])
@pytest.mark.parametrize("key", ["weekend", "tools"])
def test_FR_TEAM_04_every_switch_is_owner_only(actor: str, key: str) -> None:
    with team_api() as api:
        before = api.store.read().switches
        assert api.as_(actor).put(f"/v1/team/switches/{key}", {"on": not before[key]}).status_code == 403
        assert api.store.read().switches == before


def test_FR_TEAM_04_an_unknown_switch_or_a_non_bool_is_refused() -> None:
    with team_api() as api:
        assert api.put("/v1/team/switches/nope", {"on": True}).status_code == 404
        assert api.put("/v1/team/switches/weekend", {"on": "yes"}).status_code == 422
        assert api.put("/v1/team/switches/weekend", {"on": 1}).status_code == 422


# --- the weekend switch on the scheduled-run path ----------------------------------------------------------------

SATURDAY = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
MONDAY = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def test_FR_TEAM_04_weekend_hold_is_on_only_when_the_switch_is_on_and_the_day_is_a_weekend() -> None:
    from tilo_api.team_access import weekend_hold

    on = state(switches={"spend": True, "share": True, "undo": True, "tools": True, "weekend": True})
    assert weekend_hold(on, SATURDAY, "UTC") is True
    assert weekend_hold(on, MONDAY, "UTC") is False
    assert weekend_hold(state(), SATURDAY, "UTC") is False
    assert weekend_hold(None, SATURDAY, "UTC") is False  # no team store wired: as before


def test_FR_TEAM_04_a_scheduled_start_on_a_weekend_is_held_not_counted() -> None:
    from tilo_api.schedules import ScheduleStarter
    from tilo_api.team_store import InMemoryTeamStore
    from tilo_harness.schedule import StartSkipped

    record = SimpleNamespace(
        owner_user_id=OWNER, brief={}, approach={}, enabled=True, cadence=SimpleNamespace(tz="UTC")
    )
    schedules = SimpleNamespace(get=lambda _id: record)
    on = state(switches={"spend": True, "share": True, "undo": True, "tools": True, "weekend": True})
    starter = ScheduleStarter(
        store=SimpleNamespace(), schedules=schedules, seams=None, clock=lambda: SATURDAY,  # type: ignore[arg-type]
        team=InMemoryTeamStore(on),
    )  # fmt: skip
    with pytest.raises(StartSkipped) as held:
        starter.start(SimpleNamespace(schedule_id="sched_1", owner_user_id=OWNER))  # type: ignore[arg-type]
    assert held.value.code == "weekend_hold" and held.value.count is False
