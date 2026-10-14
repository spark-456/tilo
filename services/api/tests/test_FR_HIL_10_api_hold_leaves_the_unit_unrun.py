"""FR-HIL-10 through the API, review of PR #336 (PRD 10.2, 10.3 "the Director applies the default", 8.3, FR-HIL-02): an
answer lets the asked unit run only when the harness says so (`Ask.runs`). For the rule card of an uncovered send
("Hold this step" / "Prepare it") a person's Hold and the deadline's safe default (also Hold) leave the send unit
unrun: no agent.working, no artifact, no gate card, no approval.requested, nothing sent, and the run still ends
(`world.failed`, a step was held) with no thread left waiting. "Prepare it" runs it to its gate. A model-written
question holding control or surrogate characters is cleaned before its card is stored, so the cards route still works.
Scripted models, in-process app: no model, no network, no server.
"""

from __future__ import annotations

import copy
import json
import threading

import pytest
from _agt05_lib import (
    ASK,
    CLEAR_REPLY,
    ScriptedProvider,
    build_ask_flow,
    needs_you_cards,
    start_and_approve,
    worker_of,
)
from _clint2_lib import wait_for

pytestmark = pytest.mark.usefixtures("must_ask_ask_mode")  # these suites pin the cards (BQ-ASSUME-1)


def _asked_send(rf):
    start_and_approve(rf)
    wait_for(lambda: rf.events("question.routed"), what="question.routed")
    rf.quiet_stream()
    (card,) = needs_you_cards(rf)
    return card


def _option(card, label):
    return next(o["id"] for o in card["options"] if o["label"].startswith(label))


def _run_threads(rf):
    return [t for t in threading.enumerate() if t.name == f"run-{rf.world_id}"]


def _assert_send_held(rf):
    worker = worker_of(rf, "U4")
    events = rf.quiet_stream()
    mine = [e for e in events if worker in (e["actor"], e["target"])]
    types = [e["type"] for e in events]
    assert "U4" not in rf.runner.ran, "the held send unit never runs"
    assert not [e for e in mine if e["type"] in ("agent.working", "agent.handoff", "artifact.created")]
    assert rf.events("approval.requested") == [] and [c for c in rf.cards().json() if c["kind"] == "gate"] == []
    assert rf.outbox_store.all_entries() == [] and rf.adapter.sent == []
    assert types.count("world.failed") == 1 and "world.completed" not in types
    assert "held" in rf.events("world.failed")[0]["data"]["reason"]
    wait_for(lambda: not _run_threads(rf), timeout=3, what="the run thread to end")


@pytest.fixture()
def send_flow(repo_root):
    flows = []

    def build():
        flows.append(build_ask_flow(repo_root, ScriptedProvider(default=CLEAR_REPLY), send=True))
        return flows[-1]

    yield build
    for rf in flows:
        rf.close()


def test_FR_HIL_10_api_a_persons_hold_leaves_the_send_unit_unrun_and_the_run_ends(send_flow):
    rf = send_flow()
    card = _asked_send(rf)
    assert card["safe_default"] == _option(card, "Hold")

    response = rf.answer(card["id"], _option(card, "Hold"))

    assert response.status_code == 200, response.text
    wait_for(lambda: rf.events("world.failed"), what="world.failed")
    (answered,) = rf.events("question.answered")
    assert answered["data"]["answered_by"] == "person"
    _assert_send_held(rf)


def test_FR_HIL_10_api_the_deadline_default_leaves_the_send_unit_unrun_and_the_run_ends(send_flow, monkeypatch):
    import tilo_harness.must_ask as must_ask  # noqa: PLC0415

    monkeypatch.setattr(must_ask, "QUESTION_TIMEOUT_S", 1)
    rf = send_flow()
    card = _asked_send(rf)

    wait_for(lambda: rf.events("world.failed"), timeout=8, what="world.failed after the deadline")

    (answered,) = rf.events("question.answered")
    assert (answered["data"]["answered_by"], answered["severity"]) == ("default", "nudge")
    assert rf.answer(card["id"], _option(card, "Prepare")).status_code == 400, "the default closed the card"
    _assert_send_held(rf)


def test_FR_HIL_10_api_prepare_it_runs_the_send_unit_to_its_gate(send_flow):
    rf = send_flow()
    card = _asked_send(rf)

    assert rf.answer(card["id"], _option(card, "Prepare")).status_code == 200
    requested = wait_for(lambda: rf.events("approval.requested"), what="approval.requested")[0]

    assert "U4" in rf.runner.ran and rf.runner.answers["U4"].option == _option(card, "Prepare")
    assert requested["data"]["risk_tier"] == "T3"
    assert [c["kind"] for c in rf.cards().json()] == ["gate"]


def test_FR_HIL_10_api_a_model_written_question_is_cleaned_before_its_card_is_stored(repo_root):
    reply = copy.deepcopy(ASK["model_reply"])
    reply["question"] = "Compare‮ on\ud800 total\ncost​?"
    reply["options"] = ["Total‮ cost", "Delivery\ud800 time"]
    provider = ScriptedProvider({ASK["title"]: json.dumps(reply, ensure_ascii=True)}, default=CLEAR_REPLY)
    rf = build_ask_flow(repo_root, provider)
    try:
        start_and_approve(rf)
        wait_for(lambda: rf.events("question.routed"), what="question.routed")
        rf.quiet_stream()

        response = rf.cards()
        assert response.status_code == 200, response.text
        (card,) = [c for c in response.json() if c["kind"] == "needs_you"]
        text = card["what_happened"] + " ".join(o["label"] for o in card["options"])
        assert not [c for c in text if c in "‮\ud800\n​"], text
        assert card["what_happened"] == "Compare on totalcost?"
    finally:
        rf.close()
