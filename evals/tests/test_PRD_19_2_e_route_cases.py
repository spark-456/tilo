"""Acceptance tests for E-ROUTE eval cases (PRD 19.2, 8.3; FR-AGT-06, FR-AGT-07, EV-14, EFF-07)."""

import re
import subprocess
import sys
from typing import Any

import yaml
from _evals_lib import REPO_ROOT, make_event
from test_PRD_19_2_eval_set_structure import DENYLIST_BRANDS_RE, REAL_ROUTING_RE
from tilo_evals import Case, load_cases
from tilo_evals.checks import Outcome, get

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_ROUTE_FIXTURE_REL = "evals/fixtures/route/routing_scenarios.yaml"
_ROUTE_FIXTURE_PATH = REPO_ROOT / _ROUTE_FIXTURE_REL
_ULID_RE = re.compile(r"^01[0-9A-HJKMNP-TV-Z]{24}$")
_GATE_TAG_RE = re.compile(r"\(gate\s*\d+\)", re.IGNORECASE)


def _e_route_cases() -> list[Case]:
    return [c for c in load_cases(str(_CASES_DIR)) if c.group == "E-ROUTE"]


def _load_fixture_scenarios() -> dict[str, dict[str, Any]]:
    assert _ROUTE_FIXTURE_PATH.is_file(), f"missing E-ROUTE fixture {_ROUTE_FIXTURE_REL}"
    data = yaml.safe_load(_ROUTE_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("scenarios"), dict)
    return data["scenarios"]


def _matching_decision(case: Case, scenario: dict[str, Any], routed_domain: str | None) -> dict[str, Any] | None:
    asked_at = case.inputs["asked_at"]
    world_id = case.inputs["world_id"]
    district = case.inputs["district"]
    topic_key = case.inputs["topic_key"]
    active_tl_ids = {tl["id"]: tl for tl in scenario.get("team_leads", [])}
    for dec in scenario.get("decisions", []):
        if dec.get("topic_key") != topic_key:
            continue
        if dec.get("created_at", "") >= asked_at:
            continue
        if dec.get("expires_at") is not None and dec["expires_at"] <= asked_at:
            continue
        worlds = dec["scope"]["worlds"]
        if worlds != "all" and world_id not in worlds:
            continue
        districts = dec["scope"]["districts"]
        if districts != "all" and district not in districts:
            continue
        ans_by = dec["answered_by"]
        if ans_by["by"] == "team_lead":
            tl = active_tl_ids.get(ans_by["ref"])
            if tl is None or tl["user"] != ans_by["user"] or tl["domain"] != dec["domain"]:
                continue
            if dec["domain"] != routed_domain:
                continue
        return dec
    return None


def test_PRD_19_2_e_route_twenty_cases_load_with_required_measures_and_checks() -> None:
    cases = _e_route_cases()
    assert [c.id for c in cases] == [f"E-ROUTE-{i:02d}" for i in range(1, 21)]
    for case in cases:
        assert (case.status, case.deploy_gate, case.recording) == ("ready", False, None)
        assert {"FR-AGT-06", "FR-AGT-07", "EV-14"} <= set(case.measures)
        assert isinstance(case.inputs.get("task"), str) and len(case.inputs["task"].strip()) >= 25
        assert isinstance(case.inputs.get("question"), str) and len(case.inputs["question"].strip()) >= 25
        assert _ULID_RE.fullmatch(str(case.inputs.get("card_id", ""))), f"{case.id}: invalid card_id ULID"
        assert case.inputs.get("context_fixture") == _ROUTE_FIXTURE_REL
        check_names = [c["check"] for c in case.checks]
        assert check_names == ["routed_domain", "answered_from_decision"]
        assert case.notes and "routing_scenarios.yaml" in case.notes and "CL-EVID" in case.notes


