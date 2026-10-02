"""Acceptance tests for eval set structure (PRD 19.2, EFF-07)."""

from collections import defaultdict

from conftest import REPO_ROOT
from tilo_evals import Case, EvalsConfig, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_CONFIG_PATH = REPO_ROOT / "config" / "evals.yaml"


def test_PRD_19_2_eval_set_structure_all_cases_load_and_respect_group_caps() -> None:
    config = EvalsConfig.load(str(_CONFIG_PATH))
    cases = load_cases(str(_CASES_DIR))
    assert len(cases) > 0

    by_group: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        by_group[case.group].append(case)

    for group, group_cases in by_group.items():
        assert group in config.groups, f"unknown group {group!r} not in config/evals.yaml"
        assert len(group_cases) <= config.groups[group], (
            f"group {group!r} has {len(group_cases)} cases, exceeding cap {config.groups[group]}"
        )


def test_PRD_19_2_eval_set_structure_ids_unique_and_contiguous_from_01() -> None:
    cases = load_cases(str(_CASES_DIR))
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids found"

    by_group: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        by_group[case.group].append(case.id)

    for group, group_ids in by_group.items():
        expected = [f"{group}-{i:02d}" for i in range(1, len(group_ids) + 1)]
        assert sorted(group_ids) == expected, f"group {group!r} ids have gaps or do not start at 01: {group_ids}"
