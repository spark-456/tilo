"""FR-MTR-04 (PRD 14.5, 14.1): caps and demo spend defaults, all from config. config/metering.yaml
doesn't exist yet (S0 owns config/, CC-SE #7), so the demo-defaults test loads the local stub."""

import pytest
from _metering_testlib import METERING_STUB, metering_config, write_yaml
from tilo_metering import MeteringConfig, MeteringConfigError


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
