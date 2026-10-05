"""CC-PEOPLE: the people crossref cases, `contracts/fixtures/person/crossref/{valid,invalid}/`
(people.rules.md PE-01 to PE-07; PE-10 is covered by test_CC_PEOPLE_ui_action.py).

Each file is `{rule, note, now, persons, record, request}`. A valid file is a request the rules grant
(`rule` is null); each invalid file is a request they refuse and breaks the rule its `rule` field
and its name (`pe01_...`) state. `_people_lib.permits` is the reference oracle; the `tilo-api`
tests (CL-PEOPLE) must run the same files. Membership counts only when an org owner of the same org
assigned it no later than `now`.

Test-writer split: the folder does not exist yet, so each test fails with "must hold at least one
case".
"""

from __future__ import annotations

import _people_lib as pl
import pytest


def _cases(repo_root, kind):
    cases = pl.load_cases(repo_root, kind)
    assert cases, f"contracts/fixtures/person/crossref/{kind}/ must hold at least one case"
    return cases


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_CC_PEOPLE_PE_01_crossref_cases_are_shape_valid(repo_root, registry, kind):
    for path, case in _cases(repo_root, kind):
        found = pl.case_shape_problems(repo_root, registry, case)
        assert not found, f"{kind}/{path.name}: every part must be shape-valid, got {found[:3]}"


def test_CC_PEOPLE_PE_02_every_valid_case_is_a_request_the_rules_grant(repo_root):
    for path, case in _cases(repo_root, "valid"):
        assert case["rule"] is None, f"valid/{path.name}: rule must be null"
        assert pl.permits(case), f"valid/{path.name}: the rules refuse this request: {case['note']}"


def test_CC_PEOPLE_PE_03_every_invalid_case_is_refused_and_named_after_its_rule(repo_root):
    for path, case in _cases(repo_root, "invalid"):
        rule = case["rule"]
        assert rule in pl.RULES, f"invalid/{path.name}: rule must be one of {pl.RULES}"
        prefix = rule.lower().replace("-", "")
        assert path.name.startswith(f"{prefix}_"), f"invalid/{path.name} must start with {prefix}_"
        assert not pl.permits(case), f"invalid/{path.name}: the rules grant this request, it must be refused"


def test_CC_PEOPLE_PE_04_each_rule_from_pe_01_to_pe_07_has_an_invalid_case(repo_root):
    covered = {case["rule"] for _, case in _cases(repo_root, "invalid")}
    assert set(pl.RULES) <= covered, f"no invalid case for {sorted(set(pl.RULES) - covered)}"


@pytest.mark.parametrize("label", sorted(pl.REQUIRED_REFUSALS))
def test_CC_PEOPLE_PE_05_the_required_refusals_exist(repo_root, label):
    predicate = pl.REQUIRED_REFUSALS[label]
    hits = [path.name for path, case in _cases(repo_root, "invalid") if predicate(case)]
    assert hits, f"no invalid crossref case for: {label}"
