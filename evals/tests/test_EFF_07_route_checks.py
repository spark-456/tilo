"""E-ROUTE checks (EFF-07; PRD 19.2 E-ROUTE, 8.3, FR-AGT-06, FR-AGT-07): routed_domain, answered_from_decision.

routed_domain: args `expected` (a domain slug, or null for the owner fallback; else ground_truth["domain"])
and optional `card_id`; passes when the matching question.routed event(s) carry data.domain == expected.
answered_from_decision: optional `decision_id` and `expected` (default true; false asserts a repeat was NOT
answered from a decision, so a person was asked); passes on a question.answered with answered_by "decision".
"""

import json
from pathlib import Path

import pytest
from _evals_lib import REPO_ROOT, make_event
from tilo_evals import Case
from tilo_evals import checks as registry
from tilo_evals.checks import Outcome, get, kind

_CARD_A, _CARD_B = "01JB5VQ0000000000000009003", "01JB5VQ0000000000000009004"
_DECISION = "01J8Z3K4M5N6P7Q8R9S0T1V2W5"


def _case(name: str, args: dict, ground_truth: dict | None = None) -> Case:
    return Case("E-ROUTE-01", "E-ROUTE", "t", ("EFF-07",), "ready", False, {}, (), ground_truth,
                [{"check": name, "args": args}], None, Path("evals/cases/E-ROUTE/E-ROUTE-01.yaml"))  # fmt: skip


def _routed(domain: str | None, card: str = _CARD_A) -> dict:
    return make_event(type="question.routed", data={"card_id": card, "domain": domain})


def _answered(by: str, decision_id: str | None = None) -> dict:
    return make_event(type="question.answered", data={"answered_by": by, "decision_id": decision_id})


def _run(name: str, args: dict, events: list[dict], ground_truth: dict | None = None):
    return get(name)(_case(name, args, ground_truth), Outcome(events=events, outputs={}), args)


def test_EFF_07_route_checks_are_registered_deterministic():
    for name in ("routed_domain", "answered_from_decision"):
        assert registry.is_registered(name)
        assert kind(name) == "deterministic"


def test_EFF_07_routed_domain_passes_on_the_expected_domain():
    assert _run("routed_domain", {"expected": "security"}, [_routed("security")]).passed


def test_EFF_07_routed_domain_fails_on_another_domain_and_names_both():
    result = _run("routed_domain", {"expected": "security"}, [_routed("finance")])
    assert not result.passed and "security" in result.cause and "finance" in result.cause


def test_EFF_07_routed_domain_null_means_owner_fallback():
    assert _run("routed_domain", {"expected": None}, [_routed(None)]).passed
    assert not _run("routed_domain", {"expected": None}, [_routed("legal")]).passed
    assert not _run("routed_domain", {"expected": "legal"}, [_routed(None)]).passed


def test_EFF_07_routed_domain_takes_expected_from_ground_truth_when_no_arg():
    assert _run("routed_domain", {}, [_routed("legal")], ground_truth={"domain": "legal"}).passed
    assert _run("routed_domain", {}, [_routed(None)], ground_truth={"domain": None}).passed
    assert not _run("routed_domain", {}, [_routed("legal")], ground_truth={"domain": "finance"}).passed


def test_EFF_07_routed_domain_fails_without_an_expected_domain_or_a_routed_event():
    assert not _run("routed_domain", {}, [_routed("legal")], ground_truth={"ok": True}).passed
    result = _run("routed_domain", {"expected": "legal"}, [make_event(type="world.started")])
    assert not result.passed and "question.routed" in result.cause


def test_EFF_07_routed_domain_every_routed_event_must_match_unless_card_id_picks_one():
    events = [_routed("legal", _CARD_A), _routed("finance", _CARD_B)]
    assert not _run("routed_domain", {"expected": "legal"}, events).passed
    assert _run("routed_domain", {"expected": "legal", "card_id": _CARD_A}, events).passed
    assert not _run("routed_domain", {"expected": "legal", "card_id": _CARD_B}, events).passed
    assert not _run("routed_domain", {"expected": "legal", "card_id": "nope"}, events).passed


