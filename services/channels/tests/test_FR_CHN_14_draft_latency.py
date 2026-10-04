"""FR-CHN-14 acceptance test: "Instruction to draft ready in <= 15 s p95 (EV-15)", "Latency test on 50 cases"
(PRD 11.6; EV-15 3.x; NFR-09).

The 50 drafting cases of FR-CHN-10 (20 E-MAIL + 30 fixture cases) run through the real `Drafter` and checker on the
fake clock. Provider latency is injected: each thread read, safety check and model call advances the fake clock by a
seeded random delay inside the bounds below, and the CPU time the drafter itself uses (`time.process_time`, the
checker included) is added, so a slow checker shows up. A third of the cases get an invented first answer, so the
regeneration path (the longest, 2 model calls) is inside the p95. Also: the worst case is bounded by the attempt cap,
a provider timeout degrades to a non-ready result without a second wait, the checker has a CPU budget, and a replayed
instruction costs no provider time. No sleeps, no network, no paid calls, no LIVE=1.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Callable

import pytest
from _chn10_lib import DraftingCase, Rig, answer, case_rig, draft_case, drafting_module, load_drafting_cases
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

CASES = load_drafting_cases()
DRAFT_P95_S = 15.0  # PRD 11.6 FR-CHN-14, 3 EV-15, 17.2 NFR-09
# Provider latency bounds in seconds (BQ-159): a Gmail thread read, a safety check, one autopilot-role model call.
READ_S, SAFETY_S, MODEL_S = (0.3, 0.8), (0.2, 0.5), (2.0, 4.5)
MODEL_TIMEOUT_S = 10.0  # a model call that gives up (BQ-160): one wait, never retried
CPU_BUDGET_S = DRAFT_P95_S * 0.1  # drafter plus checker may use at most 10% of the budget per draft (BQ-161)


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def slow(rig: Rig, rng: random.Random, read=READ_S, safety=SAFETY_S, model=MODEL_S) -> None:
    """Every provider call moves the fake clock by a random delay in its bounds, then does its normal work."""

    def wrap(obj, name: str, bounds: tuple[float, float]) -> None:
        inner: Callable = getattr(obj, name)

        def call(*args, **kwargs):
            rig.clock.advance(rng.uniform(*bounds))
            return inner(*args, **kwargs)

        setattr(obj, name, call)

    wrap(rig.reader, "get_thread", read)
    wrap(rig.safety, "check", safety)
    wrap(rig.model, "generate", model)


def measured(rig: Rig, case: DraftingCase) -> tuple[float, object]:
    """Seconds from the instruction to the draft: fake-clock provider time plus the drafter's own CPU time."""
    start, cpu = rig.clock(), time.process_time()
    result = draft_case(rig, case)
    return (rig.clock() - start) + (time.process_time() - cpu), result


def run_all(model_bounds=MODEL_S) -> tuple[list[float], list[object], int]:
    rng, times, results, regenerated = random.Random(14), [], [], 0
    for i, case in enumerate(CASES):
        first = [case.invented[0].body] if i % 3 == 0 and case.invented else []
        rig, _ = case_rig(case, *[answer(b) for b in first], answer(case.clean))
        slow(rig, rng, model=model_bounds)
        seconds, result = measured(rig, case)
        times.append(seconds)
        results.append(result)
        regenerated += len(rig.model.requests) - 1
    return times, results, regenerated


def test_FR_CHN_14_draft_ready_within_15_s_p95_on_50_cases() -> None:
    drafting_module()
    assert len(CASES) == 50
    times, results, regenerated = run_all()
    assert [r.status for r in results] == ["ready"] * 50, "latency is only meaningful for drafts that are ready"
    assert regenerated >= 15, "the regeneration path (2 model calls) must be inside the measured set"
    assert p95(times) <= DRAFT_P95_S, f"p95 {p95(times):.1f} s > {DRAFT_P95_S:.0f} s (max {max(times):.1f} s)"


