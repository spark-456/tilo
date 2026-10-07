"""FR-ACC-01 / BQ-DSN-04: Off / Read / Draft / Act per tool map to risk tiers; Act never passes the engine's ceiling."""

import pytest
from tilo_policy.access_levels import Level, effective_level, parse_level, permits

ALLOWED = {  # (level, tier, read_only) -> outcome; the BQ-DSN-04 default mapping
    ("off", "T0", True): "block",
    ("off", "T1", False): "block",
    ("off", "T3", False): "block",
    ("read", "T0", True): "allow",
    ("read", "T1", True): "allow",  # a read whose table tier is T1 (read_events) is still a read
    ("read", "T1", False): "block",
    ("read", "T2", False): "block",
    ("draft", "T0", True): "allow",
    ("draft", "T1", False): "allow",
    ("draft", "T2", False): "block",  # an external send is T2: not a draft
    ("draft", "T3", False): "block",
    ("act", "T1", False): "allow",
    ("act", "T2", False): "allow",
    ("act", "T3", False): "needs_person",
}


@pytest.mark.parametrize(("key", "outcome"), ALLOWED.items())
def test_FR_ACC_01_each_level_maps_to_a_tier_ceiling(key, outcome):
    level, tier, read_only = key
    assert permits(parse_level(level), tier, read_only=read_only) == outcome


def test_FR_ACC_01_act_never_auto_executes_t3():
    assert all(permits(lv, "T3") != "allow" for lv in Level)


@pytest.mark.parametrize("tier", ["T4", "", "t1", None, 1])
def test_FR_ACC_01_unknown_tier_is_blocked_at_every_level(tier):
    assert all(permits(lv, tier) == "block" for lv in Level)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["admin", "", "ACT ", None, 3])
def test_FR_ACC_01_unknown_level_is_refused(bad):
    with pytest.raises(ValueError):
        parse_level(bad)  # type: ignore[arg-type]


def test_FR_ACC_01_skill_level_can_only_restrict():
    levels = list(Level)
    for team in levels:
        assert effective_level(team, None) == team
        for skill in levels:
            got = effective_level(team, skill)
            assert got == min(team, skill) and got <= team
    assert effective_level(Level.READ, Level.ACT) == Level.READ
    assert effective_level(Level.ACT, Level.DRAFT) == Level.DRAFT