def test_EFF_07_routed_domain_ignores_a_malformed_event_data_without_raising():
    events = [make_event(type="question.routed", data="oops"), make_event(type="question.routed", data=None)]
    assert not _run("routed_domain", {"expected": "legal"}, events).passed


def test_EFF_07_routed_domain_null_expected_never_passes_when_the_domain_is_absent():
    absent = [make_event(type="question.routed", data={"card_id": _CARD_A})]  # no "domain" key: not the same as null
    result = _run("routed_domain", {"expected": None}, absent)
    assert not result.passed and "no domain" in result.cause
    for data in ("garbage", None, []):
        assert not _run("routed_domain", {"expected": None}, [make_event(type="question.routed", data=data)]).passed
    mixed = [_routed(None), make_event(type="question.routed", data={"card_id": _CARD_B})]
    assert not _run("routed_domain", {"expected": None}, mixed).passed


def test_EFF_07_answered_from_decision_passes_on_a_cited_decision():
    assert _run("answered_from_decision", {}, [_answered("decision", _DECISION)]).passed
    assert _run("answered_from_decision", {"decision_id": _DECISION}, [_answered("decision", _DECISION)]).passed


def test_EFF_07_answered_from_decision_fails_for_a_person_answer_a_wrong_citation_or_none():
    assert not _run("answered_from_decision", {}, [_answered("person")]).passed
    assert not _run("answered_from_decision", {}, []).passed
    assert not _run("answered_from_decision", {}, [_answered("decision", None)]).passed  # a citation is required
    wrong = _run(
        "answered_from_decision", {"decision_id": _DECISION}, [_answered("decision", "01J8Z3K4M5N6P7Q8R9S0T1V2W6")]
    )
    assert not wrong.passed and _DECISION in wrong.cause


def test_EFF_07_answered_from_decision_expected_false_asserts_a_person_was_asked():
    assert _run("answered_from_decision", {"expected": False}, [_answered("person")]).passed
    assert _run("answered_from_decision", {"expected": False}, [_answered("team_lead")]).passed
    assert not _run("answered_from_decision", {"expected": False}, [_answered("decision", _DECISION)]).passed


def test_EFF_07_answered_from_decision_expected_false_never_passes_vacuously():
    for events in ([], [make_event(type="world.started")], [make_event(type="question.answered", data={})]):
        result = _run("answered_from_decision", {"expected": False}, events)
        assert not result.passed and "no question.answered" in result.cause


def test_EFF_07_route_checks_accept_the_contract_fixtures():
    routed = json.loads((REPO_ROOT / "contracts/fixtures/events/valid/question.routed.json").read_text("utf-8"))
    answered_path = REPO_ROOT / "contracts/fixtures/events/valid/question.answered--from_decision.json"
    answered = json.loads(answered_path.read_text("utf-8"))
    assert _run("routed_domain", {"expected": None}, [routed]).passed
    assert _run("answered_from_decision", {"decision_id": answered["data"]["decision_id"]}, [answered]).passed


def test_EFF_07_route_checks_use_the_args_of_their_own_entry_when_a_case_lists_them_twice():
    case = _case("routed_domain", {"expected": "legal"})
    case.checks.append({"check": "routed_domain", "args": {"expected": "finance"}})
    outcome = Outcome(events=[_routed("finance")], outputs={})
    assert get("routed_domain")(case, outcome, {"expected": "finance"}).passed
    assert not get("routed_domain")(case, outcome, {"expected": "legal"}).passed
    assert not get("routed_domain")(case, outcome).passed  # which entry is meant is unknown


@pytest.mark.parametrize("name", ["routed_domain", "answered_from_decision"])
def test_EFF_07_route_checks_never_raise_on_odd_event_shapes(name):
    events = [{"type": "question.routed"}, {"type": "question.answered", "data": []}, {}]
    assert _run(name, {"expected": "legal"}, events).passed is False
