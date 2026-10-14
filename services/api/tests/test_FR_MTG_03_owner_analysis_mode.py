"""Owner request mode, trusted start and per-call spend; all providers are offline doubles."""

from types import SimpleNamespace

import pytest
from _ppl11a_lib import OWNER, SAM
from _sec16_lib import make_caps, make_ledger
from starlette.requests import Request
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from tilo_api import deps, spend, team_access
from tilo_api.people_writes import Refusal
from tilo_metering.flags import InMemoryFlagStore
from tilo_providers.safety import FakeSafetyProvider


@pytest.fixture
def owner_call(integration, monkeypatch):  # noqa: F811
    rig, writer, scope, router = integration
    stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
    rig.real.meetings.replace(
        {**stored.record, "scheduled": {"start": "2026-10-05T23:30:00.000Z", "end": "2026-10-06T00:30:00.000Z"}},
        expected_version=stored.version,
    )
    caps = make_caps()
    ledger = make_ledger(caps)
    flags = InMemoryFlagStore()
    switches = spend.Switches(flags, ledger)
    request = Request(
        {"type": "http", "app": SimpleNamespace(dependency_overrides={deps.get_spend_caps: lambda: caps})}
    )
    request.state.uid = OWNER
    request.state.declaration = "owner"
    monkeypatch.setattr(deps, "get_work_mode", lambda request, switches: "replay")
    monkeypatch.setattr(team_access, "user_cap_minor", lambda *args: caps.uid_lifetime_minor)
    modes = []
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: modes.append(("router", mode)) or router)
    monkeypatch.setattr(deps, "get_safety", lambda mode: modes.append(("safety", mode)) or FakeSafetyProvider())
    return SimpleNamespace(**locals())


def run(case):
    from tilo_api.meeting_analysis_mode import analyze_owner_minutes

    return analyze_owner_minutes(
        case.request,
        case.writer,
        case.rig.event_store,
        case.rig.artifacts,
        "mt_q4_plan",
        principal=deps.Principal(case.writer.actor, "owner"),
        switches=case.switches,
        budget=2,
        events=case.rig.events,
    )


def live(case, monkeypatch):
    monkeypatch.setattr(deps, "get_work_mode", lambda request, switches: "live")


def test_FR_MTG_03_owner_mode_replays_and_leaves_minutes_unconfirmed(owner_call):
    c = owner_call
    result = run(c)
    assert result["status"] == "minuted" and result["minutes_confirmed_by"] is None
    assert c.modes == [("router", "replay"), ("safety", "replay")]
    assert c.ledger.spent_minor(OWNER) == 0 and c.router.calls[0][2] == 2


@pytest.mark.parametrize("change", ["actor", "uid", "world", "missing_start", "future_start", "expired", "budget"])
def test_FR_MTG_03_owner_mode_refuses_before_mode_or_provider(owner_call, monkeypatch, change):
    c = owner_call
    if change == "actor":
        c.writer.actor = SAM
    elif change == "uid":
        c.request.state.uid = SAM
    elif change == "world":
        c.rig.event_store.worlds[c.scope.world_id].owner = SAM
    elif change == "expired":
        c.writer.now = c.rig.stored("meetings", "mt_q4_plan")["delete_transcript_after"]
    elif change == "budget":
        c.bad_budget = True
    else:
        stored = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
        scheduled = (
            None
            if change == "missing_start"
            else {"start": "2099-01-01T00:00:00.000Z", "end": "2099-01-01T01:00:00.000Z"}
        )
        c.rig.real.meetings.replace({**stored.record, "scheduled": scheduled}, expected_version=stored.version)
    monkeypatch.setattr(deps, "get_work_mode", lambda *args: pytest.fail("mode read before owner preflight"))
    before = c.rig.snapshot()
    with pytest.raises(Refusal):
        if change == "budget":
            from tilo_api.meeting_analysis_mode import analyze_owner_minutes

            analyze_owner_minutes(
                c.request,
                c.writer,
                c.rig.event_store,
                c.rig.artifacts,
                "mt_q4_plan",
                principal=deps.Principal(OWNER, "owner"),
                switches=c.switches,
                budget=float("nan"),
                events=c.rig.events,
            )
        else:
            run(c)
    assert not c.modes and not c.router.calls and c.rig.snapshot() == before