def test_FR_CHN_14_harness_sees_a_slow_model() -> None:
    """Guards the measurement: with a model that takes 8 to 9 s per call the same run must miss the budget."""
    drafting_module()
    times, _, _ = run_all(model_bounds=(8.0, 9.0))
    assert p95(times) > DRAFT_P95_S


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    data=st.data(),
    regenerate=st.booleans(),
    index=st.integers(0, len(CASES) - 1),
)
def test_FR_CHN_14_worst_case_latency_is_bounded_by_the_attempt_cap(data, regenerate, index) -> None:
    """Whatever the latencies inside their bounds, one draft is <= 1 read + 2 model calls + 3 safety checks."""
    drafting_module()
    case = CASES[index]
    answers = ([case.invented[0].body] if regenerate and case.invented else []) + [case.clean]
    rig, _ = case_rig(case, *[answer(b) for b in answers])
    rng = random.Random(data.draw(st.integers(0, 2**31)))
    slow(rig, rng)
    start = rig.clock()
    draft_case(rig, case)
    bound = READ_S[1] + 3 * SAFETY_S[1] + 2 * MODEL_S[1]  # 11.3 s: inside 15 s with room for the checker
    assert len(rig.model.requests) <= 2
    assert rig.clock() - start <= bound + 1e-9 < DRAFT_P95_S


@pytest.mark.parametrize("failing", ["model", "safety"])
def test_FR_CHN_14_provider_timeout_degrades_without_a_second_wait(failing) -> None:
    """A provider that times out does not hang the instruction: the user gets a not-ready result (or the error)
    after one wait, the drafter never retries into a second timeout, and nothing is stored or emitted."""
    drafting_module()
    case = CASES[0]
    rig, _ = case_rig(case, answer(case.clean))
    slow(rig, random.Random(1))
    waits = []

    def times_out(*args, **kwargs):
        waits.append(1)
        rig.clock.advance(MODEL_TIMEOUT_S)
        raise TimeoutError("provider timed out")

    setattr(rig.model if failing == "model" else rig.safety, "generate" if failing == "model" else "check", times_out)
    start = rig.clock()
    try:
        result = draft_case(rig, case)
    except TimeoutError:
        assert rig.drafts.dump() == "{}", "an error leaves nothing stored"
    else:
        assert result.status in ("needs_you", "failed") and result.draft is None
    assert len(waits) == 1, "one timeout, one wait: no retry into a second timeout"
    assert rig.clock() - start <= READ_S[1] + SAFETY_S[1] + MODEL_TIMEOUT_S < DRAFT_P95_S
    assert rig.events.of_type("artifact.created") == []


def test_FR_CHN_14_checker_cpu_budget() -> None:
    """The deterministic checker (PRD 19.3) stays far under the 15 s budget: every fixture answer, then a
    maximum-size adversarial body (dense numbers, dates, links) over a maximum-size thread."""
    mod = drafting_module()
    from tilo_channels.drafting_check import CHECK_CAP

    start = time.process_time()
    for case in CASES:
        for body in (case.clean, *[i.body for i in case.invented]):
            mod.find_invented(body, instruction=case.instruction, thread=case.sources())
    assert time.process_time() - start <= CPU_BUDGET_S, "fixture answers"

    dense = "On Mon 5 Nov at 3:45 PM call +1 415 555 0100 or see https://a.example/x, refund $1,200.00. "
    body = (dense * (CHECK_CAP // len(dense)))[:CHECK_CAP]
    thread = [body] * 5
    start = time.process_time()
    mod.find_invented(body, instruction=body, thread=thread)
    mod.find_invented(body, instruction="Tell them hello.", thread=thread)
    assert time.process_time() - start <= CPU_BUDGET_S, "maximum-size adversarial input"


def test_FR_CHN_14_drafter_cpu_per_draft_under_budget() -> None:
    """The drafter's own work (prompt building, screening, checking, storing) per draft, providers excluded."""
    drafting_module()
    spent = []
    for case in CASES:
        rig, _ = case_rig(case, answer(case.clean))
        cpu = time.process_time()
        draft_case(rig, case)
        spent.append(time.process_time() - cpu)
    assert p95(spent) <= CPU_BUDGET_S, f"p95 CPU {p95(spent):.3f} s"


def test_FR_CHN_14_replayed_instruction_costs_no_provider_time() -> None:
    drafting_module()
    case = CASES[1]
    rig, _ = case_rig(case, answer(case.clean))
    slow(rig, random.Random(2))
    first = draft_case(rig, case, instruction_id="ins-latency-1")
    start, calls = rig.clock(), len(rig.model.requests)
    again = draft_case(rig, case, instruction_id="ins-latency-1")
    assert again.draft == first.draft
    assert rig.clock() == start and len(rig.model.requests) == calls
