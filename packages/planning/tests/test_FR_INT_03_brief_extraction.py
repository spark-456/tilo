"""FR-INT-03 (PRD 7.1): "The Director extracts a schema-valid brief: goal, deliverables,
audience, deadline, constraints, sources, sensitivity." Acceptance test: "Given 20 eval intakes,
then 100% of briefs validate against `brief.schema.json` and the user can edit every chip."

The eval harness (P8-06) owns the full 20-case set; this ticket exercises a handful of recorded
Director outputs standing in for it (ticket brief: "keep it to a handful here"). All model calls
go through `tilo_providers` (PL-01): a real `tilo_providers.router.Router` is built with
`_planning_contracts_lib.build_test_router`, wired to `ScriptedModelProvider` so no live call is
ever made (EFF-01) and the canned output comes from a fixture file under
`packages/planning/tests/fixtures/briefs/` (never inline in the test).

Public interface under test: `tilo_planning.brief.extract_brief`, `.edit_brief_field`,
`.BriefExtractionError`, `.ExtractionResult` -- this ticket's own design (`tilo_planning` does
not exist yet; see `_planning_contracts_lib.py` module docstring for why every import below fails
at collection with `ModuleNotFoundError` until the builder ships it).

Ambiguity resolved here (CLAUDE.md: PRD's stated default, logged in docs/open-questions.md):
BQ-12 -- `sensitivity` is one of `personal`, `business`, `public` (PRD 12.1 data classes).
"""

from __future__ import annotations

import json

import pytest
from _planning_contracts_lib import (
    ScriptedCall,
    ScriptedModelProvider,
    assert_valid_brief,
    build_test_router,
    load_brief_fixture,
)
from tilo_planning.brief import BriefExtractionError, edit_brief_field, extract_brief

_EVAL_INTAKE_FIXTURES = ["valid_pdf_report", "valid_market_scan", "valid_client_deck", "valid_minimal"]


@pytest.mark.parametrize("fixture_name", _EVAL_INTAKE_FIXTURES)
def test_FR_INT_03_extracted_brief_validates_for_every_eval_intake(repo_root, registry, tmp_path, fixture_name):
    canned = load_brief_fixture(fixture_name)
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps(canned))])
    router = build_test_router(tmp_path, provider)

    result = extract_brief("Some intake text and files.", router=router)

    assert_valid_brief(repo_root, registry, result.brief)
    assert result.brief["assumptions"] == []
    assert result.brief["applied_preferences"] == []
    assert result.ambiguous_fields == canned.get("ambiguous_fields", [])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("goal", "Prepare the revised Q3 report."),
        ("audience", "Board of directors"),
        ("deadline", "2026-11-01"),
        ("sensitivity", "personal"),
        ("constraints", ["Board-ready formatting only"]),
        ("deliverables", [{"title": "Board pack", "format": "pptx"}]),
        ("sources", [{"kind": "connector", "ref": "crm-salesforce", "label": "Salesforce CRM"}]),
    ],
)
def test_FR_INT_03_every_one_of_the_seven_chips_is_editable(repo_root, registry, tmp_path, field, value):
    canned = load_brief_fixture("valid_pdf_report")
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps(canned))])
    router = build_test_router(tmp_path, provider)
    result = extract_brief("Prepare the report.", router=router)

    edited = edit_brief_field(result.brief, field, value)

    assert edited[field] == value
    assert_valid_brief(repo_root, registry, edited)


def test_FR_INT_03_invalid_model_output_is_repaired_into_a_valid_brief(repo_root, registry, tmp_path):
    invalid = load_brief_fixture("invalid_missing_sensitivity")
    repaired = load_brief_fixture("repaired_vendor_memo")
    provider = ScriptedModelProvider(
        "large", [ScriptedCall(text=json.dumps(invalid)), ScriptedCall(text=json.dumps(repaired))]
    )
    router = build_test_router(tmp_path, provider)

    result = extract_brief("Draft the vendor renewal memo.", router=router)

    assert_valid_brief(repo_root, registry, result.brief)
    assert len(provider.calls) == 2, "FR-INT-03: an invalid extraction is retried once, not resubmitted blindly"


def test_FR_INT_03_model_output_still_invalid_after_repair_is_rejected_not_returned(tmp_path):
    invalid = load_brief_fixture("invalid_missing_sensitivity")
    provider = ScriptedModelProvider(
        "large", [ScriptedCall(text=json.dumps(invalid)), ScriptedCall(text=json.dumps(invalid))]
    )
    router = build_test_router(tmp_path, provider)

    with pytest.raises(BriefExtractionError):
        extract_brief("Draft the vendor renewal memo.", router=router)
