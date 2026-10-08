"""Acceptance tests covering every EV-* requirement in PRD 2.4, 3.5, 19.2, 19.4 and event rule EV-16."""

import ast
import functools
import json
import re

import pytest
from _evals_lib import REPO_ROOT, add_case, make_event
from _metrics_lib import (
    CLAIM_SENTENCE,
    alert_raised,
    approval_requested,
    blocked,
    budget_requested,
    completed,
    compute,
    escalated,
    handoff,
    memory_hit,
    metrics,
    metrics_report,
    only,
    planned,
    rec,
    recovered,
)
from tilo_evals import Case, EvalsConfig, load_cases, run_pass
from tilo_evals.__main__ import main
from tilo_evals.checks import Outcome, get
from tilo_metering.prices import PriceBook
from tilo_metering.savings import InconsistentMemoryHit

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_PRD_PATH = REPO_ROOT / "docs" / "prd" / "tilo-prd-v2.md"
_EVENT_RULES_PATH = REPO_ROOT / "contracts" / "event.rules.md"
_PILOT_FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures" / "pilot"
_METER_FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures" / "meter"


def _cfg(repo) -> EvalsConfig:
    return EvalsConfig.load(str(repo / "config" / "evals.yaml"))


@functools.cache
def _all_cases() -> tuple[Case, ...]:
    return tuple(load_cases(str(_CASES_DIR)))


def _cases_by_group(group: str) -> list[Case]:
    return [c for c in _all_cases() if c.group == group]


def test_PRD_19_2_EV_01_task_success_e_res_coverage_and_gate_1_replay(fake_repo) -> None:
    e_res = _cases_by_group("E-RES")
    assert len(e_res) == 10 and all("EV-01" in c.measures and c.status == "ready" for c in e_res)

    add_case(
        fake_repo,
        "E-RES-01",
        [completed(4)],
        measures=["EV-01"],
        ground_truth={"monthly": 49},
        outputs={"monthly": 49},
        checks=[{"check": "equals_ground_truth", "args": {"field": "monthly", "tolerance": 0}}],
    )
    add_case(
        fake_repo,
        "E-RES-02",
        [completed(4)],
        measures=["EV-01"],
        ground_truth={"monthly": 49},
        outputs={"monthly": 99},
        checks=[{"check": "equals_ground_truth", "args": {"field": "monthly", "tolerance": 0}}],
    )
    add_case(
        fake_repo,
        "E-RED-01",
        [make_event(1, "alert.raised")],
        measures=["EV-09"],
        checks=[{"check": "flagged_or_blocked", "args": {}}],
    )
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records), "EV-01", "recorded")
    assert (row.status, row.n, row.of, row.value) == ("computed", 1, 2, pytest.approx(0.5))
    assert "85%" in row.target and "60%" in row.target


def test_PRD_19_2_EV_02_time_to_first_plan_e_plan_coverage_and_gate_6_live_honesty(fake_repo) -> None:
    e_plan = _cases_by_group("E-PLAN")
    assert len(e_plan) == 10 and all("EV-02" in c.measures for c in e_plan)

    cov = metrics().coverage_from([c.measures for c in e_plan], [])
    assert cov["EV-02"] == (10, 0)
    add_case(fake_repo, "E-PLAN-01", [planned(8, 12, "town"), completed(10)], measures=["EV-02", "EV-03"])
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records, coverage=cov), "EV-02", None)
    assert (row.status, row.value, row.n) == ("needs_live_or_pilot", None, 0)
    assert "12 s" in row.target and "25 s" in row.target
    assert "10 cases measure this, 0 recorded" in row.note


def test_PRD_19_2_EV_03_estimate_accuracy_e_plan_measures_and_midpoint_ratio(fake_repo) -> None:
    e_plan = _cases_by_group("E-PLAN")
    assert len(e_plan) == 10 and all("EV-03" in c.measures and c.notes and "EV-03" in c.notes for c in e_plan)

    add_case(fake_repo, "E-PLAN-01", [planned(8, 12), completed(9)], measures=["EV-03"])
    add_case(fake_repo, "E-PLAN-02", [planned(8, 12), completed(11)], measures=["EV-03"])
    add_case(fake_repo, "E-PLAN-03", [planned(8, 12), completed(15)], measures=["EV-03"])
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records), "EV-03", "recorded")
    assert (row.status, row.n, row.value) == ("computed", 3, pytest.approx(1.1))
    assert "2 of 3" in row.note and "±25%" in row.target


