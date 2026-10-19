"""FR-ACC-02: a skill's tool level can only lower the team level, never raise it (BQ-DSN-04)."""

import json
from pathlib import Path

import pytest
from tilo_policy.access_levels import Level, effective_level, parse_level, permits

PAIRS = json.loads((Path(__file__).parent / "fixtures" / "effective_level_pairs.json").read_text(encoding="utf-8"))


def test_FR_ACC_02_shared_fixture_matches_the_engine_for_every_pair():
    assert len(PAIRS["pairs"]) == 16
    for team, skill, expected in PAIRS["pairs"]:
        assert effective_level(Level(team), Level(skill)) == Level(expected)


@pytest.mark.parametrize("team", list(Level))
@pytest.mark.parametrize("skill", list(Level))
def test_FR_ACC_02_a_skill_level_above_the_team_level_never_raises_it(team, skill):
    eff = effective_level(team, skill)
    assert eff <= team and eff <= skill
    if skill > team:
        assert eff == team
        for tier in ("T0", "T1", "T2", "T3"):  # what the skill may do is what the team level allows
            assert permits(eff, tier) == permits(team, tier)


@pytest.mark.parametrize("team", list(Level))
def test_FR_ACC_02_no_skill_level_means_the_team_level(team):
    assert effective_level(team, None) == team


@pytest.mark.parametrize("bad", [2, 3, "act", True, 1.0])
def test_FR_ACC_02_a_non_level_skill_value_is_refused_not_clamped(bad):
    with pytest.raises(TypeError):
        effective_level(Level.ACT, bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        effective_level(bad, Level.READ)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["admin", "", "ACT ", None, 3])
def test_FR_ACC_02_a_tampered_skill_level_string_is_refused_by_parse(bad):
    with pytest.raises(ValueError):
        parse_level(bad)  # type: ignore[arg-type]
