"""LIVE-RESUME (LIVE-QA-14OCT-1730 row 3), FR-HIL-10, FR-HIL-04, BQ-XWORLD-5: the live run stalled after the owner
answered its card from a signed-in web session. That session is bound to no world (`Principal.world_id` is None, a
full Google sign-in), unlike the in-world principals the older FR-HIL-10 tests answer as; the API logged "cross-world
answer ... session world None". Replay providers, the in-process app: no model, no network.

Pinned here: the same answer, from the signed-in owner's session, resumes the waiting run (a question card resumes the
unit; a gate card opens the gate) and the next step runs, and a person who is not the owner is refused with the
route's 404 and wakes nothing.
"""

from __future__ import annotations

import pytest
from _agt05_lib import (
    ASK,
    CLEAR,
    RESUME_BUDGET_S,
    build_ask_flow,
    needs_you_cards,
    start_and_approve,
    tasks_provider,
)
from _clint2_lib import wait_for

pytestmark = pytest.mark.usefixtures("must_ask_ask_mode")  # this suite pins the card and its answer (BQ-ASSUME-1)

OTHER = "u_not_the_owner"


def _signed_in(rf, user_id: str | None = None) -> None:
    """The signed-in web session of production: a full sign-in, bound to no world."""
    from tilo_api import deps  # noqa: PLC0415

    rf.flow._deny = False
    rf.flow.principal = deps.Principal(
        user_id=user_id or rf.flow.principal.user_id, role="owner", channel="web", world_id=None, full_session=True
    )


@pytest.fixture()
def waiting(repo_root):
    flows = []

    def build():
        rf = build_ask_flow(repo_root, tasks_provider(ASK, *CLEAR[1:]), independent=True)
        flows.append(rf)
        start_and_approve(rf)
        wait_for(lambda: rf.events("question.routed"), what="question.routed")
        rf.quiet_stream()
        (card,) = needs_you_cards(rf)
        return rf, card

    yield build
    for rf in flows:
        rf.close()


def test_FR_HIL_10_LIVE_RESUME_a_signed_in_owners_answer_resumes_the_waiting_unit(waiting):
    rf, card = waiting()
    _signed_in(rf)  # the session names no world: the answer is a cross-world answer for the owner (BQ-XWORLD-5)
    assert rf.flow.principal.world_id is None

    response = rf.answer(card["id"], card["options"][0]["id"])

    assert response.status_code == 200 and response.json() == {"outcome": "answered"}, response.text
    wait_for(lambda: "U1" in rf.runner.started_at, timeout=RESUME_BUDGET_S + 1, what="U1 to resume")
    (answered,) = rf.events("question.answered")
    assert answered["data"]["answered_by"] == "person"
    assert rf.runner.ran.count("U1") == 1, "the asked unit's work runs once, with the answer"
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    types = [e["type"] for e in rf.quiet_stream()]
    assert types.count("world.completed") == 1 and "world.failed" not in types


def test_FR_HIL_04_LIVE_RESUME_a_signed_in_owners_approve_opens_the_gate_and_the_send_runs(run_flow):
    _requested, card = run_flow.run_to_gate()
    _signed_in(run_flow)
    assert run_flow.flow.principal.world_id is None

    response = run_flow.answer(card["id"], "approve")

    assert response.status_code == 200 and response.json() == {"outcome": "answered"}, response.text
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    resolved = run_flow.events("approval.resolved")
    assert len(resolved) == 1 and resolved[0]["authz"]["by"] == "person"
    assert not run_flow.events("world.failed")


def test_FR_HIL_10_LIVE_RESUME_someone_who_is_not_the_owner_wakes_nothing(waiting):
    rf, card = waiting()
    _signed_in(rf, user_id=OTHER)

    response = rf.answer(card["id"], card["options"][0]["id"])

    assert response.status_code == 404, response.text  # the same 404 as an unknown world
    assert rf.events("question.answered") == []
    assert "U1" not in rf.runner.ran