def test_PRD_19_2_EV_04_intervention_rate_town_tier_unplanned_cards_only(fake_repo) -> None:
    add_case(
        fake_repo,
        "E-PLAN-01",
        [
            planned(8, 12, "town"),
            blocked("U1"),
            budget_requested(),
            escalated(),
            approval_requested(),
            alert_raised(),
            completed(10),
        ],
        measures=["EV-04"],
    )
    add_case(
        fake_repo,
        "E-PLAN-02",
        [planned(8, 12, "town"), blocked("U1"), completed(9)],
        measures=["EV-04"],
    )
    add_case(
        fake_repo,
        "E-PLAN-03",
        [planned(4, 6, "village"), blocked("U1"), blocked("U2"), blocked("U3"), blocked("U4"), completed(5)],
        measures=["EV-04"],
    )
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records), "EV-04", "recorded")
    assert (row.status, row.n, row.value) == ("computed", 2, pytest.approx(2.0))
    assert "2" in row.target and "Town" in row.target


def test_PRD_19_2_EV_05_groundedness_e_res_autorater_check_and_gate_2_pending_honesty(fake_repo) -> None:
    e_res = _cases_by_group("E-RES")
    assert len(e_res) == 10
    for case in e_res:
        assert "EV-05" in case.measures
        assert any(c.get("check") == "groundedness" and c.get("kind") == "autorater" for c in case.checks)

    add_case(
        fake_repo,
        "E-RES-01",
        [completed(4)],
        measures=["EV-01", "EV-05"],
        checks=[{"check": "groundedness", "kind": "autorater", "args": {"field": "citations", "sources": []}}],
    )
    pass_res = run_pass(pass_kind="full", config=_cfg(fake_repo))
    assert pass_res.ran[0].pending_autoraters == ["groundedness"]
    records = metrics().records_from_pass(pass_res)
    assert records[0].passed is None
    ev05 = only(compute(records), "EV-05", None)
    assert (ev05.status, ev05.value, ev05.n) == ("needs_live_or_pilot", None, 0)
    assert "90%" in ev05.target and "autorater" in ev05.method.lower()


def test_PRD_19_2_EV_06_recovery_rate_recovered_vs_escalated_buildings(fake_repo) -> None:
    add_case(
        fake_repo,
        "E-PLAN-01",
        [
            recovered("U1"),
            blocked("U2"),
            blocked("U3"),
            recovered("U3"),
            completed(6),
        ],
        measures=["EV-06"],
    )
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records), "EV-06", "recorded")
    assert (row.status, row.n, row.of, row.value) == ("computed", 1, 3, pytest.approx(1 / 3))
    assert "70%" in row.target


def test_PRD_19_2_EV_07_cost_per_task_by_tier_and_usd_from_pricebook(fake_repo) -> None:
    add_case(fake_repo, "E-PLAN-01", [planned(8, 12, "town"), completed(10)], measures=["EV-07"])
    add_case(fake_repo, "E-PLAN-02", [planned(4, 6, "village"), completed(6)], measures=["EV-07"])
    credit_usd = PriceBook.load(REPO_ROOT / "config" / "prices.yaml").credit_usd
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records, credit_usd=credit_usd), "EV-07", "recorded")
    assert (row.status, row.n, row.value) == ("computed", 2, pytest.approx(8.0))
    assert "town" in row.note.lower() and "village" in row.note.lower()
    assert f"{8 * credit_usd:.2f}" in row.note and row.target == "Reported"


def test_PRD_19_2_EV_08_memory_reuse_saved_share_of_first_run_cost(fake_repo) -> None:
    add_case(
        fake_repo,
        "E-PLAN-01",
        [memory_hit(12.0, 2.0), memory_hit(8.0, 6.0), completed(10.0)],
        measures=["EV-08"],
    )
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records), "EV-08", "recorded")
    assert (row.status, row.n, row.value) == ("computed", 2, pytest.approx(0.6))
    assert "50%" in row.target
    with pytest.raises(InconsistentMemoryHit):
        compute([rec(memory_hit(10.0, 3.0, saved=9.0))])


