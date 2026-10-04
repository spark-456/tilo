"""FR-AGT-12 hardening, round 4 of the security review of #278 (PRD 8.1, 16.3; UAX #15 stream-safe format).

Mark runs are counted on the DECOMPOSED text: U+FF9E and U+FF9F are not combining themselves but decompose into
U+3099/U+309A, so `(U+0F73 * 30 + U+FF9E)` repeated to 30k chars used to slip past a raw count and take 14 s per
source. The NFKC output is capped before the second pass (U+FDFA expands 18 times), the cited sources of a claim
are summed before any is prepared, the distinct sources of a review are capped and a review has a budget of
normalised characters. Every timed test bounds time generously and checks that the event loop never stalls.
"""

from __future__ import annotations

import asyncio
import sys
import time
import unicodedata

import pytest
from agt_scripted import ScriptedProvider
from agt_verifier_support import LENIENT, build_manifest, claim, deliverable_of, make_verifier
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_harness import untrusted
from tilo_harness import verifier as verifier_module
from tilo_harness.untrusted import Budget, BudgetSpent, has_long_mark_run, neutralise, nfkc
from tilo_harness.validator import repo_validator

SIZE = 30_000
TRUE_CLAIM = "Firm Faa was founded by two friends."
BOUND_S = 5.0
MAX_GAP_S = 1.0
TIB = "\u0f73"  # Mn, ccc 0, NFKD: two non-starters
VOICED, SEMI = "\uff9e", "\uff9f"  # Lm, ccc 0, NFKD: U+3099 / U+309A, one non-starter each
ACUTE = "\u0301"
C_CEDILLA_ACUTE = "\u1e09"  # c + U+0327 + U+0301: a starter that ends in two non-starters
LIGATURE = "\ufdfa"  # NFKC expands it to 18 characters
ZWSP = "\u200b"
HOSTILE = {
    "0f73x30_ff9e": (TIB * 30 + VOICED) * (SIZE // 31 + 1),
    "0f73x30_ff9f": (TIB * 30 + SEMI) * (SIZE // 31 + 1),
    "alternating_0f73_ff9e": (TIB + VOICED) * (SIZE // 2),
    "alternating_0f73_ff9f": (TIB + SEMI) * (SIZE // 2),
}


def _nfkd_runs(text: str) -> tuple[int, int]:
    """(longest run of non-starters, length) of NFKD(text), counted the slow, obvious way."""
    longest = run = 0
    decomposed = unicodedata.normalize("NFKD", text)
    for char in decomposed:
        run = run + 1 if unicodedata.combining(char) else 0
        longest = max(longest, run)
    return longest, len(decomposed)


async def _review_with_heartbeat(verifier, deliverable):
    repo_validator().contract_problems("manifest", {})  # the one-time schema load is not what is measured
    gaps: list[float] = []
    stop = False

    async def beat() -> None:
        last = time.perf_counter()
        while not stop:
            await asyncio.sleep(0.01)
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


# --- the run is counted on the decomposed form --------------------------------------------------


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_FR_AGT_12_halfwidth_sound_marks_join_a_decomposed_mark_run(name) -> None:
    text = HOSTILE[name][:SIZE]
    start = time.perf_counter()
    assert has_long_mark_run(text)
    cleaned = neutralise(text, limit=SIZE)
    numbers = verifier_module._numbers(text, Budget(10**9))
    took = time.perf_counter() - start
    assert took < BOUND_S, f"{name}: {took:.2f} s"
    assert _nfkd_runs(cleaned)[0] <= untrusted.MAX_MARK_RUN and len(cleaned) <= SIZE
    assert numbers == frozenset()


@pytest.mark.parametrize(
    ("text", "long"),
    [
        ("a" + TIB * 15, False),  # 30 non-starters once decomposed
        ("a" + TIB * 15 + ACUTE, True),  # 31
        ("a" + VOICED * 30, False),
        ("a" + VOICED * 31, True),
        (TIB * 15 + SEMI, True),  # 31: each U+0F73 is two, U+FF9F one
        (C_CEDILLA_ACUTE + ACUTE * 28, False),  # 2 trailing + 28 = 30
        (C_CEDILLA_ACUTE + ACUTE * 29, True),
        (TIB * 15 + "b" + TIB * 15, False),  # a starter resets the run
    ],
    ids=["30_0f73", "31_0f73", "30_ff9e", "31_ff9e", "31_ff9f", "30_trailing", "31_trailing", "reset"],
)
def test_FR_AGT_12_runs_of_30_pass_and_31_are_long_on_the_decomposed_form(text, long) -> None:
    assert has_long_mark_run(text) is long
    assert (_nfkd_runs(text)[0] > untrusted.MAX_MARK_RUN) is long
    assert _nfkd_runs(neutralise(text, limit=SIZE))[0] <= untrusted.MAX_MARK_RUN


def test_FR_AGT_12_the_per_character_table_agrees_with_nfkd_for_every_code_point() -> None:
    wrong = []
    for code in range(sys.maxunicode + 1):
        char = chr(code)
        marks = "".join("m" if unicodedata.combining(c) else "s" for c in unicodedata.normalize("NFKD", char))
        brute = (len(marks) - len(marks.lstrip("m")), len(marks) - len(marks.rstrip("m")), len(marks))
        if untrusted._profile(char) != brute:
            wrong.append(hex(code))
    assert wrong == []


_ALPHABET = st.sampled_from(
    ["a", "1", "\n", TIB, VOICED, SEMI, ACUTE, "\u0344", C_CEDILLA_ACUTE, "\u00c0", LIGATURE, ZWSP]
    + ["\u0f71", "\u0f72", "\uac00", "\u2028"]
)


@settings(max_examples=300, deadline=None)
@given(st.lists(_ALPHABET, max_size=120).map("".join), st.integers(min_value=1, max_value=400))
def test_FR_AGT_12_stream_safe_count_matches_the_decomposed_text(text, limit) -> None:
    assert has_long_mark_run(text) is (_nfkd_runs(text)[0] > untrusted.MAX_MARK_RUN)
    out = nfkc(text, limit=limit)
    longest, size = _nfkd_runs(out)
    assert longest <= untrusted.MAX_MARK_RUN and size <= limit and len(out) <= limit
    cleaned = neutralise(text, limit=limit)
    assert _nfkd_runs(cleaned)[0] <= untrusted.MAX_MARK_RUN and len(cleaned) <= limit
    if not has_long_mark_run(text) and _nfkd_runs(text)[1] <= limit:
        assert out == unicodedata.normalize("NFKC", text), "text that needs no cut is normalised unchanged"


def test_FR_AGT_12_an_expanding_character_is_capped_before_the_second_pass() -> None:
    text = LIGATURE * SIZE
    start = time.perf_counter()
    once = nfkc(text, limit=SIZE)
    cleaned = neutralise(text, limit=SIZE)
    numbers = verifier_module._numbers(text, Budget(10**9))
    took = time.perf_counter() - start
    assert took < BOUND_S, f"{took:.2f} s"
    assert SIZE - 18 < len(once) <= SIZE and len(cleaned) <= SIZE and numbers == frozenset()
    budget = Budget(10**9)
    nfkc(text, limit=SIZE, budget=budget)
    assert 10**9 - budget.left <= SIZE, "the budget is spent on the capped, decomposed length"


# --- reviews stay fast and never stall the loop -----------------------------------------------------


def test_FR_AGT_12_two_hundred_claims_citing_one_hostile_source_review_fast() -> None:
    source = HOSTILE["0f73x30_ff9e"][:SIZE]
    claims = [claim(f"cl_{k}", TRUE_CLAIM, ["src_a"]) for k in range(200)]
    manifest = build_manifest(artifact_id="art_ff9e", sources={"src_a": source}, claims=claims)
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)

    review, took, gap = asyncio.run(_review_with_heartbeat(verifier, deliverable_of(manifest, {"src_a": source})))

    assert took < BOUND_S and gap < MAX_GAP_S, (took, gap)
    assert set(review.status.values()) == {"unverified"} and model.call_count == 0
    assert review.notes["cl_0"] == ["source src_a: holds a long run of combining characters"]


def test_FR_AGT_12_a_review_over_three_heavy_distinct_sources_is_fast() -> None:
    sources = {
        "src_a": HOSTILE["alternating_0f73_ff9f"][:SIZE],  # refused: one long decomposed run
        "src_b": (TRUE_CLAIM + " " + (TIB * 15 + ZWSP) * SIZE)[:SIZE],  # usable; runs join once ZWSP goes
        "src_c": (TRUE_CLAIM + " " + LIGATURE * SIZE)[:SIZE],  # usable; NFKC expands it 18 times
    }
    claims = [claim(f"cl_{k}", TRUE_CLAIM, [f"src_{'abc'[k % 3]}"]) for k in range(30)]
    manifest = build_manifest(artifact_id="art_three", sources=sources, claims=claims)
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)

    review, took, gap = asyncio.run(_review_with_heartbeat(verifier, deliverable_of(manifest, sources)))

    assert took < BOUND_S and gap < MAX_GAP_S, (took, gap)
    assert review.status["cl_0"] == "unverified" and review.status["cl_1"] == review.status["cl_2"] == "supported"
    assert model.call_count == 20


# --- caps applied before anything is prepared -------------------------------------------------------


def _counting_prepare(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = verifier_module._prepare
    monkeypatch.setattr(verifier_module, "_prepare", lambda *a: calls.append(1) or real(*a))
    return calls


def test_FR_AGT_12_cited_sources_are_summed_before_any_is_prepared(monkeypatch) -> None:
    calls = _counting_prepare(monkeypatch)
    sources = {"src_a": "word " * 4_000, "src_b": "text " * 4_000}  # 20,000 each, 40,000 together
    manifest = build_manifest(
        artifact_id="art_sum", sources=sources, claims=[claim("cl_1", TRUE_CLAIM, ["src_a", "src_b"])]
    )
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)

    review = asyncio.run(verifier.review(deliverable_of(manifest, sources)))

    assert review.status == {"cl_1": "unverified"} and model.call_count == 0 and calls == []
    assert review.notes == {"cl_1": ["cited sources together too long to check"]}


def test_FR_AGT_12_distinct_sources_per_review_are_capped(monkeypatch) -> None:
    calls = _counting_prepare(monkeypatch)
    monkeypatch.setattr(verifier_module, "MAX_SOURCES", 2)
    sources = {sid: f"{TRUE_CLAIM} Note {sid[-1]}." for sid in ("src_a", "src_b", "src_c")}
    claims = [claim(f"cl_{sid[-1]}", TRUE_CLAIM, [sid]) for sid in sources]
    manifest = build_manifest(artifact_id="art_cap", sources=sources, claims=claims)
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)

    review = asyncio.run(verifier.review(deliverable_of(manifest, sources)))

    assert len(calls) == 2 and model.call_count == 2
    assert review.status == {"cl_a": "supported", "cl_b": "supported", "cl_c": "unverified"}
    assert review.notes == {"cl_c": ["source src_c: past the first 2 sources of this review"]}


def test_FR_AGT_12_a_spent_normalising_budget_leaves_claims_unverified(monkeypatch) -> None:
    source = f"{TRUE_CLAIM} " * 20
    claims = [claim("cl_1", TRUE_CLAIM, ["src_a"]), claim("cl_2", TRUE_CLAIM, ["src_a"])]
    manifest = build_manifest(artifact_id="art_budget", sources={"src_a": source}, claims=claims)

    monkeypatch.setattr(verifier_module, "MAX_REVIEW_CHARS", 10)
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)
    review = asyncio.run(verifier.review(deliverable_of(manifest, {"src_a": source})))
    assert set(review.status.values()) == {"unverified"} and model.call_count == 0
    assert review.notes["cl_1"] == ["source src_a: the review's budget for normalising text is spent"]

    # Enough for the source (two neutralise passes and the number scan) and one claim, not for the second.
    monkeypatch.setattr(verifier_module, "MAX_REVIEW_CHARS", 3 * len(source) + 3 * len(TRUE_CLAIM))
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)
    review = asyncio.run(verifier.review(deliverable_of(manifest, {"src_a": source})))
    assert review.status == {"cl_1": "supported", "cl_2": "unverified"} and model.call_count == 1
    assert review.notes == {"cl_2": ["claim: the review's budget for normalising text is spent"]}

    budget = Budget(5)
    with pytest.raises(BudgetSpent):
        budget.spend(6)


def test_FR_AGT_12_a_claim_over_its_cap_is_unverified_before_it_is_normalised(monkeypatch) -> None:
    monkeypatch.setattr(verifier_module, "MAX_CLAIM_CHARS", 10)
    manifest = build_manifest(
        artifact_id="art_claim", sources={"src_a": TRUE_CLAIM}, claims=[claim("cl_1", TRUE_CLAIM, ["src_a"])]
    )
    model = ScriptedProvider(default=LENIENT)
    verifier, _ = make_verifier(model)

    review = asyncio.run(verifier.review(deliverable_of(manifest, {"src_a": TRUE_CLAIM})))

    assert review.status == {"cl_1": "unverified"} and model.call_count == 0
    assert review.notes == {"cl_1": ["claim text too long to check"]}
