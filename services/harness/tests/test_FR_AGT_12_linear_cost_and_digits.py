"""FR-AGT-12 hardening (PRD 8.1, 16.3): reviewing hostile source text costs time linear in its size and never
stalls the event loop, and a number written in any script's digits is read as the number it is. Written after
round 2 of the security review of #278; the acceptance tests are untouched.

NFKC is quadratic on a long run of combining marks (U+0F73 and the like): 30,000 of them took 7 s per pass.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from agt_scripted import ScriptedProvider
from agt_verifier_support import LENIENT, build_manifest, claim, deliverable_of, make_verifier
from tilo_harness import verifier as verifier_module
from tilo_harness.untrusted import has_long_mark_run, neutralise
from tilo_harness.validator import repo_validator

SIZE = 30_000
TRUE_CLAIM = "Firm Faa was founded by two friends."
BOUND_S = 10.0
MAX_GAP_S = 1.0


def _timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def test_FR_AGT_12_neutralise_is_linear_on_long_runs_of_combining_marks() -> None:
    for hostile in ("ཱི" * SIZE, "ཱི​" * (SIZE // 2), ("ཱི" * 25 + "​") * (SIZE // 26)):
        cleaned, took = _timed(lambda text=hostile: neutralise(text, limit=SIZE))
        assert took < 3.0, f"neutralise took {took:.1f} s"
        assert not has_long_mark_run(cleaned) and len(cleaned) <= SIZE


def test_FR_AGT_12_has_long_mark_run_counts_consecutive_marks_only() -> None:
    assert has_long_mark_run("a" + "́" * 31) and not has_long_mark_run("a" + "́" * 30)
    assert not has_long_mark_run("́a" * 100)


async def _review_with_heartbeat(verifier, deliverable):
    repo_validator().contract_problems("manifest", {})  # the one-time schema load is not what is measured
    gaps: list[float] = []
    stop = False

    async def beat() -> None:
        last = time.perf_counter()
        while not stop:
            await asyncio.sleep(0.02)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(beat())
    await asyncio.sleep(0)
    start = time.perf_counter()
    review = await verifier.review(deliverable)
    took = time.perf_counter() - start
    stop = True
    await task
    return review, took, max(gaps)


def _two_hundred_claims(source: str, *, claim_text: str = TRUE_CLAIM):
    claims = [claim(f"cl_{k}", claim_text, ["src_a"]) for k in range(200)]
    manifest = build_manifest(artifact_id="art_dos", sources={"src_a": source}, claims=claims)
    return deliverable_of(manifest, {"src_a": source})


def test_FR_AGT_12_a_source_of_combining_marks_is_refused_fast_for_every_claim_citing_it() -> None:
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)

    review, took, gap = asyncio.run(_review_with_heartbeat(verifier, _two_hundred_claims("ཱི" * SIZE)))

    assert took < BOUND_S and gap < MAX_GAP_S, (took, gap)
    assert review.result == "unverified" and set(review.status.values()) == {"unverified"}
    assert review.notes["cl_0"] == ["source src_a: holds a long run of combining characters"]
    assert model.call_count == 0


def test_FR_AGT_12_a_source_is_prepared_once_per_review_not_once_per_claim(monkeypatch) -> None:
    calls: list[int] = []
    real = verifier_module._prepare
    monkeypatch.setattr(verifier_module, "_prepare", lambda *a: calls.append(1) or real(*a))
    source = "Firm Faa was founded by two friends. " + ("ཱི​" * (SIZE // 2 - 20))
    source = source[:SIZE]
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)

    review, took, gap = asyncio.run(_review_with_heartbeat(verifier, _two_hundred_claims(source)))

    assert calls == [1], "200 claims cite one source: it is checked, hashed and scanned once"
    assert took < BOUND_S and gap < MAX_GAP_S, (took, gap)
    assert review.result == "passed" and model.call_count == 200


@pytest.mark.parametrize(
    ("claim_text", "expected"),
    [
        ("Firm Faa reported revenue of ٩٤٥ million.", "contradicted"),  # Arabic-Indic 945
        ("Firm Faa reported revenue of ९४५ million.", "contradicted"),  # Devanagari 945
        ("Firm Faa reported revenue of ٤٥ million.", "supported"),  # Arabic-Indic 45
        ("Firm Faa reported revenue of ４５ million.", "supported"),  # full-width 45
        ("Firm Faa reported revenue of 45 million.", "supported"),
    ],
    ids=["arabic_indic_wrong", "devanagari_wrong", "arabic_indic_right", "fullwidth_right", "ascii_right"],
)
def test_FR_AGT_12_numbers_in_any_script_are_read_as_the_numbers_they_are(claim_text, expected) -> None:
    source = "Firm Faa reported revenue of 45 million."
    manifest = build_manifest(
        artifact_id="art_digits", sources={"src_a": source}, claims=[claim("cl_1", claim_text, ["src_a"])]
    )
    verifier, _ = make_verifier(ScriptedProvider(default=LENIENT))

    review = asyncio.run(verifier.review(deliverable_of(manifest, {"src_a": source})))

    assert review.status == {"cl_1": expected}