def test_FR_MTG_03_owner_demo_forces_replay_even_when_mode_seam_says_live(owner_call, monkeypatch):
    c = owner_call
    live(c, monkeypatch)
    from tilo_api.meeting_analysis_mode import analyze_owner_minutes

    analyze_owner_minutes(
        c.request,
        c.writer,
        c.rig.event_store,
        c.rig.artifacts,
        "mt_q4_plan",
        principal=deps.Principal(OWNER, "owner", demo_session=True),
        switches=c.switches,
        budget=2,
        events=c.rig.events,
    )
    assert c.modes == [("router", "replay"), ("safety", "replay")]
    assert c.ledger.spent_minor(OWNER) == 0


def test_FR_MTG_03_owner_live_reserves_each_safety_and_generation_call(owner_call, monkeypatch):
    c = owner_call
    live(c, monkeypatch)
    run(c)
    assert c.modes == [("router", "live"), ("safety", "live")]
    assert c.ledger.spent_minor(OWNER) == 2 * c.caps.unit_reserve_minor


@pytest.mark.parametrize("denial", ["unwired", "team", "team_error", "switch"])
def test_FR_MTG_03_owner_live_denial_never_reaches_provider(owner_call, monkeypatch, denial):
    c = owner_call
    live(c, monkeypatch)
    if denial == "unwired":
        c.switches = spend.Switches(c.flags, None)
    elif denial == "team":
        monkeypatch.setattr(team_access, "user_cap_minor", lambda *args: 0)
    elif denial == "team_error":

        def fail(*args):
            raise RuntimeError("untrusted data")

        monkeypatch.setattr(team_access, "user_cap_minor", fail)
    else:
        c.flags.set("replay_only", True, reason="test")
    before = c.rig.snapshot()
    with pytest.raises((deps.ReplayOnly, spend.SpendCapReached, Refusal)):
        run(c)
    assert not c.router.calls and c.ledger.spent_minor(OWNER) == 0 and c.rig.snapshot() == before


def test_FR_MTG_03_owner_switch_between_screen_and_generation_stops_generation(owner_call, monkeypatch):
    c = owner_call
    live(c, monkeypatch)

    class Safety:
        def check(self, text):
            c.flags.set("replay_only", True, reason="test")
            return {"flagged": False}

    monkeypatch.setattr(deps, "get_safety", lambda mode: Safety())
    with pytest.raises(Refusal):
        run(c)
    assert not c.router.calls and c.ledger.spent_minor(OWNER) == c.caps.unit_reserve_minor


def test_FR_MTG_03_owner_provider_error_stays_charged_without_publication(owner_call, monkeypatch):
    c = owner_call
    live(c, monkeypatch)

    def fail():
        raise RuntimeError("untrusted provider error")

    c.router.during = fail
    with pytest.raises(Refusal) as raised:
        run(c)
    assert raised.value.detail == "analysis_failed"
    assert c.ledger.spent_minor(OWNER) == 2 * c.caps.unit_reserve_minor
    assert c.rig.stored("meetings", "mt_q4_plan")["minutes"] is None


def test_FR_MTG_03_owner_verifier_uses_remaining_budget_and_another_hold(owner_call, monkeypatch):
    from test_FR_MTG_03_minutes_analysis import Script

    c = owner_call
    live(c, monkeypatch)
    c.router.doc["decisions"][0]["text"] = "The group chose to proceed."
    script = Script(c.router.doc, {"supported": [True]})
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: script)
    run(c)
    assert [call[0] for call in script.calls] == ["meeting_analyst", "verifier"]
    assert [call[2] for call in script.calls] == [2, 0.75]
    assert c.ledger.spent_minor(OWNER) == 3 * c.caps.unit_reserve_minor


def test_FR_MTG_03_owner_team_remaining_limit_blocks_second_call(owner_call, monkeypatch):
    c = owner_call
    live(c, monkeypatch)
    monkeypatch.setattr(team_access, "user_cap_minor", lambda *args: 150)
    with pytest.raises(Refusal):
        run(c)
    assert not c.router.calls and c.ledger.spent_minor(OWNER) == 100


def test_FR_MTG_03_owner_schedule_change_during_factory_refuses(owner_call, monkeypatch):
    c = owner_call

    def factory(mode):
        stored = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
        c.rig.real.meetings.replace({**stored.record, "title": "Changed"}, expected_version=stored.version)
        return c.router

    monkeypatch.setattr(deps, "router_for_mode", factory)
    with pytest.raises(Refusal) as raised:
        run(c)
    assert raised.value.detail == "version_conflict" and not c.router.calls
