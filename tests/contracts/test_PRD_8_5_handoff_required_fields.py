"""PRD 8.5 Context handoff protocol (ticket P0-02 section 1 handoff.schema.json).

"The note follows `handoff.schema.json`: goal, unit ids, done, in progress
(with artifact refs), decisions, open questions, next steps, verification to
re-run, gotchas." Ticket section 1 names the JSON keys directly: goal,
unit_ids, done, in_progress, decisions, open_questions, next_steps,
verification_to_rerun, gotchas -- "all required".

Ticket's rule test: "a handoff note missing any required field is invalid."
"""

from __future__ import annotations

import copy

import pytest
from _lib import errors_for, list_fixtures, load_json, load_schema

REQUIRED_FIELDS = (
    "goal",
    "unit_ids",
    "done",
    "in_progress",
    "decisions",
    "open_questions",
    "next_steps",
    "verification_to_rerun",
    "gotchas",
)


@pytest.fixture()
def a_valid_handoff(repo_root):
    fixtures = list_fixtures(repo_root, "handoff", "valid")
    assert fixtures, "PRD 8.5: need at least one contracts/fixtures/handoff/valid/*.json to mutate"
    instance = load_json(fixtures[0])
    for field in REQUIRED_FIELDS:
        assert field in instance, f"PRD 8.5: the valid handoff fixture {fixtures[0].name} is missing {field!r}"
    return instance


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_PRD_8_5_handoff_missing_required_field_is_invalid(repo_root, registry, a_valid_handoff, field):
    schema = load_schema(repo_root, "handoff")
    mutated = copy.deepcopy(a_valid_handoff)
    del mutated[field]
    errors = errors_for(schema, mutated, registry)
    assert errors, f"PRD 8.5: a handoff note missing {field!r} must be invalid against handoff.schema.json"


def test_PRD_8_5_handoff_with_every_required_field_is_valid(repo_root, registry, a_valid_handoff):
    schema = load_schema(repo_root, "handoff")
    errors = errors_for(schema, a_valid_handoff, registry)
    assert (
        not errors
    ), f"PRD 8.5: a handoff note with every required field present should validate, got: {[e.message for e in errors]}"
