"""FR-CHN-10 acceptance: "Eval: 0 invented commitments across 50 drafting cases" (PRD 11.6; 19.2 E-MAIL; 19.4 gate 5).

A real model cannot run in CI (EFF-01), so the eval runs offline on scripted model answers: the 20 E-MAIL drafting
cases (evals/cases/E-MAIL/E-MAIL-31..50) plus 30 fixture cases. Each case has a clean answer and answers that
invent a commitment, a fact, a date or a link; every eval case's ground-truth `forbidden_commitments` is acted out
by one of them. The pipeline must turn every clean answer into a ready draft and must never let an invented one
become a ready draft. PRD default for invented content: "unclear points are asked, not guessed" (11.4), so the
draft goes back to the user (`needs_you`), after at most one regeneration. API pinned in API_FR_CHN_10.md.
"""

from __future__ import annotations

import pytest
from _chn10_lib import answer, case_rig, draft_case, load_drafting_cases

CASES = load_drafting_cases()
MAX_MODEL_CALLS = 2  # one draft plus at most one regeneration (BQ-TBD; PRD 6.6 efficiency)


def _calls(rig, key: str) -> int:
    return len(rig.model.calls_for(key))


def test_FR_CHN_10_fifty_drafting_cases_with_clean_and_invented_answers() -> None:
    assert len(CASES) == 50
    assert len({c.id for c in CASES}) == 50
    assert len([c for c in CASES if c.id.startswith("E-MAIL-")]) == 20
    assert len({c.thread.messages[-1].body for c in CASES}) == 50  # each thread is told apart by its last body
    for case in CASES:
        assert case.clean.strip()
        assert case.invented, case.id
        for inv in case.invented:
            assert inv.kind in {"number", "date", "contact", "commitment"}
            assert inv.sentence in inv.body and inv.body != case.clean


def test_FR_CHN_10_every_eval_forbidden_commitment_is_acted_out_by_a_scripted_answer() -> None:
    for case in (c for c in CASES if c.forbidden):
        realized = {inv.realizes for inv in case.invented}
        assert set(case.forbidden) <= realized, f"{case.id}: {set(case.forbidden) - realized}"


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_FR_CHN_10_clean_answer_becomes_a_ready_draft(case) -> None:
    rig, key = case_rig(case, answer(case.clean))

    result = draft_case(rig, case)

    assert result.status == "ready", (case.id, result.status, result.findings)
    assert result.draft is not None
    assert case.clean.strip() in result.draft.body
    assert result.findings == ()
    assert _calls(rig, key) == 1


INVENTED = [(c, inv) for c in CASES for inv in c.invented]
IDS = [f"{c.id}-{n}-{inv.kind}" for n, (c, inv) in enumerate(INVENTED)]


@pytest.mark.parametrize("case,invented", INVENTED, ids=IDS)
def test_FR_CHN_10_invented_answer_never_becomes_a_ready_draft(case, invented) -> None:
    rig, key = case_rig(case, answer(invented.body))  # the model invents on every attempt

    result = draft_case(rig, case)

    assert result.status == "needs_you", (case.id, invented.sentence)
    assert result.draft is None
    assert invented.kind in {f.kind for f in result.findings}
    assert 1 <= _calls(rig, key) <= MAX_MODEL_CALLS
    assert rig.events.of_type("artifact.created") == []


def test_FR_CHN_10_regeneration_never_ships_the_invented_answer() -> None:
    for case in CASES:
        first = case.invented[0]
        rig, key = case_rig(case, answer(first.body), answer(case.clean))

        result = draft_case(rig, case)

        assert _calls(rig, key) <= MAX_MODEL_CALLS
        if result.status == "ready":  # regenerated: only the clean answer may ship
            assert first.sentence not in result.draft.body
            assert case.clean.strip() in result.draft.body
        else:
            assert result.status == "needs_you" and result.draft is None


def test_FR_CHN_10_eval_pass_counts_zero_invented_commitments_across_50_cases() -> None:
    """The acceptance number: run all 50 cases with a model that invents on half of them (always) and is clean on
    the other half; count invented sentences in drafts that came out ready. Counts first (PRD 19.3)."""
    ready = invented_in_ready = asked = 0
    for n, case in enumerate(CASES):
        inventing = n % 2 == 0
        scripted = [answer(i.body) for i in case.invented] if inventing else [answer(case.clean)]
        rig, _ = case_rig(case, *scripted)

        result = draft_case(rig, case)

        if result.status == "ready":
            ready += 1
            invented_in_ready += sum(1 for i in case.invented if i.sentence in result.draft.body)
        else:
            asked += 1
            assert result.status == "needs_you"

    assert invented_in_ready == 0
    assert (ready, asked) == (25, 25), f"{ready} of 50 ready, {asked} of 50 asked"


def test_FR_CHN_10_model_questions_are_asked_not_guessed() -> None:
    # PRD 11.4 Content: "unclear points are asked, not guessed". The model may answer with questions instead of a
    # draft; they go back to the user and no draft is made.
    case = CASES[0]
    rig, _ = case_rig(case, answer("", questions=["Which Friday does David mean?"]))

    result = draft_case(rig, case)

    assert result.status == "needs_you"
    assert result.draft is None
    assert result.questions == ("Which Friday does David mean?",)
    assert rig.events.of_type("artifact.created") == []
