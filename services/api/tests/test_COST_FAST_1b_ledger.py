"""COST-FAST-1b (BQ-COSTFAST-7): Quick spend shows in `GET /costs`.

Every Quick call that was billed is committed on a per-user pseudo run (`r_quick_<hash of uid>`; no world, event or
task) through a writable ledger seam (`deps.get_ledger_writer`, fail closed unless wired), for exactly the credits the
FR-PA-19 allowance was charged. `GET /costs` adds that run for the caller only; `/worlds/{id}/costs` never has it.
A ledger write that fails never changes the served answer or the allowance. Fakes only; no network, no paid call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from _clint1_lib import FLOW_USER
from _costfast1_lib import SIMPLE_TEXT
from fastapi import HTTPException
from tilo_providers.errors import OutputTruncatedError, RequestError


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


@pytest.fixture()
def ledger(quick_rig):
    from tilo_api import app, deps, quick_ledger

    book = quick_ledger.MemoryLedger()
    app.dependency_overrides[deps.get_ledger_writer] = lambda: book
    app.dependency_overrides[deps.get_ledger] = lambda: book.entries()
    return book


def costs(rig):
    response = rig.client.get("/costs")
    assert response.status_code == 200, response.text
    return response.json()


def quick_rows(report):
    return [t for t in report["tasks"] if t["run_id"].startswith("r_quick_")]


def test_COST_FAST_1b_an_answer_is_on_costs_for_exactly_the_credits_the_allowance_was_charged(quick_rig, ledger):
    body = quick_rig.ask(SIMPLE_TEXT).json()
    report = costs(quick_rig)

    (row,) = quick_rows(report)
    spent = quick_rig.allowance.spent(FLOW_USER, today())
    assert spent > 0
    assert row["credits"] == pytest.approx(spent) == pytest.approx(body["cost"]["credits"])
    assert report["totals"]["credits"] == pytest.approx(spent)
    assert row["tier"] is None and row["completed"] is False
    assert [r["task_type"] for r in report["by_task_type"]] == ["quick_answer"], "the label the web can tell Quick by"
    assert set(report) == {"credit_usd", "totals", "tasks", "by_tier", "by_profile", "by_task_type", "by_tier_profile"}


def test_COST_FAST_1b_nothing_is_stored_by_the_ledger_write_no_world_no_event(quick_rig, ledger):
    quick_rig.ask(SIMPLE_TEXT)
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1b_the_run_id_fits_the_contract_and_is_stable_per_user(quick_rig, ledger):
    import re

    from tilo_api.quick_ledger import quick_run_id

    assert re.fullmatch(r"r_[0-9A-Za-z_]{1,48}", quick_run_id(FLOW_USER))
    assert quick_run_id(FLOW_USER) == quick_run_id(FLOW_USER) != quick_run_id("u_other")
    assert FLOW_USER not in quick_run_id(FLOW_USER)


def test_COST_FAST_1b_a_fallback_ask_is_one_commit_for_both_calls(quick_rig, ledger):
    quick_rig.classifier_usage, quick_rig.answer_usage = (300, 20), (400, 80)
    quick_rig.ask("tell me about Q3")
    expected = quick_rig.credits_for(300, 20) + quick_rig.credits_for(400, 80)
    (row,) = quick_rows(costs(quick_rig))
    assert row["credits"] == pytest.approx(expected)


def test_COST_FAST_1b_a_rules_offer_costs_nothing_and_writes_nothing(quick_rig, ledger):
    quick_rig.ask("Please email the contract to Bob and then delete my inbox")
    assert ledger.entries() == []
    assert quick_rows(costs(quick_rig)) == []


def test_COST_FAST_1b_billed_failures_are_on_costs_too(quick_rig, ledger):
    quick_rig.fail = OutputTruncatedError("cut (fake)", output_tokens=1000)
    assert quick_rig.ask(SIMPLE_TEXT).status_code == 502
    quick_rig.fail = None
    quick_rig.answer = "  \n "
    assert quick_rig.ask(SIMPLE_TEXT).status_code == 502
    quick_rig.answer = "ok"
    quick_rig.classifier_usage = (300, 20)
    quick_rig.fail = RequestError("PL-02: 400 (fake)")
    assert quick_rig.ask("tell me about Q3").status_code == 502

    (row,) = quick_rows(costs(quick_rig))
    assert row["credits"] == pytest.approx(quick_rig.allowance.spent(FLOW_USER, today()))
    assert len(ledger.entries()) == 3


def test_COST_FAST_1b_an_unbilled_refusal_writes_nothing(quick_rig, ledger):
    quick_rig.fail = RequestError("PL-02: 400 (fake)")
    assert quick_rig.ask(SIMPLE_TEXT).status_code == 502
    assert quick_rig.allowance.spent(FLOW_USER, today()) == 0 and ledger.entries() == []


def test_COST_FAST_1b_a_retry_with_the_same_key_is_charged_and_written_once(quick_rig, ledger):
    headers = {"Idempotency-Key": "k-1"}
    first = quick_rig.ask(SIMPLE_TEXT, headers=headers)
    again = quick_rig.ask(SIMPLE_TEXT, headers=headers)
    assert first.json() == again.json()
    assert len(ledger.entries()) == 1
    (row,) = quick_rows(costs(quick_rig))
    assert row["credits"] == pytest.approx(first.json()["cost"]["credits"])


def test_COST_FAST_1b_another_person_never_sees_the_spend(quick_rig, ledger):
    quick_rig.ask(SIMPLE_TEXT)
    quick_rig.flow.as_user("u_someone_else")
    report = costs(quick_rig)
    assert quick_rows(report) == [] and report["totals"]["credits"] == 0


def test_COST_FAST_1b_the_quick_run_is_the_only_run_written(quick_rig, ledger):
    from tilo_api.quick_ledger import quick_run_id

    quick_rig.ask(SIMPLE_TEXT)
    runs = {e.run for e in ledger.entries()}
    assert runs == {quick_run_id(FLOW_USER)}
    assert not any(e.run.startswith("r_w") for e in ledger.entries()), "no world, so no world report has it"


def test_COST_FAST_1b_a_failing_ledger_write_never_changes_the_answer_or_the_allowance(quick_rig, caplog):
    from tilo_api import app, deps

    class Broken:
        def append(self, entry):
            raise RuntimeError("secret detail the log must not carry")

    app.dependency_overrides[deps.get_ledger_writer] = lambda: Broken()
    response = quick_rig.ask(SIMPLE_TEXT)
    assert response.status_code == 200 and response.json()["outcome"] == "answered"
    assert quick_rig.allowance.spent(FLOW_USER, today()) > 0
    assert "secret detail" not in caplog.text and "RuntimeError" in caplog.text


def test_COST_FAST_1b_unwired_the_seam_fails_closed_and_quick_still_answers(quick_rig):
    from tilo_api import deps

    with pytest.raises(HTTPException) as caught:
        deps.get_ledger_writer()
    assert caught.value.status_code == 503
    response = quick_rig.ask(SIMPLE_TEXT)
    assert response.status_code == 200
    assert quick_rig.allowance.spent(FLOW_USER, today()) > 0


def test_COST_FAST_1b_erasing_a_person_deletes_their_quick_run(quick_rig, ledger):
    quick_rig.ask(SIMPLE_TEXT)
    quick_rig.flow.as_user("u_someone_else")
    quick_rig.ask(SIMPLE_TEXT)
    ledger.erase_quick(FLOW_USER)
    assert {e.user for e in ledger.entries()} == {"u_someone_else"}


def test_COST_FAST_1b_a_classifier_offer_that_was_billed_is_on_costs(quick_rig, ledger):
    quick_rig.classifier_reply = json.dumps({"kind": "work", "reason": "needs_tools"})
    quick_rig.classifier_usage = (300, 20)
    quick_rig.ask("tell me about Q3")
    (row,) = quick_rows(costs(quick_rig))
    assert row["credits"] == pytest.approx(quick_rig.credits_for(300, 20))
