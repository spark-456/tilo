"""FR-AGT-12 (PRD 8.1): the Verifier "checks claims, numbers and formats independently of the author".

Independence is asserted four ways, all offline:
1. a separate call path: the Verifier reaches a model only through the `verifier` role's provider; the
   producer roles' providers receive no call, and a mapping without a `verifier` entry is refused
   (it never borrows the writer's or the specialist's provider);
2. a separate context: nothing that identifies the producer (agent id, skill, profile) is in any prompt
   the Verifier sends, and the author's own `verified` flag is not trusted;
3. a separate agent: the review is signed by a verifier-rank agent that is not the producer, and a
   Verifier asked to review its own work refuses;
4. the input is left alone: reviewing never mutates the author's manifest.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from agt_scripted import ScriptedProvider, all_prompt_text
from agt_verifier_support import (
    PRODUCER,
    PRODUCER_PROFILE,
    PRODUCER_SKILL,
    VERIFIER,
    build_manifest,
    claim,
    deliverable_of,
    make_verifier,
    note_for,
    snapshot,
    verifier_model,
)

TEXT_CLAIM = "Firm Qaa never moved its office."  # number-free: only the model can judge it


def _text_claim_deliverable(*, producer: str = PRODUCER, verified: bool = True):
    source = note_for(5)
    manifest = build_manifest(
        artifact_id="art_indep",
        sources={"src_a": source},
        claims=[claim("cl_1", TEXT_CLAIM, ["src_a"], verified=verified)],
        producer=producer,
    )
    return deliverable_of(manifest, {"src_a": source})


def test_FR_AGT_12_the_verifier_calls_only_the_verifier_role_provider() -> None:
    verifier_provider = verifier_model([])
    others = {
        role: ScriptedProvider(default=json.dumps({"verdict": "supported"}))
        for role in ("specialist", "writer", "lead", "director")
    }
    verifier, providers = make_verifier(verifier_provider, **others)

    review = asyncio.run(verifier.review(_text_claim_deliverable()))

    assert review.status["cl_1"] == "supported"
    assert verifier_provider.call_count >= 1, "a number-free claim needs the verifier model"
    for role, provider in others.items():
        assert provider.call_count == 0, f"independence: the {role} provider must not be called during verification"
    assert providers["verifier"] is verifier_provider


@pytest.mark.parametrize("fallback_role", ["writer", "specialist", "lead"])
def test_FR_AGT_12_without_a_verifier_provider_it_refuses_instead_of_borrowing_the_authors(fallback_role) -> None:
    from tilo_harness.verifier import Verifier

    borrowed = ScriptedProvider(default=json.dumps({"verdict": "supported"}))
    providers = {fallback_role: borrowed}

    with pytest.raises(Exception):  # noqa: B017, PT011 - the PRD names no exception type; any refusal at build or review
        verifier = Verifier(providers, agent_id=VERIFIER)
        asyncio.run(verifier.review(_text_claim_deliverable()))

    assert borrowed.call_count == 0, "the author's provider must never judge the author's claims"


def test_FR_AGT_12_no_prompt_names_the_producer_its_skill_or_its_profile() -> None:
    model = verifier_model([])
    verifier, _ = make_verifier(model)

    asyncio.run(verifier.review(_text_claim_deliverable()))

    seen = all_prompt_text(model)
    assert model.call_count >= 1
    assert TEXT_CLAIM in seen and "reported revenue of 45 million" in seen, (
        "the model is shown the claim and the evidence"
    )
    for leaked in (PRODUCER, PRODUCER_SKILL, PRODUCER_PROFILE):
        assert leaked not in seen, f"independence: the producer's {leaked!r} reached the Verifier's prompt"


def test_FR_AGT_12_the_authors_own_verified_flag_does_not_change_the_verdict() -> None:
    verdicts = {}
    for author_says in (True, False):
        verifier, _ = make_verifier(verifier_model([]))
        review = asyncio.run(verifier.review(_text_claim_deliverable(verified=author_says)))
        verdicts[author_says] = (review.result, dict(review.status))
    assert verdicts[True] == verdicts[False] == ("passed", {"cl_1": "supported"})


def test_FR_AGT_12_a_verifier_refuses_to_review_its_own_work() -> None:
    from tilo_harness.verifier import VerifierNotIndependent

    verifier, _ = make_verifier(verifier_model([]), agent_id=VERIFIER)
    own_work = _text_claim_deliverable(producer=VERIFIER)

    with pytest.raises(VerifierNotIndependent):
        asyncio.run(verifier.review(own_work))


def test_FR_AGT_12_reviewing_does_not_mutate_the_authors_manifest_or_sources() -> None:
    deliverable = _text_claim_deliverable(verified=True)
    manifest_before, sources_before = snapshot(deliverable.manifest), dict(deliverable.sources)
    verifier, _ = make_verifier(verifier_model([]))

    review = asyncio.run(verifier.review(deliverable))

    assert deliverable.manifest == manifest_before and dict(deliverable.sources) == sources_before
    assert review.manifest is not deliverable.manifest, "the recomputed manifest is a new document"


def test_FR_AGT_12_each_review_starts_from_nothing_no_state_carries_between_deliverables() -> None:
    """A lenient verdict on one deliverable must not leak into the next: reviewing the same wrong-number claim
    after a clean one still fails, in either order."""
    wrong = deliverable_of(
        build_manifest(
            artifact_id="art_wrong",
            sources={"src_a": note_for(5)},
            claims=[claim("cl_1", "Firm Qaa reported revenue of 905 million.", ["src_a"])],
        ),
        {"src_a": note_for(5)},
    )
    verifier, _ = make_verifier(verifier_model([]))
    first = asyncio.run(verifier.review(_text_claim_deliverable()))
    second = asyncio.run(verifier.review(wrong))
    third = asyncio.run(verifier.review(_text_claim_deliverable()))
    assert (first.result, second.result, third.result) == ("passed", "failed", "passed")
