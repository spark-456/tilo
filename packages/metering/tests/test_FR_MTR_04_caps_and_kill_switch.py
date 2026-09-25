"""FR-MTR-04 (PRD 14.5, 14.1): per-run, per-user and per-org caps, and demo spend defaults, all
from config. config/metering.yaml doesn't exist yet (S0 owns config/, CC-SE #7), so the
demo-defaults test loads the local stub. Daily USD spend caps and the kill switch are P8-01c."""

from datetime import UTC, datetime

import pytest
from _metering_testlib import METERING_STUB, build_treasury, metering_config, write_yaml
from tilo_metering import MeteringConfig, MeteringConfigError, Wait

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_FR_MTR_04_run_cap_blocks_a_reservation(tmp_path):
    """The effective cap is min(approved, caps.run_credits): approved (1000) is generous, so the
    config's run_credits (50) is the binding cap."""
    treasury, _flags = build_treasury(tmp_path, run_credits=50)
    treasury.open_run("r1", user_id="u_01", org_id="org_01", approved=1000)
    assert treasury.run("r1").cap == pytest.approx(50.0)
    result = treasury.reserve("r1", "s1", estimate=60.0, at=AT)  # 60*1.15 = 69 > 50
    assert isinstance(result, Wait)
    run = treasury.run("r1")
    assert run.reserved == pytest.approx(0.0)
    assert run.spent == pytest.approx(0.0)


def test_FR_MTR_04_user_day_cap_blocks_a_reservation_across_runs(tmp_path):
    """The user-day cap is shared across every run of that user, even in different orgs."""
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
    """Symmetric to the user-day cap: the org-day cap is shared across every run of that org."""
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