def test_PRD_19_2_EV_09_injection_resistance_e_red_deploy_gate_3_and_check_teeth(fake_repo) -> None:
    e_red = _cases_by_group("E-RED")
    assert len(e_red) == 14 and all(c.deploy_gate and "EV-09" in c.measures for c in e_red)

    red_checks = [{"check": "no_side_effects", "args": {}}, {"check": "flagged_or_blocked", "args": {}}]
    add_case(
        fake_repo,
        "E-RED-01",
        [make_event(1, "alert.raised")],
        measures=["EV-09"],
        deploy_gate=True,
        checks=red_checks,
    )
    add_case(
        fake_repo,
        "E-RED-02",
        [make_event(1, "alert.raised"), make_event(2, "data.transfer", data={"outbox_id": "ob_1"})],
        measures=["EV-09"],
        deploy_gate=False,
        checks=red_checks,
    )
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records), "EV-09", "recorded")
    assert (row.status, row.n, row.of, row.value) == ("computed", 3, 4, pytest.approx(0.75))
    assert "100%" in row.target


def test_PRD_19_2_EV_10_handoff_continuity_e_hand_deploy_gate_4_and_rework_check(fake_repo) -> None:
    e_hand = _cases_by_group("E-HAND")
    assert len(e_hand) == 20 and all("EV-10" in c.measures for c in e_hand)
    assert [c.id for c in e_hand if c.deploy_gate] == [f"E-HAND-{i:02d}" for i in range(1, 6)]

    hand_checks = [{"check": "equals_ground_truth", "args": {"field": "rework"}}]
    add_case(
        fake_repo,
        "E-HAND-01",
        [handoff(True)],
        measures=["EV-10"],
        ground_truth={"rework": False},
        outputs={"rework": False},
        checks=hand_checks,
    )
    add_case(
        fake_repo,
        "E-HAND-02",
        [handoff(True)],
        measures=["EV-10"],
        ground_truth={"rework": False},
        outputs={"rework": True},
        checks=hand_checks,
    )
    records = metrics().records_from_pass(run_pass(pass_kind="full", config=_cfg(fake_repo)))
    row = only(compute(records), "EV-10", "recorded")
    assert (row.status, row.n, row.of, row.value) == ("computed", 1, 2, pytest.approx(0.5))
    assert "from case passes" in row.note and "95%" in row.target


def test_PRD_19_2_EV_11_time_saved_estimate_requires_pilot_attention_spans() -> None:
    row = only(compute([]), "EV-11", None)
    assert (row.status, row.value, row.n) == ("needs_live_or_pilot", None, 0)
    assert "section 14" in row.method.lower() and "attention" in row.method.lower()
    assert "Reported" in row.target


def test_PRD_19_2_EV_12_time_reinvested_requires_pilot_exit_survey() -> None:
    row = only(compute([]), "EV-12", None)
    assert (row.status, row.value, row.n) == ("needs_live_or_pilot", None, 0)
    assert "survey" in row.method.lower() and "self-reported" in (row.method + row.target).lower()


def test_PRD_19_2_EV_13_autopilot_draft_acceptance_requires_pilot_unedited_sends() -> None:
    row = only(compute([]), "EV-13", None)
    assert (row.status, row.value, row.n) == ("needs_live_or_pilot", None, 0)
    assert "pilot" in row.method.lower() and "unedited" in row.method.lower() and "70%" in row.target


def test_PRD_19_2_EV_14_expert_load_e_route_coverage_and_pilot_answer_time() -> None:
    e_route = _cases_by_group("E-ROUTE")
    assert len(e_route) == 20 and all("EV-14" in c.measures for c in e_route)
    cov = metrics().coverage_from([c.measures for c in e_route], [])
    assert cov["EV-14"] == (20, 0)
    row = only(compute([], coverage=cov), "EV-14", None)
    assert (row.status, row.value, row.n) == ("needs_live_or_pilot", None, 0)
    assert "2 min" in row.target and "5%" in row.target
    assert "20 cases measure this, 0 recorded" in row.note


def test_PRD_19_2_EV_15_channel_latency_whatsapp_out_of_scope_and_assistant_panel_cases() -> None:
    e_chn = _cases_by_group("E-CHN")
    assert len(e_chn) == 30 and all(c.inputs.get("channel") == "assistant_panel" for c in e_chn)
    row = only(compute([]), "EV-15", None)
    assert (row.status, row.value, row.n) == ("needs_live_or_pilot", None, 0)
    assert "15 s" in row.target and "WhatsApp" in row.note and "5 Oct 2026" in row.note


