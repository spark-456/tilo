"""FR-MEM-08 (PRD 13.2, 13.5, 15.1; GitHub issue #4 section 1, `spark-456/tilo`, ticket CC-SH).

PRD 13.2 Records: "Decision and policy log | Every answer, policy change and automated action
with `authz` | Firestore plus BigQuery | Append-only." PRD 13.5 acceptance test: "Audit query
returns the authoriser for 100% of side effects."

Issue #4 makes the Decision entity (PRD 15.1: "question, answer, answered by, scope, expiry")
carry `answered_by` as the `authz` shape (BQ-01, `contracts/common.schema.json`), but narrower
than the general shape: "`by` is `person` or `team_lead` only, never `policy` or a model." A
Decision is always a person's or a Team Lead's own answer (PRD 8.3: "Team Leads... a security
question reaches the Security Team Lead"); a policy never answers a question (root CLAUDE.md:
"A model never decides authorisation" -- and a policy is not who *answered*, only what may
*authorise a side effect* elsewhere, so it has no place here either) and cannot be cited as
"the person or Team Lead who told us this."

This is the same `decision.schema.json` ticket adds under FR-AGT-07 -- this file only exercises
its `answered_by` field from the audit angle, complementing
`test_FR_AGT_07_decision_and_repeat_questions.py`'s schema-shape coverage. Test-writer split:
`contracts/decision.schema.json` does not exist yet, so every test here must fail for that
reason.
"""

from __future__ import annotations

import pytest
from _cc_sh_lib import sample_authz, sample_decision
from _lib import errors_for, load_schema


def test_FR_MEM_08_decision_answered_by_is_required(repo_root, registry):
    """Every automated 'answered from a decision' event must trace to an authoriser --
    a decision without one breaks the audit query FR-MEM-08 needs."""
    schema = load_schema(repo_root, "decision")
    instance = sample_decision()
    del instance["answered_by"]
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-08: a decision without answered_by must be invalid"


def test_FR_MEM_08_decision_answered_by_carries_by_ref_and_at(repo_root, registry):
    """The audit query needs by (who kind), ref (which one) and at (when) on every decision,
    matching common.schema.json#/$defs/authz (BQ-01)."""
    schema = load_schema(repo_root, "decision")
    for field in ("by", "ref", "at"):
        instance = sample_decision()
        del instance["answered_by"][field]
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MEM-08: decision.answered_by missing {field!r} must be invalid"


@pytest.mark.parametrize(
    "by,ref,person",
    # A Team Lead's answer also names the person who held the Team Lead id (DC-02, DC-04).
    [("person", "u_owner", {}), ("team_lead", "tl_security", {"user": "u_security_lead"})],
)
def test_FR_MEM_08_decision_answered_by_accepts_person_and_team_lead(repo_root, registry, by, ref, person):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(answered_by=sample_authz(by=by, ref=ref, **person))
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-MEM-08: decision.answered_by by={by!r} should validate, got: {[e.message for e in errors][:5]}"
    )


def test_FR_MEM_08_decision_answered_by_rejects_policy(repo_root, registry):
    """Issue #4, verbatim: 'never policy or a model.' A policy authorises side effects
    elsewhere (outbox.schema.json), but it never *answers a question* -- only a person or a
    Team Lead does."""
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(answered_by=sample_authz(by="policy", ref="pol_autoreply"))
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-08: decision.answered_by.by='policy' must be invalid (issue #4)"


def test_FR_MEM_08_decision_answered_by_rejects_a_model(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(answered_by=sample_authz(by="the_model_itself", ref="fake-model-1"))
    errors = errors_for(schema, instance, registry)
    assert errors, (
        "FR-MEM-08: decision.answered_by.by must reject a model (root CLAUDE.md: 'A model never decides authorisation')"
    )


def test_FR_MEM_08_decision_answered_by_ref_matches_by_person(repo_root, registry):
    """BQ-01: ref must match by -- a person's decision names a user id, not a Team Lead id."""
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(answered_by=sample_authz(by="person", ref="tl_security"))
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-08: decision.answered_by by=person with a Team Lead ref (tl_...) must be invalid"


def test_FR_MEM_08_decision_answered_by_ref_matches_by_team_lead(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(answered_by=sample_authz(by="team_lead", ref="u_owner"))
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MEM-08: decision.answered_by by=team_lead with a user ref (u_...) must be invalid"
