"""BQ-01 (docs/open-questions.md, ticket P0-02 section 1 common.schema.json
`authz`).

The PRD 9.3 table cell describing `authz` was cut off by a Markdown export;
`docs/open-questions.md` records the resolved default: "`authz: {by: "person"
| "policy" | "team_lead", ref: string, at: RFC 3339}` from PRD 10.4 'Audit'
and the glossary."

Ticket's rule test: "authz requires by (person, policy or team_lead), ref and
at."
"""

from __future__ import annotations

import copy

import pytest
from _lib import SCHEMA_ID_TEMPLATE, errors_for, load_schema

COMMON_ID = SCHEMA_ID_TEMPLATE.format(name="common")
AUTHZ_REF = {"$ref": f"{COMMON_ID}#/$defs/authz"}

A_VALID_AUTHZ = {
    "by": "person",
    "ref": "u_owner",
    "at": "2026-09-25T12:00:00.000Z",
}


def test_BQ_01_authz_with_all_three_fields_is_valid(repo_root, registry):
    load_schema(repo_root, "common")
    errors = errors_for(AUTHZ_REF, A_VALID_AUTHZ, registry)
    assert not errors, f"BQ-01: a complete authz object should validate, got: {[e.message for e in errors]}"


@pytest.mark.parametrize("by_value", ["person", "policy", "team_lead"])
def test_BQ_01_authz_by_accepts_person_policy_or_team_lead(repo_root, registry, by_value):
    load_schema(repo_root, "common")
    instance = {**A_VALID_AUTHZ, "by": by_value}
    errors = errors_for(AUTHZ_REF, instance, registry)
    assert not errors, f"BQ-01: authz.by must accept {by_value!r}, got: {[e.message for e in errors]}"


def test_BQ_01_authz_by_rejects_unknown_value(repo_root, registry):
    load_schema(repo_root, "common")
    instance = {**A_VALID_AUTHZ, "by": "the_model_itself"}
    errors = errors_for(AUTHZ_REF, instance, registry)
    assert errors, "BQ-01: authz.by must reject a value other than person/policy/team_lead"


@pytest.mark.parametrize("field", ["by", "ref", "at"])
def test_BQ_01_authz_missing_required_field_is_invalid(repo_root, registry, field):
    load_schema(repo_root, "common")
    instance = copy.deepcopy(A_VALID_AUTHZ)
    del instance[field]
    errors = errors_for(AUTHZ_REF, instance, registry)
    assert errors, f"BQ-01: authz missing {field!r} must be invalid (by, ref and at are all required)"
