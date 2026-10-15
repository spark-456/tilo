"""SELF-SERVE-TEAMS (ADR-0044): self-join, self-serve teams and their leads.

`person` 1.1.0 adds two optional fields to a membership, `lead` and `accepted_at`; people.rules.md amends "Terms",
PE-17 and PE-20 and adds PE-37. `_teams_lib.team_permits` is the reference check for
`contracts/fixtures/person.membership/crossref/`. That folder is separate from `person/crossref` on purpose: the
`tilo_people` and `tilo-api` suites run every file of the latter, and keep their counts until the builder adds the
new actions; then they must reach the same verdicts on these files.
"""

from __future__ import annotations

import _people_lib as pl
import _teams_lib as tl
import pytest


def _cases(repo_root, kind):
    cases = tl.load_cases(repo_root, kind)
    assert cases, f"contracts/fixtures/person.membership/crossref/{kind}/ must hold at least one case"
    return cases


def test_SELF_SERVE_TEAMS_person_is_1_1_with_two_optional_membership_fields(repo_root):
    schema = pl.load_contract(repo_root, "person")
    assert tuple(map(int, schema["x-version"].split("."))) >= (1, 1, 0)
    membership = schema["$defs"]["membership"]
    assert membership["required"] == ["team", "assigned_by"], "old records stay valid: nothing new is required"
    assert set(membership["properties"]) == {"team", "assigned_by", "lead", "accepted_at"}
    assert membership["properties"]["lead"] == {"type": "boolean"}
    assert membership["additionalProperties"] is False


@pytest.mark.parametrize(
    "extra",
    [
        {"lead": "yes"},
        {"lead": None},
        {"lead": 1},
        {"accepted_at": "2026-10-15"},
        {"accepted_at": None},
        {"role": "lead"},
    ],
)
def test_SELF_SERVE_TEAMS_PE_02_membership_fields_are_closed(repo_root, registry, extra):
    entry = {"team": "tm_sales", "assigned_by": pl.assignment(), **extra}
    pl.assert_invalid(repo_root, registry, "person", pl.person(memberships=[entry]), why=str(extra))


def test_SELF_SERVE_TEAMS_PE_02_a_lead_and_an_accepted_entry_are_valid(repo_root, registry):
    lead = {"team": "tm_sales", "assigned_by": pl.assignment(), "lead": True}
    accepted = {"team": "tm_ops", "assigned_by": pl.assignment("u_riya"), "accepted_at": pl.T1}
    pl.assert_valid(repo_root, registry, "person", pl.person(memberships=[lead, accepted]))


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_SELF_SERVE_TEAMS_crossref_cases_are_shape_valid(repo_root, registry, kind):
    for path, case in _cases(repo_root, kind):
        found = tl.case_shape_problems(repo_root, registry, case)
        assert not found, f"{kind}/{path.name}: {found[:3]}"


def test_SELF_SERVE_TEAMS_every_valid_case_is_granted(repo_root):
    for path, case in _cases(repo_root, "valid"):
        assert case["rule"] is None, f"valid/{path.name}: rule must be null"
        assert tl.team_permits(case), f"valid/{path.name}: refused, must be granted: {case['note']}"


def test_SELF_SERVE_TEAMS_every_invalid_case_is_refused_and_named_after_its_rule(repo_root):
    for path, case in _cases(repo_root, "invalid"):
        assert case["rule"] in tl.RULES, f"invalid/{path.name}: rule must be one of {tl.RULES}"
        assert path.name.startswith(case["rule"].lower().replace("-", "") + "_"), f"invalid/{path.name}"
        assert not tl.team_permits(case), f"invalid/{path.name}: granted, must be refused: {case['note']}"


def test_SELF_SERVE_TEAMS_every_amended_rule_and_action_has_both_kinds_of_case(repo_root):
    invalid = [case for _, case in _cases(repo_root, "invalid")]
    valid = [case for _, case in _cases(repo_root, "valid")]
    assert {case["rule"] for case in invalid} == set(tl.RULES)
    for action in tl.NEEDS:
        assert any(c["request"]["action"] == action for c in valid), f"no valid case for {action}"
        assert any(c["request"]["action"] == action for c in invalid), f"no invalid case for {action}"


def test_SELF_SERVE_TEAMS_the_rules_and_the_adr_say_the_same(repo_root):
    rules = (pl.contracts_dir(repo_root) / "people.rules.md").read_text(encoding="utf-8")
    assert "| PE-37 |" in rules and "ADR-0044" in rules and "`accepted_at`" in rules
    adr = next((repo_root / "docs" / "adr").glob("0044-*.md")).read_text(encoding="utf-8")
    assert "approve contract change for self-serve teams" in adr, "the ADR records the owner's approval"
