"""FR-WLD-03 (PRD 10.4, 11.4, HR-7), and every PI row `docs/security/p4-policy-invariants.md`
marks "engine; validator": tilo_policy.check_entry(case) must reach the same verdict as each
file's own `rule` field for every case in contracts/fixtures/outbox/crossref/{valid,invalid}/ —
the same fixtures tests/contracts/test_FR_WLD_03_outbox_crossref.py's reference check (`broken`)
runs. This is the engine half of that reference check: one call per fixture file, parametrized
over every file so a new fixture is covered automatically.
"""

from __future__ import annotations

import pytest
import tilo_policy


def test_FR_WLD_03_every_valid_crossref_case_passes(crossref_valid_cases):
    assert crossref_valid_cases, "contracts/fixtures/outbox/crossref/valid/ must hold at least one case"


def test_FR_WLD_03_every_invalid_crossref_case_names_a_rule(crossref_invalid_cases):
    assert crossref_invalid_cases, "contracts/fixtures/outbox/crossref/invalid/ must hold at least one case"
    for name, case in crossref_invalid_cases:
        assert case["rule"] in ("OB-01", "OB-05"), f"{name}: unexpected rule {case['rule']!r}"


def test_FR_WLD_03_PI_06_check_entry_matches_every_fixtures_own_rule(crossref_valid_cases, crossref_invalid_cases):
    cases = crossref_valid_cases + crossref_invalid_cases
    assert cases, "no crossref fixtures found"
    mismatched = []
    for name, case in cases:
        verdict = tilo_policy.check_entry(case)
        if verdict != case["rule"]:
            mismatched.append((name, case["rule"], verdict))
    assert not mismatched, f"check_entry disagreed with the fixture's own rule: {mismatched}"


@pytest.mark.parametrize(
    "name",
    [
        "gate_reply_sent_in_village_basic.json",
        "gate_t3_reply_approved_by_assigned_approver_with_pin.json",
        "policy_l3_status_update_waiting.json",
        "policy_reply_instructed_on_the_web.json",
        "policy_reply_sent_after_undo_window.json",
        "policy_reply_sent_before_revocation.json",
        "policy_reply_waiting_out_undo_window.json",
        "team_lead_save_names_its_file.json",
    ],
)
def test_FR_WLD_03_PI_06_named_valid_case_passes(crossref_valid_cases, name):
    """Every valid/ file present today, named explicitly so a file removed by accident fails
    loudly instead of shrinking the parametrized set quietly."""
    by_name = dict(crossref_valid_cases)
    assert name in by_name, f"{name} is missing from contracts/fixtures/outbox/crossref/valid/"
    assert tilo_policy.check_entry(by_name[name]) is None
