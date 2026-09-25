"""FR-MTR-04 (PRD 14.5, 14.1): caps and demo spend defaults, all from config. config/metering.yaml
doesn't exist yet (S0 owns config/, CC-SE #7), so the demo-defaults test loads the local stub."""

from __future__ import annotations

import pathlib

import pytest
from _metering_testlib import metering_config, write_metering_config
from tilo_metering import MeteringConfig, MeteringConfigError

_STUB_METERING_CONFIG = pathlib.Path(__file__).parent / "data" / "metering.stub.yaml"


def test_FR_MTR_04_repo_config_metering_yaml_has_the_demo_defaults():
    """PRD 14.1/14.5 demo defaults: 300 run credits, $15/$25 daily spend,
    15% reserve margin, 80% budget-request threshold."""
    config = MeteringConfig.load(_STUB_METERING_CONFIG)

    assert config.caps.run_credits == 300
    assert config.caps.user_day_credits == 1500
    assert config.spend.daily_usd_soft == 15
    assert config.spend.daily_usd_hard == 25
    assert config.treasury.reserve_margin == pytest.approx(0.15)
    assert config.treasury.request_at == pytest.approx(0.80)


def test_FR_MTR_04_config_rejects_hard_cap_below_soft_cap(tmp_path):
    """A kill switch weaker than the warning threshold must never load."""
    bad = metering_config(daily_usd_soft=25, daily_usd_hard=15)
    path = write_metering_config(tmp_path, bad)

    with pytest.raises(MeteringConfigError):
        MeteringConfig.load(path)
