"""FR-AGT-14d (rollout follow-ups of the scheduled-runs security and code reviews), on tilo-api. API_FR_AGT_14d.md.

1. LAZY SEAMS AFTER AUTH. `POST /internal/schedules/tick` used to resolve the run seams and the schedule store as
   FastAPI dependencies BEFORE its token check, so an anonymous 401 built both (about 80 ms each). They are now behind
   two factories (`get_seams_factory`, `get_schedule_store_factory`) that the route calls only after the token passed:
   no token, a bad token and a wrong-iss/aud/email token leave both counters at 0; a good token resolves each once.
   The 503 for an unconfigured audience or caller still comes first, before anything is built.
2. A DISABLED OWNER'S SCHEDULES NEVER FIRE (the route side of `disable_for_owner`).
3. `run_seams_unwired` DOES NOT COUNT. The real `ScheduleStarter` raises
   `StartSkipped("run_seams_unwired", count=False)`; through the route, 25 schedules and unwired seams for
   20 ticks disable and back off none.
4. PATCH `{"enabled": true}` MOVES a stale `next_due` to the first slot after now (the store's clock, the fake one).

Fakes: `_fr_agt_14_lib.py`. The store and ticker sides of items 2 to 4 are in services/harness/tests.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from _fr_agt_14_lib import (
    API_SA,
    AUDIENCE,
    ENV_AUDIENCE,
    ENV_CALLER,
    FLOW_USER,
    GMAIL_SA,
    GOOGLE_ISSUER,
    MON_0330Z,
    SCHEDULE_SA,
    WEEK,
    SchedApi,
    bearer,
)
from tilo_harness.schedule import StartSkipped, next_slot
from tilo_harness.schedule_store import MAX_FAILURES


@pytest.fixture
def sched(clear_flow, monkeypatch) -> SchedApi:
    rig = SchedApi(clear_flow, monkeypatch)
    rig.clock.set(MON_0330Z)
    return rig


class Counting:
    """A factory (`() -> value`) that counts how often the route asked for it."""

    def __init__(self, value: Any) -> None:
        self.value, self.calls = value, 0

    def __call__(self) -> Any:
        self.calls += 1
        return self.value


class Counters:
    def __init__(self, rig: SchedApi) -> None:
        from tilo_api import schedules

        self.seams, self.store = Counting(None), Counting(rig.schedules)  # None seams: nothing due can start anyway
        overrides = rig.app.dependency_overrides
        overrides[schedules.get_seams_factory] = lambda: self.seams
        overrides[schedules.get_schedule_store_factory] = lambda: self.store

    def both(self) -> tuple[int, int]:
        return self.seams.calls, self.store.calls


@pytest.fixture
def counters(sched: SchedApi) -> Counters:
    return Counters(sched)


# --- 1. lazy seams after auth ---------------------------------------------------------------------------------------

REFUSED = [
    pytest.param({}, 401, id="no token"),
    pytest.param({"Authorization": "Bearer"}, 401, id="empty bearer"),
    pytest.param({"Authorization": "Basic abc"}, 401, id="not a bearer"),
    pytest.param({"Authorization": "Bearer tok-forged"}, 401, id="a token the verifier refuses"),
]


@pytest.mark.parametrize(("headers", "status"), REFUSED)
def test_FR_AGT_14_an_anonymous_or_forged_call_builds_neither_the_seams_nor_the_store(
    sched: SchedApi, counters: Counters, headers: dict[str, str], status: int
) -> None:
    assert sched.tick(headers=headers).status_code == status
    assert counters.both() == (0, 0)


WRONG = [
    pytest.param({"iss": "https://evil.example.com"}, id="wrong issuer"),
    pytest.param({"iss": "accounts.google.com.evil.test"}, id="look-alike issuer"),
    pytest.param({"aud": "https://tilo-harness-abc123-as.a.run.app"}, id="wrong audience"),
    pytest.param({"aud": [AUDIENCE]}, id="audience is a list"),
    pytest.param({"email": GMAIL_SA}, id="wrong service account"),
    pytest.param({"email": API_SA}, id="tilo-api itself"),
    pytest.param({"email": "someone@example.com"}, id="a person"),
    pytest.param({"email_verified": False}, id="unverified email"),
    pytest.param({"drop": ("iss",)}, id="no issuer"),
]


@pytest.mark.parametrize("claims", WRONG)
def test_FR_AGT_14_a_verified_token_of_the_wrong_caller_builds_neither_the_seams_nor_the_store(
    sched: SchedApi, counters: Counters, claims: dict[str, Any]
) -> None:
    token = sched.verifier.register(**{"email": SCHEDULE_SA, "iss": GOOGLE_ISSUER, **claims})
    assert sched.tick(token).status_code in (401, 403)
    assert counters.both() == (0, 0)


def test_FR_AGT_14_a_good_token_resolves_the_seams_and_the_store_once_each(sched: SchedApi, counters: Counters) -> None:
    response = sched.tick()
    assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert counters.both() == (1, 1)
    assert sched.tick().status_code == 200
    assert counters.both() == (2, 2)  # once per request: never cached across requests


@pytest.mark.parametrize("unset", [(ENV_AUDIENCE,), (ENV_CALLER,), (ENV_AUDIENCE, ENV_CALLER)])
def test_FR_AGT_14_unconfigured_is_still_503_before_the_token_and_before_anything_is_built(
    sched: SchedApi, counters: Counters, monkeypatch: pytest.MonkeyPatch, unset: tuple[str, ...]
) -> None:
    for name in unset:
        monkeypatch.delenv(name)
    for headers in ({}, bearer(sched.good_token), bearer("tok-anything")):
        assert sched.tick(headers=headers).status_code == 503
    assert counters.both() == (0, 0)
    assert sched.verifier.calls == []


def test_FR_AGT_14_a_factory_that_fails_after_auth_fails_closed_with_a_fixed_body(
    sched: SchedApi, counters: Counters
) -> None:
    from tilo_api import schedules

    def broken() -> Any:
        raise RuntimeError("secret detail for alice@example.com: password hunter2")

    sched.app.dependency_overrides[schedules.get_schedule_store_factory] = lambda: broken
    response = sched.tick()
    assert 500 <= response.status_code < 600
    for leaked in ("hunter2", "alice", "secret detail", "Traceback"):
        assert leaked not in response.text


def test_FR_AGT_14_with_the_default_factories_an_unconfigured_store_is_503_for_the_right_caller(
    sched: SchedApi,
) -> None:
    """Without the counting factories the real default ones still honour `get_schedule_store` (overridden by the rig),
    and answer 503 when that override is gone and no store is configured."""
    from tilo_api import schedules

    assert sched.tick().status_code == 200  # the rig's in-memory store, through the default factory
    del sched.app.dependency_overrides[schedules.get_schedule_store]
    getattr(schedules.get_schedule_store, "cache_clear", lambda: None)()
    response = sched.tick()
    assert response.status_code == 503 and "Traceback" not in response.text


# --- 2. a disabled owner's schedules never fire ---------------------------------------------------------------------


def test_FR_AGT_14_a_disabled_owners_due_schedule_starts_nothing_through_the_tick(sched: SchedApi) -> None:
    task = sched.approved_task()
    sched.insert(task, "sched_a")
    worlds = set(sched.store.worlds)
    assert sched.schedules.disable_for_owner(FLOW_USER) == 1
    record = sched.schedules.get("sched_a")
    assert (record.enabled, record.last_error, record.next_due) == (False, "owner_disabled", MON_0330Z)
    for minutes in (0, 1, 5):
        sched.clock.set(MON_0330Z + timedelta(minutes=minutes))
        response = sched.tick()
        assert (response.status_code, response.json()) == (200, {"fired": 0})
    assert set(sched.store.worlds) == worlds, "a world was created for a disabled owner"
    assert sched.schedules.get("sched_a").failures == 0


# --- 3. run_seams_unwired does not count ----------------------------------------------------------------------------


def test_FR_AGT_14_the_starter_with_no_seams_raises_the_uncounted_skip_and_creates_nothing(sched: SchedApi) -> None:
    from tilo_harness.schedule import RunStart, slot_key

    task = sched.approved_task()
    record = sched.insert(task, "sched_a")
    worlds = set(sched.store.worlds)
    run = RunStart(
        idempotency_key=slot_key("sched_a", MON_0330Z), schedule_id="sched_a", owner_user_id=record.owner_user_id,
        title=record.title, approved_brief_ref=record.approved_brief_ref, prior_world_id=None,
        budget_cap=record.budget_cap, slot=MON_0330Z, skipped=0, cache_namespace="sched_a",
    )  # fmt: skip
    with pytest.raises(StartSkipped) as caught:
        sched.starter(seams=None).start(run)
    assert (caught.value.code, caught.value.count) == ("run_seams_unwired", False)
    assert set(sched.store.worlds) == worlds


# (FR-AGT-14e retired `..._through_the_tick_unwired_seams_never_count_against_a_schedule`: the tick no longer runs
# anything, so unwired seams are met by the task's delivery; `test_FR_AGT_14e_unwired_run_seams_are_retryable_...`.)


# --- 4. PATCH enabled:true moves a stale next_due -------------------------------------------------------------------


def test_FR_AGT_14_patching_a_long_paused_schedule_on_again_moves_next_due_to_the_next_slot(sched: SchedApi) -> None:
    sid = sched.created(sched.approved_task())["schedule_id"]
    assert sched.schedules.get(sid).next_due == MON_0330Z + WEEK
    assert sched.patch(sid, enabled=False).json()["enabled"] is False
    sched.clock.set(MON_0330Z + 3 * WEEK + timedelta(days=2, hours=5))  # the slot of week 1 is two weeks stale
    on = sched.patch(sid, enabled=True)
    assert on.status_code == 200, on.text
    expected = next_slot(sched.schedules.get(sid).cadence, sched.clock())
    assert expected == MON_0330Z + 4 * WEEK
    view = on.json()
    assert (view["enabled"], view["failures"], view["last_error"]) == (True, 0, None)
    assert view["next_due"] == "2026-11-02T03:30:00Z"
    assert sched.get(sid).json()["next_due"] == view["next_due"]
    assert sched.schedules.get(sid).next_due == expected
    assert sched.tick().json() == {"fired": 0}  # no catch-up run for the long-past slot


def test_FR_AGT_14_patching_on_again_leaves_a_next_due_that_is_still_in_the_future(sched: SchedApi) -> None:
    sid = sched.created(sched.approved_task())["schedule_id"]
    sched.patch(sid, enabled=False)
    sched.clock.advance(timedelta(days=1))
    assert sched.patch(sid, enabled=True).json()["next_due"] == "2026-10-12T03:30:00Z"


def test_FR_AGT_14_a_pause_and_a_rename_do_not_move_next_due(sched: SchedApi) -> None:
    sid = sched.created(sched.approved_task())["schedule_id"]
    sched.clock.set(MON_0330Z + 3 * WEEK)
    for body in ({"enabled": False}, {"title": "Renamed"}):
        assert sched.patch(sid, **body).json()["next_due"] == "2026-10-12T03:30:00Z"


def test_FR_AGT_14_auto_disabled_by_failures_then_patched_on_does_not_catch_up(sched: SchedApi) -> None:
    sid = sched.created(sched.approved_task())["schedule_id"]
    due = sched.schedules.get(sid).next_due
    sched.clock.set(due)
    for _ in range(MAX_FAILURES):
        assert sched.schedules.claim(sid, due) is True
        sched.schedules.record_failure(sid, due, error="start_failed")
        assert sched.schedules.get(sid).next_due == due
        sched.clock.advance(timedelta(days=2))
    assert sched.schedules.get(sid).enabled is False
    sched.clock.set(due + 5 * WEEK + timedelta(hours=1))
    on = sched.patch(sid, enabled=True).json()
    assert (on["enabled"], on["failures"], on["last_error"]) == (True, 0, None)
    assert on["next_due"] == "2026-11-23T03:30:00Z" and sched.tick().json() == {"fired": 0}
