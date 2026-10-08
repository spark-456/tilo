"""COST-FAST-1 (requirement 9): spend limits and retries of Quick.

* P8 / FR-PA-19: a Quick call reserves its half-credit budget against the person's daily allowance
  (`deps.get_spend_ledger()`, the panel's own ledger) before it is sent, commits what it cost, and releases the hold
  when the call fails.
* SEC-16 (`config/spend_caps.yaml`, `API_SEC_16.md`): deployed, a live Quick answer counts against the uid's lifetime
  cap:
  one unit (`caps.unit_reserve_minor`, BQ-SEC16-1) is reserved before the call and settled after it, released when the
  call fails, never touched for a switch offer or for a replay-mode judge. At the cap, or when one more unit would pass
  it, Quick is refused 403 `spend_cap_reached` before any model is called. The per-uid rate limit counts Quick asks.
* Idempotency: an optional `Idempotency-Key` header on a Quick ask (people_limits' rule): the same principal, key and
  body again is the first answer with one model call and one charge; another body is a 422; another principal's key is
  its own; a failed first attempt leaves the key free; racing retries make one call.

Fakes only; no network, no paid call.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from _clint1_lib import FLOW_USER, OTHER_USER
from _costfast1_lib import SIMPLE_TEXT, assert_answer_shape, assert_offer_shape, sec16_rig
from _sec16_lib import JUDGE_A, DeadLedger, spend
from fastapi.testclient import TestClient
from tilo_api import app
from tilo_providers.errors import RequestError

BIG_LIMIT = {"rate_limit_requests": 1_000}
WORK_TEXT = "Send an email to the supplier asking for a new quote."
KEY = {"Idempotency-Key": "retry-key-0001"}


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


# --- the FR-PA-19 allowance --------------------------------------------------------------------------------------


def test_COST_FAST_1_a_failed_quick_call_releases_its_hold_and_commits_nothing(quick_rig):
    from tilo_api.assistant.config import load_assistant_config  # noqa: PLC0415

    cap = load_assistant_config().user_day_credits
    quick_rig.fail = RequestError("PL-02: 400 (fake)")

    assert quick_rig.ask(SIMPLE_TEXT).status_code == 502

    assert quick_rig.allowance.spent(FLOW_USER, today()) == 0
    assert quick_rig.allowance.reserve(FLOW_USER, today(), cap, cap) is not None, "no reservation is left open"


def test_COST_FAST_1_a_switch_offer_never_touches_the_allowance(quick_rig):
    from tilo_api.assistant.config import load_assistant_config  # noqa: PLC0415

    cap = load_assistant_config().user_day_credits

    assert quick_rig.ask(WORK_TEXT).status_code == 200

    assert quick_rig.allowance.spent(FLOW_USER, today()) == 0
    assert quick_rig.allowance.reserve(FLOW_USER, today(), cap, cap) is not None


# --- SEC-16 -----------------------------------------------------------------------------------------------------


def test_COST_FAST_1_SEC_16_a_live_quick_answer_reserves_and_settles_one_unit_on_the_uid_cap(
    sec16_factory, monkeypatch, repo_root
):
    h = sec16_factory(**BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)

    response = rig.ask(SIMPLE_TEXT)

    assert response.status_code == 200, response.text
    assert_answer_shape(response.json())
    assert set(h.router_modes) == {"live"}
    assert h.ledger.writes == ["reserve", "settle"]
    assert h.ledger.settled_minor(JUDGE_A) == h.caps.unit_reserve_minor
    assert h.ledger.spent_minor(JUDGE_A) == h.caps.unit_reserve_minor, "nothing is left held"


def test_COST_FAST_1_SEC_16_a_switch_offer_costs_the_uid_nothing(sec16_factory, monkeypatch, repo_root):
    h = sec16_factory(**BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)

    response = rig.ask(WORK_TEXT)

    assert response.status_code == 200, response.text
    assert_offer_shape(response.json(), "side_effect")
    assert h.ledger.writes == [] and h.ledger.spent_minor(JUDGE_A) == 0
    assert rig.provider_requests == []


def test_COST_FAST_1_SEC_16_a_failed_live_quick_call_releases_its_unit(sec16_factory, monkeypatch, repo_root):
    h = sec16_factory(**BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)
    rig.fail = RequestError("PL-02: 400 (fake)")

    assert rig.ask(SIMPLE_TEXT).status_code == 502

    assert h.ledger.writes == ["reserve", "release"]
    assert h.ledger.spent_minor(JUDGE_A) == 0


def test_COST_FAST_1_SEC_16_the_last_unit_under_the_cap_is_answered_and_the_next_ask_is_refused(
    sec16_factory, monkeypatch, repo_root
):
    h = sec16_factory(**BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)
    spend(h.ledger, JUDGE_A, h.caps.uid_lifetime_minor - h.caps.unit_reserve_minor)  # exactly one unit left

    last = rig.ask(SIMPLE_TEXT)
    after = rig.ask(SIMPLE_TEXT)

    assert last.status_code == 200, last.text
    assert h.ledger.settled_minor(JUDGE_A) == h.caps.uid_lifetime_minor
    assert after.status_code == 403 and after.json()["code"] == "spend_cap_reached", after.text
    assert len(rig.answer_calls) == 1


def test_COST_FAST_1_SEC_16_an_ask_that_would_pass_the_cap_is_refused_before_any_model_is_called(
    sec16_factory, monkeypatch, repo_root
):
    """Not yet at the cap, but one more unit would pass it: 403 `spend_cap_reached`, no model, nothing held."""
    h = sec16_factory(**BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)
    spend(h.ledger, JUDGE_A, h.caps.uid_lifetime_minor - 1)  # one paisa under: less than one unit
    before = h.ledger.spent_minor(JUDGE_A)

    response = rig.ask(SIMPLE_TEXT)

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "spend_cap_reached" and len(str(body["detail"])) > 20
    assert rig.provider_requests == []
    assert h.ledger.spent_minor(JUDGE_A) == before
    assert not [e for events in h.store.events.values() for e in events]


def test_COST_FAST_1_SEC_16_a_uid_at_the_cap_gets_quick_and_thinking_refused_alike(
    sec16_factory, monkeypatch, repo_root
):
    h = sec16_factory(**BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)
    spend(h.ledger, JUDGE_A, h.caps.uid_lifetime_minor)

    for mode in ("quick", "thinking"):
        response = rig.ask(SIMPLE_TEXT, mode=mode)
        assert response.status_code == 403 and response.json()["code"] == "spend_cap_reached", (mode, response.text)
    assert rig.provider_requests == []


def test_COST_FAST_1_SEC_16_a_replay_mode_judge_is_answered_and_the_ledger_is_never_written(
    sec16_factory, monkeypatch, repo_root
):
    h = sec16_factory(judge_live=False, **BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)

    response = rig.ask(SIMPLE_TEXT)

    assert response.status_code == 200, response.text
    assert set(h.router_modes) == {"replay"}
    assert h.ledger.writes == []


def test_COST_FAST_1_SEC_16_an_unreachable_spend_ledger_means_replay_and_never_a_5xx(
    sec16_factory, monkeypatch, repo_root
):
    h = sec16_factory(ledger=DeadLedger(), **BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)

    response = rig.ask(SIMPLE_TEXT)

    assert response.status_code == 200, response.text
    assert set(h.router_modes) == {"replay"}


def test_COST_FAST_1_SEC_16_the_rate_limit_counts_quick_asks(sec16_factory, monkeypatch, repo_root):
    h = sec16_factory()  # three asks a window in the test caps
    rig = sec16_rig(h, monkeypatch, repo_root)

    codes = [rig.ask(SIMPLE_TEXT).status_code for _ in range(4)]

    assert codes == [200, 200, 200, 429]
    assert len(rig.answer_calls) == 3, "the refused ask reached no model"


# --- Idempotency-Key ---------------------------------------------------------------------------------------------


def test_COST_FAST_1_a_retry_with_the_same_key_is_the_first_answer_with_one_call_and_one_charge(quick_rig):
    quick_rig.answer = lambda n: f"answer-{n}"

    first = quick_rig.ask(SIMPLE_TEXT, headers=KEY)
    again = quick_rig.ask(SIMPLE_TEXT, headers=KEY)

    assert first.status_code == again.status_code == 200
    assert again.content == first.content, "the first answer, byte for byte"
    assert first.json()["text"] == "answer-1"
    assert len(quick_rig.answer_calls) == 1
    assert quick_rig.allowance.spent(FLOW_USER, today()) == pytest.approx(first.json()["cost"]["credits"])


def test_COST_FAST_1_SEC_16_a_retry_is_not_charged_to_the_uid_twice(sec16_factory, monkeypatch, repo_root):
    h = sec16_factory(**BIG_LIMIT)
    rig = sec16_rig(h, monkeypatch, repo_root)

    for _ in range(3):
        assert rig.ask(SIMPLE_TEXT, headers=KEY).status_code == 200

    assert h.ledger.settled_minor(JUDGE_A) == h.caps.unit_reserve_minor


def test_COST_FAST_1_the_same_key_with_another_question_is_refused(quick_rig):
    assert quick_rig.ask(SIMPLE_TEXT, headers=KEY).status_code == 200

    reused = quick_rig.ask("Why is the sky blue?", headers=KEY)

    assert reused.status_code == 422, reused.text
    assert len(quick_rig.answer_calls) == 1


def test_COST_FAST_1_another_principal_has_its_own_keys(quick_rig):
    quick_rig.answer = lambda n: f"answer-{n}"
    mine = quick_rig.ask(SIMPLE_TEXT, headers=KEY).json()
    quick_rig.flow.as_user(OTHER_USER)

    theirs = quick_rig.ask(SIMPLE_TEXT, headers=KEY).json()

    assert (mine["text"], theirs["text"]) == ("answer-1", "answer-2"), "never another person's stored answer"


@pytest.mark.parametrize("bad", ["x" * 300, "has spaces in it", "semi;colon"])
def test_COST_FAST_1_a_bad_idempotency_key_is_a_422_that_asks_nothing_and_never_echoes_it(quick_rig, bad):
    response = quick_rig.ask(SIMPLE_TEXT, headers={"Idempotency-Key": bad})

    assert response.status_code == 422, response.text
    assert bad not in response.text
    assert quick_rig.provider_requests == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_failed_first_attempt_leaves_the_key_free(quick_rig):
    quick_rig.fail, quick_rig.fail_times = RequestError("PL-02: 400 (fake)"), 1

    assert quick_rig.ask(SIMPLE_TEXT, headers=KEY).status_code == 502
    retried = quick_rig.ask(SIMPLE_TEXT, headers=KEY)

    assert retried.status_code == 200, retried.text
    assert quick_rig.allowance.spent(FLOW_USER, today()) == pytest.approx(retried.json()["cost"]["credits"])


def test_COST_FAST_1_racing_retries_with_one_key_make_one_model_call(quick_rig):
    quick_rig.answer = lambda n: f"answer-{n}"
    results: list = []

    def post() -> None:
        with TestClient(app, raise_server_exceptions=False) as client:
            results.append(client.post("/intake", data={"text": SIMPLE_TEXT, "mode": "quick"}, headers=KEY))

    threads = [threading.Thread(target=post) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert {r.status_code for r in results} == {200}, [r.status_code for r in results]
    assert len({r.content for r in results}) == 1
    assert len(quick_rig.answer_calls) == 1