def test_PRD_19_2_EV_16_tokens_cached_event_rule_and_cache_hit_rate_in_replay(fake_repo) -> None:
    good = make_event(
        seq=1,
        type="agent.working",
        trace={"model_role": "specialist", "profile": "small", "tokens_in": 1000, "tokens_cached": 400},
    )
    bad = make_event(
        seq=1,
        type="agent.working",
        trace={"model_role": "specialist", "profile": "small", "tokens_in": 100, "tokens_cached": 101},
    )
    add_case(fake_repo, "E-PLAN-01", [good], credits=1.0)
    add_case(fake_repo, "E-PLAN-02", [bad], credits=1.0)
    assert main(["run", "--pass", "full", "--results-json", "results.json"]) == 0
    data = json.loads((fake_repo / "results.json").read_text(encoding="utf-8"))
    assert data["ran"] == ["E-PLAN-01"] and data["not_runnable"] == ["E-PLAN-02"]
    assert "tokens_cached" in data["not_runnable_reasons"]["E-PLAN-02"]
    assert data["cache_hit_rate_per_role"]["specialist"]["rate"] == pytest.approx(0.4)


def test_PRD_19_2_EV_G1_glanceability_study_never_invented_in_offline_metrics() -> None:
    rows = compute([])
    md = metrics_report().render_markdown(rows, build_hash="abc1234", now_utc="2026-10-06T00:00:00Z")
    payload = metrics_report().render_json(rows)
    assert CLAIM_SENTENCE in md
    assert all(r["id"] != "EV-G1" for r in payload["rows"])
    assert "EV-G1" in _PRD_PATH.read_text(encoding="utf-8")


def test_PRD_19_2_EV_G2_human_baseline_drives_meter_time_saved_contract_and_EV_11() -> None:
    meter_schema = json.loads((REPO_ROOT / "contracts" / "meter.schema.json").read_text(encoding="utf-8"))
    time_saved_def = meter_schema["$defs"]["time_saved"]
    assert "EV-G2" in time_saved_def["description"]
    valid_path = sorted((_METER_FIXTURES_DIR / "valid").glob("*.json"))[0]
    valid_meter = json.loads(valid_path.read_text(encoding="utf-8"))
    case = _cases_by_group("E-PLAN")[0]
    assert get("schema_valid")(
        case, Outcome(events=[], outputs={"m": valid_meter}), {"field": "m", "schema": "meter.schema.json"}
    ).passed
    bad_meter = {**valid_meter, "time_saved": {k: v for k, v in valid_meter["time_saved"].items() if k != "method_url"}}
    assert not get("schema_valid")(
        case, Outcome(events=[], outputs={"m": bad_meter}), {"field": "m", "schema": "meter.schema.json"}
    ).passed


def test_PRD_19_2_EV_G3_pilot_programme_consent_and_records_match_pilot_schema() -> None:
    case = _cases_by_group("E-PLAN")[0]
    valid_pilot = json.loads((_PILOT_FIXTURES_DIR / "valid" / "one_of_each_record.json").read_text(encoding="utf-8"))
    invalid_study = json.loads(
        (_PILOT_FIXTURES_DIR / "invalid" / "consent_study_not_ev_g3.json").read_text(encoding="utf-8")
    )
    assert valid_pilot["consent"]["study"] == "EV-G3"
    assert get("schema_valid")(
        case, Outcome(events=[], outputs={"p": valid_pilot}), {"field": "p", "schema": "pilot.schema.json"}
    ).passed
    assert not get("schema_valid")(
        case, Outcome(events=[], outputs={"p": invalid_study}), {"field": "p", "schema": "pilot.schema.json"}
    ).passed


def test_PRD_19_2_every_prd_ev_id_has_a_test_with_its_id_in_the_name() -> None:
    prd_ids = set(re.findall(r"\bEV-(?:[0-9]{2}|G[1-3])\b", _PRD_PATH.read_text(encoding="utf-8")))
    rule_ids = set(re.findall(r"\bEV-[0-9]{2}\b", _EVENT_RULES_PATH.read_text(encoding="utf-8")))
    expected_tokens = {ev_id.replace("-", "_") for ev_id in (prd_ids | rule_ids)}
    assert expected_tokens == {f"EV_{i:02d}" for i in range(1, 17)} | {"EV_G1", "EV_G2", "EV_G3"}

    test_names: set[str] = set()
    for path in sorted((REPO_ROOT / "evals" / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                test_names.add(node.name)

    missing = {tok for tok in expected_tokens if not any(tok in name for name in test_names)}
    assert not missing, f"EV IDs missing from evals/tests function names: {sorted(missing)}"
