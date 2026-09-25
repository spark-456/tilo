"""FR-MTR-04 (PRD 14.5, 14.1): run/user-day/org-day caps and demo spend defaults, from config
(local stub, CC-SE #7). Daily USD caps and the kill switch are P8-01c."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from _metering_testlib import METERING_STUB, build_treasury, metering_config, write_yaml
from tilo_metering import MeteringConfig, MeteringConfigError, Reservation, Wait

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