def test_PRD_19_2_e_route_domain_routing_and_owner_fallback_match_parsed_fixture() -> None:
    cases = _e_route_cases()
    scenarios = _load_fixture_scenarios()
    assert len(cases) == 20 and set(scenarios) == {c.id for c in cases}
    routed_domains: list[str | None] = []
    for case in cases:
        scenario = scenarios[case.id]
        configured = {tl["domain"] for tl in scenario.get("team_leads", [])}
        q_domain = case.inputs["question_domain"]
        expected_domain = q_domain if q_domain in configured else None
        routed_domains.append(expected_domain)
        assert case.ground_truth is not None
        assert case.ground_truth["domain"] == expected_domain, f"{case.id}: domain mismatch vs fixture"
        routed_check = case.checks[0]
        assert routed_check == {
            "check": "routed_domain",
            "args": {"expected": expected_domain, "card_id": case.inputs["card_id"]},
        }
    assert routed_domains.count(None) == 6, "expected 6 owner-fallback (null domain) cases"
    assert {"security", "finance", "legal", "automation", "research"} <= {d for d in routed_domains if d is not None}


def test_PRD_19_2_e_route_repeat_detection_and_decision_citations_match_parsed_fixture() -> None:
    cases = _e_route_cases()
    scenarios = _load_fixture_scenarios()
    assert len(cases) == 20
    repeat_hits = 0
    for case in cases:
        scenario = scenarios[case.id]
        gt = case.ground_truth
        assert gt is not None
        matched = _matching_decision(case, scenario, gt["domain"])
        ans_check = case.checks[1]
        card_id = case.inputs["card_id"]
        routed_ev = make_event(type="question.routed", data={"card_id": card_id, "domain": gt["domain"]})
        wrong_routed = make_event(type="question.routed", data={"card_id": card_id, "domain": "wrong_domain"})
        assert get("routed_domain")(case, Outcome(events=[routed_ev], outputs={}), case.checks[0]["args"]).passed
        assert not get("routed_domain")(case, Outcome(events=[wrong_routed], outputs={}), case.checks[0]["args"]).passed

        if matched is None:
            assert gt["answered_from_decision"] is False and gt["decision_id"] is None
            assert ans_check == {"check": "answered_from_decision", "args": {"expected": False}}
            person_ev = make_event(type="question.answered", data={"answered_by": "team_lead", "decision_id": None})
            dec_ev = make_event(
                type="question.answered",
                data={"answered_by": "decision", "decision_id": "01J8Z3K4M5N6P7Q8R9S0T1V2W5"},
            )
            assert get("answered_from_decision")(
                case, Outcome(events=[person_ev], outputs={}), ans_check["args"]
            ).passed
            assert not get("answered_from_decision")(
                case, Outcome(events=[dec_ev], outputs={}), ans_check["args"]
            ).passed
        else:
            repeat_hits += 1
            dec_id = matched["id"]
            assert _ULID_RE.fullmatch(dec_id)
            assert gt["answered_from_decision"] is True and gt["decision_id"] == dec_id
            assert ans_check == {
                "check": "answered_from_decision",
                "args": {"expected": True, "decision_id": dec_id},
            }
            good_ev = make_event(type="question.answered", data={"answered_by": "decision", "decision_id": dec_id})
            bad_ev = make_event(type="question.answered", data={"answered_by": "person", "decision_id": None})
            assert get("answered_from_decision")(case, Outcome(events=[good_ev], outputs={}), ans_check["args"]).passed
            assert not get("answered_from_decision")(
                case, Outcome(events=[bad_ev], outputs={}), ans_check["args"]
            ).passed
    assert repeat_hits == 10, f"expected 10 repeat-decision cases and 10 person-asked cases, got {repeat_hits}"


def test_PRD_19_2_e_route_brand_routing_number_and_fictional_host_denylist() -> None:
    cases = _e_route_cases()
    assert len(cases) == 20
    all_paths = [c.path for c in cases] + [_ROUTE_FIXTURE_PATH]
    for case in cases:
        assert _GATE_TAG_RE.search(case.title) is None, f"{case.id}: gate tag found in title {case.title!r}"
    for path in all_paths:
        text = path.read_text(encoding="utf-8")
        brand_match = DENYLIST_BRANDS_RE.search(f"{path.name}\n{text}")
        assert brand_match is None, f"{path.name}: real/sample brand {brand_match.group(0)!r} found"
        routing_match = REAL_ROUTING_RE.search(text)
        assert routing_match is None, f"{path.name}: routing/account number {routing_match.group(0)!r} found"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"), *(str(p) for p in all_paths)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
