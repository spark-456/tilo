"""FR-MTR-04 (PRD 14.5): "Per-run, per-user and per-org caps; hard cap
triggers the kill switch" -- acceptance test: "Exceeding the demo hard cap
switches the link to replay-only." PRD 14.1: "Caps. Per run, per user per
day, and per org per day, all from config. Demo defaults: 300 credits per
public run; US$15 soft and US$25 hard daily model spend on tilo-demo, the
hard cap flipping the kill switch." PRD 17.2 NFR-24: "One flag switches the
public link to replay-only." PRD 13.4 "Emergency fallback": "The kill
switch puts the public link into replay-only mode."

se-spec.md "## P8-01" fixes the acceptance tests verbatim:
- the run, user-day and org-day caps each block a reservation;
- crossing the soft cap raises one alert per day;
- crossing the demo hard cap sets replay_only and returns Wait("replay_only")
  from then on;
- caps come from config/metering.yaml.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from _metering_testlib import REPO_ROOT, build_treasury, metering_config, write_metering_config
from tilo_metering import Alert, MeteringConfig, MeteringConfigError, Wait

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_FR_MTR_04_run_cap_blocks_a_reservation(tmp_path):
    """ "The effective cap is min(approved, caps.run_credits) when a run cap
    is set." approved (1000) is generous; config's run_credits (50) is the
    binding cap."""
    treasury, _flags = build_treasury(tmp_path, run_credits=50)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    assert treasury.run("r1").cap == pytest.approx(50.0)

    result = treasury.reserve("r1", "s1", estimate=60.0, at=AT)  # 60*1.15 = 69 > 50

    assert isinstance(result, Wait)
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(0.0)
    assert run.spent == pytest.approx(0.0)


def test_FR_MTR_04_user_day_cap_blocks_a_reservation_across_runs(tmp_path):
    """The user-day cap is shared across every run of that user (even in
    different orgs, whose own org cap is disabled here so only the user-day
    check is exercised)."""
    treasury, _flags = build_treasury(tmp_path, run_credits=1000, user_day_credits=100, org_day_credits=None)
    treasury.open_run("rA", user_id="u_capped", org_id="org_a", approved=1000)
    treasury.open_run("rB", user_id="u_capped", org_id="org_b", approved=1000)

    first = treasury.reserve("rA", "s1", estimate=50.0, at=AT)  # 57.5 reserved
    assert not isinstance(first, Wait)
    treasury.commit(first, actual=57.5, at=AT)

    second = treasury.reserve("rB", "s1", estimate=50.0, at=AT)  # 57.5 + 57.5 = 115 > 100

    assert isinstance(second, Wait)
    run_b = treasury.run("rB")
    assert run_b.reserved == pytest.approx(0.0)
    assert run_b.spent == pytest.approx(0.0)


def test_FR_MTR_04_org_day_cap_blocks_a_reservation_across_runs(tmp_path):
    """Symmetric to the user-day cap: the org-day cap is shared across
    every run of that org, across different users."""
    treasury, _flags = build_treasury(tmp_path, run_credits=1000, user_day_credits=None, org_day_credits=100)
    treasury.open_run("rA", user_id="u_a", org_id="org_capped", approved=1000)
    treasury.open_run("rB", user_id="u_b", org_id="org_capped", approved=1000)

    first = treasury.reserve("rA", "s1", estimate=50.0, at=AT)
    assert not isinstance(first, Wait)
    treasury.commit(first, actual=57.5, at=AT)

    second = treasury.reserve("rB", "s1", estimate=50.0, at=AT)

    assert isinstance(second, Wait)
    run_b = treasury.run("rB")
    assert run_b.reserved == pytest.approx(0.0)
    assert run_b.spent == pytest.approx(0.0)


def test_FR_MTR_04_crossing_the_soft_cap_raises_one_alert_per_day(tmp_path):
    """ "Crossing the soft cap raises one alert per day." credit_usd is
    0.005 (PRD 14.1), so a $1 daily_usd_soft is a 200-credit threshold."""
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
    """ "Crossing the demo hard cap sets replay_only and returns
    Wait("replay_only") from then on." (verbatim, se-spec.md). credit_usd
    0.005 makes a $1 daily_usd_hard a 200-credit threshold."""
    treasury, flags = build_treasury(
        tmp_path,
        run_credits=100_000,
        user_day_credits=None,
        org_day_credits=None,
        daily_usd_soft=1_000_000.0,
        daily_usd_hard=1.0,
    )
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=100_000)
    treasury.open_run("r2", user_id="u_02", org_id="org_02", approved=100_000)

    assert flags.get("replay_only") is False

    reservation = treasury.reserve("r1", "s1", estimate=200.0, at=AT)  # 230 reserved, well over $1
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
    """ "Caps come from config/metering.yaml." A temporary config with a
    5-credit run cap must be the binding cap even though approved is much
    larger, proving the cap is read from the file, not hard-coded."""
    treasury, _flags = build_treasury(tmp_path, run_credits=5)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)

    assert treasury.run("r1").cap == pytest.approx(5.0)


def test_FR_MTR_04_repo_config_metering_yaml_has_the_demo_defaults():
    """The demo defaults named in PRD 14.1 / 14.5 and fixed by
    se-spec.md's "Config files (new)" section: 300 credits per public run,
    US$15 soft / US$25 hard daily model spend, a 15% reserve margin and an
    80% budget-request threshold."""
    config = MeteringConfig.load(REPO_ROOT / "config" / "metering.yaml")

    assert config.caps.run_credits == 300
    assert config.caps.user_day_credits == 1500
    assert config.spend.daily_usd_soft == 15
    assert config.spend.daily_usd_hard == 25
    assert config.treasury.reserve_margin == pytest.approx(0.15)
    assert config.treasury.request_at == pytest.approx(0.80)


def test_FR_MTR_04_config_rejects_hard_cap_below_soft_cap(tmp_path):
    """MeteringConfig.load "rejects unknown keys, out-of-range values and
    daily_usd_hard < daily_usd_soft" -- a config that would make the kill
    switch weaker than the warning threshold must never load."""
    bad = metering_config(daily_usd_soft=25, daily_usd_hard=15)
    path = write_metering_config(tmp_path, bad)

    with pytest.raises(MeteringConfigError):
        MeteringConfig.load(path)
