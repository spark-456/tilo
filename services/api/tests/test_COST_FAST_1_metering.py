"""COST-FAST-1 (supervisor must-have, FR-MTR-01): "nothing stored" still meters.

Every Quick call that reaches a model, the answer and the classifier fallback alike, is charged to the person's
FR-PA-19 daily allowance (the per-user spend limit) and, deployed and live, held on the SEC-16 ledger under all of its
caps (run, uid, org day, global day), not only the uid's. A switch offer decided by the rules costs zero. The Treasury
(`deps.get_ledger`, run-based, read-only, unwired: BQ-MTR10-4) has no seam a Quick call could write to: BQ-COSTFAST-7.
Fakes only; no network, no paid call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from _clint1_lib import FLOW_USER
from _costfast1_lib import SIMPLE_TEXT, assert_answer_shape, sec16_rig
from _sec16_lib import JUDGE_A


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def test_COST_FAST_1_a_fallback_ask_charges_the_classifier_call_and_the_answer_call_to_the_allowance(quick_rig):
    quick_rig.classifier_reply = json.dumps({"kind": "simple"})
    quick_rig.classifier_usage, quick_rig.answer_usage = (300, 20), (400, 80)
    expected = quick_rig.credits_for(300, 20) + quick_rig.credits_for(400, 80)

    body = quick_rig.ask("tell me about Q3").json()

    assert_answer_shape(body)
    assert body["cost"]["model_calls"] == 2 and len(quick_rig.classifier_calls) == 1
    assert body["cost"]["credits"] == pytest.approx(expected)
    assert quick_rig.allowance.spent(FLOW_USER, today()) == pytest.approx(expected), "both calls are charged"


def test_COST_FAST_1_a_classifier_offer_is_charged_too_because_a_model_call_was_made(quick_rig):
    quick_rig.classifier_reply = json.dumps({"kind": "work", "reason": "needs_tools"})
    quick_rig.classifier_usage = (300, 20)

    body = quick_rig.ask("tell me about Q3").json()

    assert body["outcome"] == "switch_to_thinking" and quick_rig.answer_calls == []
    assert quick_rig.allowance.spent(FLOW_USER, today()) == pytest.approx(quick_rig.credits_for(300, 20))


def test_COST_FAST_1_SEC_16_the_unit_is_held_under_the_run_org_day_and_global_caps_not_only_the_uid(
    sec16_factory, monkeypatch, repo_root
):
    h = sec16_factory(rate_limit_requests=1_000)
    rig = sec16_rig(h, monkeypatch, repo_root)

    assert rig.ask(SIMPLE_TEXT).status_code == 200

    (reserve,) = [kwargs for name, _args, kwargs in h.ledger.calls if name == "reserve"]
    assert reserve["uid"] == JUDGE_A and reserve["amount_minor"] == h.caps.unit_reserve_minor
    assert reserve["run_id"] and reserve["org_id"], "the run, org-day and global-day caps count this unit too"
