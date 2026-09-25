"""FR-MTR-04 (PRD 14.5): "Per-run, per-user and per-org caps; hard cap
triggers the kill switch." PRD 14.1: "Caps. Per run, per user per day, and
per org per day, all from config. Demo defaults: 300 credits per public
run; US$15 soft and US$25 hard daily model spend on tilo-demo."

se-spec.md "## P8-01" fixes the acceptance tests verbatim (P8-01a keeps
only the two that need no Treasury; the reserve/cap-enforcement tests stay
on tests/P8-01 for P8-01b/c):
- the repo's demo defaults load;
- a config with daily_usd_hard < daily_usd_soft is rejected.

Note (undone, per se-spec.md section 0): config/metering.yaml does not
exist yet -- S0 owns config/ and lands it in contract batch CC-SE (issue
#7) -- so the demo-defaults test loads the local stub
packages/metering/tests/data/metering.stub.yaml, which carries the same
PRD 14.1/14.5 demo defaults the real file will.
"""

from __future__ import annotations

import pathlib

import pytest
from _metering_testlib import metering_config, write_metering_config
from tilo_metering import MeteringConfig, MeteringConfigError

_STUB_METERING_CONFIG = pathlib.Path(__file__).parent / "data" / "metering.stub.yaml"


def test_FR_MTR_04_repo_config_metering_yaml_has_the_demo_defaults():
    """The demo defaults named in PRD 14.1 / 14.5 and fixed by
    se-spec.md's "Config files (new)" section: 300 credits per public run,
    US$15 soft / US$25 hard daily model spend, a 15% reserve margin and an
    80% budget-request threshold."""
    config = MeteringConfig.load(_STUB_METERING_CONFIG)

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
