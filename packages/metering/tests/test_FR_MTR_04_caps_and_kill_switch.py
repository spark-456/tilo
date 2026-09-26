"""FR-MTR-04 (PRD 14.5, 14.1): run/user-day/org-day caps and demo spend defaults, from config
(local stub, CC-SE #7). Daily USD caps and the kill switch are P8-01c."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from _metering_testlib import METERING_STUB, build_treasury, metering_config, write_yaml
from tilo_metering import Alert, MeteringConfig, MeteringConfigError, Reservation, Wait

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_FR_MTR_04_run_cap_blocks_a_reservation(tmp_path):
    treasury, _flags = build_treasury(tmp_path, run_credits=50)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    assert treasury.run("r1").cap == pytest.approx(50.0)  # min(approved, caps.run_credits)
    result = treasury.reserve("r1", "s1", estimate=60.0, at=AT)  # 60*1.15 = 69 > 50
    assert isinstance(result, Wait)
    assert treasury.run("r1").reserved == treasury.run("r1").spent == 0


@pytest.mark.parametrize(
    ("cap_kwarg", "shared_kwarg", "other_kwarg"),
    [("user_day_credits", "user_id", "org_id"), ("org_day_credits", "org_id", "user_id")],
)
def test_FR_MTR_04_day_cap_blocks_a_reservation_across_runs(tmp_path, cap_kwarg, shared_kwarg, other_kwarg):
    # the user-day (or org-day) cap is shared across every run of that user (or org)
    treasury, _flags = build_treasury(tmp_path, run_credits=1000, **{cap_kwarg: 100})
    treasury.open_run("rA", **{shared_kwarg: "shared", other_kwarg: "a"}, approved=1000)
    treasury.open_run("rB", **{shared_kwarg: "shared", other_kwarg: "b"}, approved=1000)
    first = treasury.reserve("rA", "s1", estimate=50.0, at=AT)  # 57.5 reserved
    assert not isinstance(first, Wait)
    treasury.commit(first, actual=57.5, at=AT)
    second = treasury.reserve("rB", "s1", estimate=50.0, at=AT)  # 57.5 + 57.5 = 115 > 100
    assert isinstance(second, Wait)
    assert treasury.run("rB").reserved == treasury.run("rB").spent == 0


def test_FR_MTR_04_day_caps_count_a_commit_on_its_reservations_utc_day_across_midnight(tmp_path):
    treasury, _flags = build_treasury(tmp_path, run_credits=1000, user_day_credits=100)
    for run_id in ("a", "b", "c"):
        treasury.open_run(run_id, user_id="u", org_id="o", approved=1000)
    midnight = datetime(2026, 9, 26, tzinfo=UTC)
    before = (midnight - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=8)))  # 07:59+08:00 = UTC 25th
    first = treasury.reserve("a", "s1", estimate=80 / 1.15, at=before)
    treasury.commit(first, actual=80.0, at=midnight + timedelta(seconds=40))  # counts on the 25th, not the 26th
    assert isinstance(treasury.reserve("b", "s1", estimate=80 / 1.15, at=midnight + timedelta(seconds=50)), Reservation)
    assert treasury.reserve("c", "s1", estimate=30 / 1.15, at=midnight - timedelta(seconds=30)) == Wait("user_day_cap")


def test_FR_MTR_04_repo_config_metering_yaml_has_the_demo_defaults():
    """PRD 14.1/14.5: 300 run credits, $15/$25 daily spend, 15% reserve margin, 80% budget-request threshold."""
    config = MeteringConfig.load(METERING_STUB)
    assert config.caps.run_credits == 300
    assert config.caps.user_day_credits == 1500
    assert config.spend.daily_usd_soft == 15
    assert config.spend.daily_usd_hard == 25
    assert config.treasury.reserve_margin == pytest.approx(0.15)
    assert config.treasury.request_at == pytest.approx(0.80)


def test_FR_MTR_04_config_rejects_hard_cap_below_soft_cap(tmp_path):
    """A kill switch weaker than the warning threshold must never load."""
    path = write_yaml(tmp_path, "metering.yaml", metering_config(daily_usd_soft=25, daily_usd_hard=15))
    with pytest.raises(MeteringConfigError):
        MeteringConfig.load(path)


# --- P8-01c: daily USD spend caps and the replay-only kill switch (brought back from tests/P8-01,
# unchanged in what they assert; test-writer's resolved ambiguities: none).


def test_FR_MTR_04_crossing_the_soft_cap_raises_one_alert_per_day(tmp_path):
    """Crossing the soft cap raises one alert per day. credit_usd is 0.005, so a $1 daily_usd_soft is
    a 200-credit threshold."""
    treasury, flags = build_treasury(
        tmp_path,
        run_credits=100_000,
        user_day_credits=None,
        org_day_credits=None,
        daily_usd_soft=1.0,
        daily_usd_hard=1_000_000.0,
    )
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=100_000)

    below = treasury.reserve("r1", "s1", estimate=150.0, at=AT)
    result_below = treasury.commit(below, actual=150.0, at=AT)  # day total 150 < 200
    assert not any(a.kind == "daily_spend_soft" for a in result_below.alerts)

    crossing = treasury.reserve("r1", "s2", estimate=100.0, at=AT)
    result_crossing = treasury.commit(crossing, actual=100.0, at=AT)  # day total 250 >= 200
    soft_alerts = [a for a in result_crossing.alerts if a.kind == "daily_spend_soft"]
    assert len(soft_alerts) == 1
    assert isinstance(soft_alerts[0], Alert)

    again = treasury.reserve("r1", "s3", estimate=50.0, at=AT)
    result_again = treasury.commit(again, actual=50.0, at=AT)  # still above threshold, same day
    assert not any(a.kind == "daily_spend_soft" for a in result_again.alerts), "at most one alert per day"

    assert flags.get("replay_only") is False


def test_FR_MTR_04_crossing_the_hard_cap_sets_replay_only_and_blocks_further_reserves(tmp_path):
    """Crossing the demo hard cap sets replay_only and returns Wait("replay_only") from then on
    (verbatim, se-spec.md). credit_usd 0.005 makes a $1 daily_usd_hard a 200-credit threshold.

    P8-01c also checks the hard cap pre-emptively in reserve() (a reservation that would itself cross
    it is refused before it is made -- see the new test below). So, unlike the original tests/P8-01
    version, the reservation here is sized to land exactly at the cap (not the 15%-margined estimate
    that would have been refused at reserve time): a genuine conflict between this ticket's two rules,
    fixed minimally by changing only this numeric setup, not any assertion.

    daily_usd_soft is 1.0 here, not the original tests/P8-01 value of 1_000_000.0: MeteringConfig
    now rejects daily_usd_hard < daily_usd_soft (added after that test was written), so soft can
    be at most 1.0 too. Soft and hard both fire on this commit; only hard_alerts is asserted."""
    treasury, flags = build_treasury(
        tmp_path,
        run_credits=100_000,
        user_day_credits=None,
        org_day_credits=None,
        daily_usd_soft=1.0,
        daily_usd_hard=1.0,
    )
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=100_000)
    treasury.open_run("r2", user_id="u_02", org_id="org_02", approved=100_000)

    assert flags.get("replay_only") is False

    reservation = treasury.reserve("r1", "s1", estimate=200.0 / 1.15, at=AT)  # 200 reserved credits = $1.00
    result = treasury.commit(reservation, actual=200.0, at=AT)  # day spend 200 credits = $1.00

    hard_alerts = [a for a in result.alerts if a.kind == "daily_spend_hard"]
    assert len(hard_alerts) == 1
    assert flags.get("replay_only") is True
    assert flags.history("replay_only"), "the flip must be recorded in the flag's history"

    blocked_same_run = treasury.reserve("r1", "s2", estimate=1.0, at=AT)
    blocked_other_run = treasury.reserve("r2", "s1", estimate=1.0, at=AT)

    assert isinstance(blocked_same_run, Wait)
    assert blocked_same_run.reason == "replay_only"
    assert isinstance(blocked_other_run, Wait)
    assert blocked_other_run.reason == "replay_only"


def test_FR_MTR_04_caps_come_from_config_metering_yaml(tmp_path):
    """A temporary config with a 5-credit run cap must be the binding cap even though approved is much
    larger, proving the cap is read from the file, not hard-coded."""
    treasury, _flags = build_treasury(tmp_path, run_credits=5)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)

    assert treasury.run("r1").cap == pytest.approx(5.0)


def test_FR_MTR_04_a_reservation_that_would_cross_the_hard_cap_is_refused_and_flips_replay_only(tmp_path):
    """New for P8-01c: "hard cap flips replay_only ... on commit and when a reservation would cross
    it, then every reserve returns Wait('replay_only')." Nothing has been committed yet, so only the
    reservation's own (margined) amount is being projected against the hard cap."""
    treasury, flags = build_treasury(
        tmp_path,
        run_credits=100_000,
        user_day_credits=None,
        org_day_credits=None,
        daily_usd_soft=1.0,
        daily_usd_hard=1.0,
    )
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=100_000)
    assert flags.get("replay_only") is False

    result = treasury.reserve("r1", "s1", estimate=200.0, at=AT)  # 230 credits reserved = $1.15 > $1.00

    assert isinstance(result, Wait)
    assert result.reason == "daily_spend_hard"
    assert flags.get("replay_only") is True
    assert flags.history("replay_only")
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(0.0)
    assert run.spent == pytest.approx(0.0)

    blocked = treasury.reserve("r1", "s2", estimate=1.0, at=AT)
    assert blocked == Wait("replay_only")


def test_FR_MTR_04_spend_alerts_and_kill_switch_count_committed_spend_not_open_reservations(tmp_path):
    """Alerts and replay_only follow the day's committed spend only: another run's open reservation is
    not money spent (credit_usd 0.005, so $0.50 soft = 100 credits, $1.00 hard = 200 credits)."""
    treasury, flags = build_treasury(
        tmp_path,
        run_credits=100_000,
        user_day_credits=None,
        org_day_credits=None,
        daily_usd_soft=0.5,
        daily_usd_hard=1.0,
    )
    treasury.open_run("big", user_id="u_01", org_id="org_01", approved=100_000)
    treasury.open_run("small", user_id="u_02", org_id="org_02", approved=100_000)
    held = treasury.reserve("big", "s1", estimate=198.0 / 1.15, at=AT)  # 198 credits held open
    small = treasury.reserve("small", "s1", estimate=1.0 / 1.15, at=AT)
    assert not isinstance(held, Wait) and not isinstance(small, Wait)

    result = treasury.commit(small, actual=1.0, at=AT)  # $0.005 committed today

    assert result.alerts == ()
    assert flags.get("replay_only") is False
