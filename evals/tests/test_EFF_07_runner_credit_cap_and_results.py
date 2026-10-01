"""EFF-07 runner tests (PRD 6.6 "passes stop at a credit cap", MT-09, PRD 19.3 and 19.5 reporting).

The CLI has no flag for the cases root or config path, so each test builds a fake repo under tmp_path and
chdirs into it (`fake_repo`); recordings are replayed, so nothing here makes a paid call.
"""

import json
import re

import pytest
from conftest import add_case, make_event, write_evals_config
from tilo_evals.__main__ import main
from tilo_evals.config import EvalsConfig
from tilo_evals.runner import run_pass


def _config(repo, **caps):
    return EvalsConfig.load(str(write_evals_config(repo / "config", credit_cap=caps or None)))


def _json(repo):
    return json.loads((repo / "results.json").read_text(encoding="utf-8"))


def test_EFF_07_pass_stops_at_credit_cap_lists_rest_and_exits_3(fake_repo):
    write_evals_config(fake_repo / "config", credit_cap={"full": 100, "smoke": 100, "gate": 100})
    for n in (1, 2, 3):
        add_case(fake_repo, f"E-PLAN-0{n}", credits=40.0)

    code = main(["run", "--pass", "full", "--results-json", "results.json"])

    data = _json(fake_repo)
    assert code == 3, "a partial pass exits 3"
    assert data["stopped_at_cap"] is True and data["spent"] == 80.0
    assert data["ran"] == ["E-PLAN-01", "E-PLAN-02"] and data["not_run"] == ["E-PLAN-03"]
    assert "E-PLAN-03" in data["stop_reason"] and "100" in data["stop_reason"], "the report says why it stopped"
    md = (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")
    assert "E-PLAN-03" in md and "cap" in md.lower()


def test_EFF_07_cap_is_never_exceeded_and_a_reached_cap_starts_no_further_case(fake_repo):
    config = _config(fake_repo, full=100, smoke=100, gate=100)
    for n, credits in enumerate((60, 40, 0), start=1):  # spent reaches 100 exactly; the 0-credit case must not start
        add_case(fake_repo, f"E-RED-0{n}", credits=float(credits))

    result = run_pass(pass_kind="full", config=config)

    assert [r.case.id for r in result.ran] == ["E-RED-01", "E-RED-02"] and result.spent == 100.0
    assert [c.id for c in result.not_run] == ["E-RED-03"] and result.stopped_at_cap


def test_EFF_07_a_single_case_over_the_cap_runs_nothing(fake_repo):
    config = _config(fake_repo, full=10, smoke=10, gate=10)
    add_case(fake_repo, "E-RED-01", credits=11.0)
    result = run_pass(pass_kind="full", config=config)
    assert result.ran == [] and result.spent == 0.0 and result.stopped_at_cap


def test_EFF_07_summary_less_recording_costs_its_event_credits_and_stops_at_cap(fake_repo):
    write_evals_config(fake_repo / "config", credit_cap={"full": 2000, "smoke": 100, "gate": 100})
    for n in (1, 2, 3):
        event = make_event(type="alert.raised", credits=1500.0, trace={"model_role": "worker"})
        add_case(fake_repo, f"E-RED-0{n}", [event], credits=None, checks=[{"check": "flagged_or_blocked", "args": {}}])

    code = main(["run", "--pass", "full", "--results-json", "results.json"])

    data = _json(fake_repo)
    assert code == 3 and data["ran"] == ["E-RED-01"] and data["not_run"] == ["E-RED-02", "E-RED-03"]
    assert data["spent"] == 1500.0


def test_EFF_07_skeleton_and_missing_recording_cases_are_not_runnable_with_a_reason(fake_repo):
    add_case(fake_repo, "E-PLAN-01", status="skeleton", ground_truth=None, recording=None)
    add_case(fake_repo, "E-PLAN-02", recording=None)
    add_case(fake_repo, "E-PLAN-03")

    main(["run", "--pass", "full", "--results-json", "results.json"])

    data = _json(fake_repo)
    assert data["not_runnable"] == ["E-PLAN-01", "E-PLAN-02"] and data["ran"] == ["E-PLAN-03"]
    assert data["not_runnable_reasons"]["E-PLAN-01"] == "status skeleton"
    assert "E-PLAN-02: no recording" in (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")


def test_EFF_07_smoke_runs_one_ready_case_per_group_and_gate_repeats_deploy_gate_cases(fake_repo):
    for case_id in ("E-PLAN-01", "E-PLAN-02", "E-RED-01"):
        add_case(fake_repo, case_id, deploy_gate=case_id == "E-RED-01")
    config = EvalsConfig.load("config/evals.yaml")

    smoke = run_pass(pass_kind="smoke", config=config)
    gate = run_pass(pass_kind="gate", config=config)

    assert [r.case.id for r in smoke.ran] == ["E-PLAN-01", "E-RED-01"]
    assert [r.case.id for r in gate.ran] == ["E-RED-01"] * 3, "deploy_gate_repeats from config/evals.yaml"


def test_EFF_07_report_counts_first_per_group_and_never_shows_a_model_id(fake_repo):
    trace = {"model_role": "specialist", "profile": "small", "tokens_in": 1, "tokens_out": 1}
    add_case(fake_repo, "E-PLAN-01", [make_event(trace=trace, credits=10.0)], credits=10.0)
    bad = make_event(type="data.transfer", authz={"by": "person", "ref": "u_owner"})
    add_case(fake_repo, "E-PLAN-02", [bad], credits=10.0)
    add_case(
        fake_repo, "E-RED-01", [make_event(type="alert.raised")], checks=[{"check": "flagged_or_blocked", "args": {}}]
    )

    code = main(["run", "--pass", "full", "--results-json", "results.json"])

    md = (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")
    assert code == 1, "a failed case exits 1"
    assert "2 of 3 passed (67%)" in md and md.index("2 of 3 passed") < md.index("67%")
    assert "- E-PLAN: 1 of 2 passed (50%)" in md and "- E-RED: 1 of 1 passed (100%)" in md
    assert "specialist -> small" in md and "Build hash: `" in md and "10 credits" not in md.split("Roles")[0]
    assert re.search(r"### Failures grouped by cause\n- .*side-effect.*: E-PLAN-02", md)
    assert _json(fake_repo)["by_group"]["E-PLAN"]["failed"] == 1
    assert _json(fake_repo)["cost_per_role"] == {"specialist": 10.0}


def test_EFF_07_cli_prints_counts_per_group_and_why_it_stopped(fake_repo, capsys):
    write_evals_config(fake_repo / "config", credit_cap={"full": 5, "smoke": 5, "gate": 5})
    for case_id in ("E-PLAN-01", "E-PLAN-02", "E-RED-01"):
        add_case(fake_repo, case_id, credits=3.0)

    code = main(["run", "--pass", "full"])

    out = capsys.readouterr().out
    assert code == 3
    assert out.startswith("full pass: 1 of 1 passed (100%), 3 credits")
    assert "- E-PLAN: 1 of 1 passed (100%); 1 not run (cap)" in out
    assert "stopped: credit cap for the full pass is 5" in out and "2 case(s) not run" in out


def test_EFF_07_results_md_keeps_one_section_per_pass_kind_and_replaces_a_rerun(fake_repo):
    add_case(fake_repo, "E-PLAN-01")
    for kind in ("smoke", "full", "smoke"):
        assert main(["run", "--pass", kind]) == 0
    md = (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")
    assert md.count("## Pass: smoke") == 1 and md.count("## Pass: full") == 1
    assert "\r" not in md


def test_EFF_07_a_check_that_raises_fails_the_case_without_crashing_the_pass(fake_repo):
    add_case(fake_repo, "E-PLAN-01", checks=[{"check": "equals_ground_truth", "args": {}}])  # no `field` arg
    add_case(fake_repo, "E-PLAN-02")
    result = run_pass(pass_kind="full", config=EvalsConfig.load("config/evals.yaml"))
    assert [r.passed for r in result.ran] == [False, True] and "KeyError" in result.ran[0].cause


def test_EFF_07_a_failure_cause_is_one_bounded_line(fake_repo):
    outputs = {"x": "line one\n## Pass: smoke\n" + "y" * 1000}
    add_case(
        fake_repo,
        "E-PLAN-01",
        outputs=outputs,
        ground_truth={"x": "other"},
        checks=[{"check": "equals_ground_truth", "args": {"field": "x"}}],
    )
    result = run_pass(pass_kind="full", config=EvalsConfig.load("config/evals.yaml"))
    assert "\n" not in result.ran[0].cause and len(result.ran[0].cause) <= 300


def test_EFF_07_autorater_checks_are_pending_and_never_a_pass(fake_repo):
    only = [{"check": "style_rubric", "args": {}, "kind": "autorater"}]
    add_case(fake_repo, "E-MAIL-01", checks=only)
    add_case(fake_repo, "E-MAIL-02", checks=[{"check": "no_side_effects", "args": {}}, *only])

    code = main(["run", "--pass", "full", "--results-json", "results.json"])

    data = _json(fake_repo)
    assert code == 0 and data["pending_autorater"] == ["E-MAIL-01"] and data["passed"] == ["E-MAIL-02"]
    assert "1 pending autorater (not counted as passed)" in (fake_repo / "evals" / "results.md").read_text("utf-8")


@pytest.mark.parametrize("bad_credits", [-1000, float("nan")], ids=["negative", "nan"])
def test_EFF_07_bad_recording_credits_do_not_corrupt_the_credit_cap(fake_repo, bad_credits):
    config = _config(fake_repo, full=100, smoke=100, gate=100)
    add_case(fake_repo, "E-RED-01", credits=bad_credits)
    for n in (2, 3, 4, 5):
        add_case(fake_repo, f"E-RED-0{n}", credits=40.0)

    result = run_pass(pass_kind="full", config=config)

    assert list(result.not_runnable) == ["E-RED-01"] and result.spent == 80.0
    assert {r.case.id for r in result.ran} == {"E-RED-02", "E-RED-03"}
    assert {c.id for c in result.not_run} == {"E-RED-04", "E-RED-05"}


@pytest.mark.parametrize(
    "raw",
    [b"not json\n", b"[1]\n", b"\xff\xfe\x00garbage\n", b"[" * 100_000 + b"\n", b'{"outputs":[],"credits":1}\n'],
    ids=["not_json", "not_object", "utf16_bytes", "deep_nesting", "outputs_not_object"],
)
def test_EFF_07_unreadable_recording_is_not_runnable_and_the_pass_goes_on(fake_repo, raw):
    add_case(fake_repo, "E-RED-01")
    (fake_repo / "evals" / "recordings" / "E-RED-01.jsonl").write_bytes(raw)
    add_case(fake_repo, "E-RED-02")

    main(["run", "--pass", "full", "--results-json", "results.json"])

    data = _json(fake_repo)
    assert data["not_runnable"] == ["E-RED-01"] and data["ran"] == ["E-RED-02"]
    assert "E-RED-01" in (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "bad_event",
    [{"trace": "oops"}, {"trace": {"model_role": 3}}, {"credits": "lots"}, {"credits": -1e308}],
    ids=["string_trace", "numeric_role", "string_credits", "negative_credits"],
)
def test_EFF_07_bad_event_field_is_not_runnable(fake_repo, bad_event):
    add_case(fake_repo, "E-RED-01", [{"type": "x", **bad_event}])
    add_case(fake_repo, "E-RED-02")
    result = run_pass(pass_kind="full", config=EvalsConfig.load("config/evals.yaml"))
    assert list(result.not_runnable) == ["E-RED-01"] and [r.case.id for r in result.ran] == ["E-RED-02"]


def test_EFF_07_live_flag_refuses_without_LIVE_and_says_not_built_with_it(fake_repo, monkeypatch, capsys):
    monkeypatch.delenv("LIVE", raising=False)
    assert main(["run", "--pass", "smoke", "--live"]) == 2
    assert "LIVE=1" in capsys.readouterr().err
    monkeypatch.setenv("LIVE", "1")
    assert main(["run", "--pass", "smoke", "--live"]) == 2
    assert "not built" in capsys.readouterr().err


def test_EFF_07_no_cases_exits_0_and_a_bad_case_file_exits_2(fake_repo, capsys):
    assert main(["run", "--pass", "full"]) == 0
    assert "0 credits" in capsys.readouterr().out
    (fake_repo / "evals" / "cases" / "E-PLAN").mkdir()
    (fake_repo / "evals" / "cases" / "E-PLAN" / "E-PLAN-01.yaml").write_bytes(b"id: nope\n")
    assert main(["run", "--pass", "full"]) == 2
    assert "failed the case schema" in capsys.readouterr().err
