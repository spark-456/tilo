"""FR-AGT-12 (PRD 8.1, 8.6): "Independent Verifier on every deliverable. Planted false claims are
caught or marked unverified >= 90%."

Given 44 deliverables that each carry one planted false claim (a wrong number, an unavailable source,
a source edited after it was fetched, no source, an author-asserted `verified: true`, and false
statements only the model can judge, two of which the scripted model wrongly approves), When the
Verifier reviews each, Then at least 90% end `contradicted` or `unverified` with the claim's `verified`
flag False (here 42 of 44, 95.5%), the rule-decidable kinds are caught every time (a lenient verifier
model cannot rescue them), and 20 true deliverables are still passed so the rate is not bought by
marking everything unverified.

The Verifier's model is scripted (record-and-replay, EFF-01): no network, no paid call.
Interface and judging order: agt_verifier_support.py (BQ-200).
"""

from __future__ import annotations

import asyncio
from collections import Counter

from agt_verifier_support import make_verifier, planted_false_cases, true_cases, verifier_model


def _review_all(cases):
    model = verifier_model(cases)
    verifier, _providers = make_verifier(model)
    return {case.case_id: asyncio.run(verifier.review(case.deliverable)) for case in cases}, model


def _caught(case, review) -> bool:
    claim_row = next(c for c in review.manifest["claims"] if c["id"] == case.claim_id)
    return review.status[case.claim_id] in ("contradicted", "unverified") and claim_row["verified"] is False


def test_FR_AGT_12_the_planted_set_is_big_enough_and_mixes_every_kind() -> None:
    cases = planted_false_cases()
    assert len(cases) >= 40
    assert all(case.planted_false for case in cases)
    assert set(Counter(case.kind for case in cases)) == {
        "number_mismatch",
        "unknown_source",
        "fingerprint_mismatch",
        "no_sources",
        "self_verified_lie",
        "textual_contradicted",
        "model_lapse",
        "model_wrong",
    }


def test_FR_AGT_12_planted_false_claims_are_caught_or_marked_unverified_at_least_90_percent() -> None:
    cases = planted_false_cases()
    reviews, model = _review_all(cases)

    caught = [case for case in cases if _caught(case, reviews[case.case_id])]
    rate = len(caught) / len(cases)
    missed = sorted(f"{c.case_id}:{c.kind}:{reviews[c.case_id].status[c.claim_id]}" for c in cases if c not in caught)
    assert rate >= 0.90, (
        f"FR-AGT-12: caught or marked unverified {len(caught)} of {len(cases)} ({rate:.1%}); missed {missed}"
    )
    assert model.misses == [], "the Verifier sent the model a prompt the recording does not know"


def test_FR_AGT_12_every_claim_the_rules_can_decide_is_caught_even_by_a_lenient_model() -> None:
    cases = planted_false_cases()
    reviews, _model = _review_all(cases)

    missed_kinds = {case.kind for case in cases if not _caught(case, reviews[case.case_id])}
    assert missed_kinds <= {"model_wrong"}, f"only a wrong model verdict may slip through, missed kinds: {missed_kinds}"

    by_kind = {
        kind: {reviews[c.case_id].status[c.claim_id] for c in cases if c.kind == kind}
        for kind in {c.kind for c in cases}
    }
    assert by_kind["number_mismatch"] == {"contradicted"}
    assert by_kind["self_verified_lie"] == {"contradicted"}, "the author's own verified: true is never trusted"
    assert by_kind["unknown_source"] == {"unverified"}
    assert by_kind["fingerprint_mismatch"] == {"unverified"}, (
        "text that no longer matches its fingerprint proves nothing"
    )
    assert by_kind["no_sources"] == {"unverified"}
    assert by_kind["textual_contradicted"] == {"contradicted"}
    assert by_kind["model_lapse"] == {"unverified"}, "a model that fails or rambles marks the claim unverified"


def test_FR_AGT_12_the_deliverable_result_follows_its_claims() -> None:
    cases = planted_false_cases()
    reviews, _model = _review_all(cases)
    expected = {
        "number_mismatch": "failed",
        "self_verified_lie": "failed",
        "textual_contradicted": "failed",
        "unknown_source": "unverified",
        "fingerprint_mismatch": "unverified",
        "no_sources": "unverified",
        "model_lapse": "unverified",
    }
    for case in cases:
        if case.kind in expected:
            assert reviews[case.case_id].result == expected[case.kind], f"{case.case_id} ({case.kind})"


def test_FR_AGT_12_true_deliverables_are_passed_so_marking_everything_unverified_does_not_pass() -> None:
    cases = true_cases()
    reviews, model = _review_all(cases)
    assert len(cases) == 20
    for case in cases:
        review = reviews[case.case_id]
        assert review.result == "passed", f"{case.case_id} ({case.kind}) was {review.result}: {review.status}"
        assert review.status[case.claim_id] == "supported"
        assert next(c for c in review.manifest["claims"] if c["id"] == case.claim_id)["verified"] is True
    assert model.misses == []


def test_FR_AGT_12_a_mixed_deliverable_flips_only_the_false_claim_and_fails() -> None:
    from agt_verifier_support import build_manifest, claim, deliverable_of, note_for

    source = note_for(7)
    manifest = build_manifest(
        artifact_id="art_mixed",
        sources={"src_a": source},
        claims=[
            claim("cl_ok1", "Firm Haa reported revenue of 47 million.", ["src_a"], verified=True),
            claim("cl_bad", "Firm Haa reported revenue of 947 million.", ["src_a"], verified=True),
            claim("cl_ok2", "Firm Haa moved its office in March.", ["src_a"], verified=False),
        ],
    )
    verifier, _ = make_verifier(verifier_model([]))

    review = asyncio.run(verifier.review(deliverable_of(manifest, {"src_a": source})))

    assert review.result == "failed"
    assert review.status == {"cl_ok1": "supported", "cl_bad": "contradicted", "cl_ok2": "supported"}
    assert [(c["id"], c["verified"]) for c in review.manifest["claims"]] == [
        ("cl_ok1", True),
        ("cl_bad", False),
        ("cl_ok2", True),
    ], "ids and order kept; verified recomputed, including the author's wrong True"
