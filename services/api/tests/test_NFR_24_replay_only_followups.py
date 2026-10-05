"""NFR-24 (PRD 17.2) review follow-ups (#323): the refusal says `replay_only: true` in a machine-readable key; callers
get 401 or 404 before the replay-only answer; every route that reaches the Director or starts a run is closed
(intake, answers, approaches, approve); card answers and pause stay open; and the flag the API reads is the
process-wide one the Treasury is meant to set (`tilo_metering.flags.process_flags`)."""

from __future__ import annotations

import pytest
from _clint1_lib import OTHER_USER, seam
from tilo_api import app, deps
from tilo_metering.flags import InMemoryFlagStore, process_flags, use_process_flags

REFUSED = (409, 423, 503)


@pytest.fixture()
def flags(clear_flow):
    store = InMemoryFlagStore()
    app.dependency_overrides[seam(deps, "get_flag_store")] = lambda: store
    return store


def _calls(flow, task_id):
    """Every route NFR-24 closes, as callables."""
    return {
        "intake": lambda: flow.intake(),
        "answers": lambda: flow.answers(task_id, []),
        "approaches": lambda: flow.approaches(task_id),
        "approve": lambda: flow.approve(task_id, "quick", 50),
    }


@pytest.mark.parametrize("route", ["intake", "answers", "approaches", "approve"])
def test_NFR_24_every_route_that_starts_live_work_is_refused_with_replay_only_true(clear_flow, flags, route):
    task = clear_flow.task_with_approaches()
    flags.set("replay_only", True, reason="NFR-24 test")

    response = _calls(clear_flow, task["task_id"])[route]()

    assert response.status_code in REFUSED, response.text
    body = response.json()
    assert body["replay_only"] is True, body
    assert "replay" in str(body["detail"]).lower()


@pytest.mark.parametrize("route", ["intake", "answers", "approaches", "approve"])
def test_NFR_24_a_caller_who_is_not_signed_in_gets_401_before_the_replay_only_answer(clear_flow, flags, route):
    task = clear_flow.task_with_approaches()
    flags.set("replay_only", True, reason="NFR-24 test")
    clear_flow.sign_out()

    assert _calls(clear_flow, task["task_id"])[route]().status_code == 401


@pytest.mark.parametrize("route", ["answers", "approaches", "approve"])
def test_NFR_24_someone_elses_task_is_a_404_before_the_replay_only_answer(clear_flow, flags, route):
    task = clear_flow.task_with_approaches()
    flags.set("replay_only", True, reason="NFR-24 test")
    clear_flow.as_user(OTHER_USER)

    assert _calls(clear_flow, task["task_id"])[route]().status_code == 404


def test_NFR_24_a_card_answer_and_pause_stay_open_while_the_link_is_replay_only(run_flow):
    _, card = run_flow.run_to_gate()
    store = InMemoryFlagStore()
    app.dependency_overrides[seam(deps, "get_flag_store")] = lambda: store
    store.set("replay_only", True, reason="NFR-24 test")

    assert run_flow.pause().status_code in (200, 202), "stopping work is never closed"
    answer = run_flow.answer(card["id"], "hold")  # answering a card already asked is not new live work
    assert answer.status_code != 503 and "replay_only" not in answer.text


def test_NFR_24_the_api_reads_the_process_wide_flag_the_treasury_is_meant_to_set(clear_flow):
    original = process_flags()
    shared = InMemoryFlagStore()
    use_process_flags(shared)
    try:
        assert deps.get_flag_store() is shared
        shared.set("replay_only", True, reason="NFR-24 test: set where the Treasury would set it")

        response = clear_flow.intake()

        assert response.status_code in REFUSED and response.json()["replay_only"] is True
    finally:
        use_process_flags(original)
