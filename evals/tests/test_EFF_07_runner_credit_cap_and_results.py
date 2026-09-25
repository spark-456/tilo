"""EFF-07 acceptance tests for the eval-harness runner (PRD 6.6 "Lean evals":
"passes stop at a credit cap in config/evals.yaml"; PRD 19.5 "Results go to
evals/results.md with the build hash, model profiles, cost of the pass and
every failure listed"). Ticket spec (SE orchestrator "## P8-06"):

"Credit cap (EFF-07): before each case, when spent + case estimate >
credit_cap[pass] (the estimate comes from the recording's credits), the pass
stops, and the report lists the cases run, the cases not run, and
stopped_at_cap: true. A partial pass exits with code 3."

Computed-task EFF-07 test: "a pass whose fake cases cost 40 credits each
against a cap of 100 stops after 2 cases, lists the rest as not run, writes
partial results and exits 3."

Ambiguity resolved (logged in the report): the runner's CLI
(`python -m tilo_evals run --pass ... [--group G] [--case ID]...
[--results-md ...] [--results-json ...]`) has no flag to point --cases-root
or config/evals.yaml at tmp_path, so every test here uses the fake_repo
fixture (monkeypatch.chdir(tmp_path)) and writes evals/cases, config/evals.yaml
and evals/recordings under tmp_path, exactly as the P8-06 spec instructs
("Build fake cases and recordings in tmp_path, not in evals/cases"). The
--results-json object is assumed to expose "ran", "not_run", "not_runnable"
(lists of case ids) and "stopped_at_cap" (bool), since those are the exact
names the spec's acceptance test uses ("lists the cases run, the cases not
run, and stopped_at_cap: true").

Run with `uv run pytest "evals/tests" -q` from the repo root.
"""

from __future__ import annotations

import json
import re

import yaml
from conftest import make_event, write_case, write_evals_config, write_recording
from tilo_evals.__main__ import main

# fake_repo is a pytest fixture defined in this directory's conftest.py;
# pytest discovers it by name from every test function's parameter list
# below without a direct import.


def _recording_relpath(fake_repo, recording_path):
    return str(recording_path.relative_to(fake_repo)).replace("\\", "/")


def test_EFF_07_pass_stops_at_credit_cap_lists_rest_and_exits_3(fake_repo):
    cases_root = fake_repo / "evals" / "cases"
    write_evals_config(fake_repo / "config", credit_cap={"full": 100, "smoke": 100, "gate": 100})

    for n in (1, 2, 3):
        case_id = f"E-PLAN-0{n}"
        recording = fake_repo / "evals" / "recordings" / f"{case_id}.jsonl"
        write_recording(recording, [make_event(seq=1, type="world.started")], outputs={}, credits=40.0)
        write_case(
            cases_root,
            case_id=case_id,
            group="E-PLAN",
            ground_truth={"ok": True},
            checks=[{"check": "no_side_effects", "args": {}}],
            recording=_recording_relpath(fake_repo, recording),
        )

    exit_code = main(["run", "--pass", "full", "--results-json", "results.json"])

    assert exit_code == 3, "EFF-07: a partial pass (stopped at the credit cap) must exit 3"

    data = json.loads((fake_repo / "results.json").read_text(encoding="utf-8"))
    assert data["stopped_at_cap"] is True
    assert set(data["ran"]) == {"E-PLAN-01", "E-PLAN-02"}, "40+40=80<=100, but 80+40=120>100 stops after 2 cases"
    assert set(data["not_run"]) == {"E-PLAN-03"}, "the cap-blocked case is listed, never silently dropped"

    results_md = (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")
    assert results_md, "a partial pass still writes the results report"
    assert "E-PLAN-03" in results_md, "the report must list the case that was not run"


def test_EFF_07_skeleton_and_missing_recording_cases_are_not_runnable(fake_repo):
    """P8-06 spec: "A case with status: skeleton or no recording is not
    runnable; it is listed and never counted as passed or failed."
    """
    cases_root = fake_repo / "evals" / "cases"

    write_case(cases_root, case_id="E-PLAN-01", group="E-PLAN", status="skeleton", ground_truth=None, recording=None)
    write_case(
        cases_root, case_id="E-PLAN-02", group="E-PLAN", status="ready", ground_truth={"ok": True}, recording=None
    )

    recording = fake_repo / "evals" / "recordings" / "E-PLAN-03.jsonl"
    write_recording(recording, [make_event(seq=1, type="world.started")], outputs={}, credits=5.0)
    write_case(
        cases_root,
        case_id="E-PLAN-03",
        group="E-PLAN",
        status="ready",
        ground_truth={"ok": True},
        checks=[{"check": "no_side_effects", "args": {}}],
        recording=_recording_relpath(fake_repo, recording),
    )

    main(["run", "--pass", "full", "--results-json", "results.json"])

    data = json.loads((fake_repo / "results.json").read_text(encoding="utf-8"))
    assert set(data["not_runnable"]) == {"E-PLAN-01", "E-PLAN-02"}
    assert "E-PLAN-01" not in data["ran"]
    assert "E-PLAN-02" not in data["ran"]
    assert "E-PLAN-03" in data["ran"]


def test_EFF_07_results_report_counts_first_and_never_shows_a_model_id(fake_repo):
    """PRD 19.3 "Honest reporting: counts first ('34 of 40'), then
    percentages ..., failures grouped by cause". PL-01: a model id may live
    only in config/ and packages/providers, never in results output --
    events carry trace.profile (a profile name) already, so this also checks
    the renderer does not additionally resolve and print config/models.yaml's
    "model:" ids when it maps roles to profile names."""
    cases_root = fake_repo / "evals" / "cases"

    (fake_repo / "config").mkdir(parents=True, exist_ok=True)
    (fake_repo / "config" / "models.yaml").write_bytes(
        yaml.safe_dump(
            {
                "example": True,
                "profiles": {
                    "big": {"provider": "fake", "model": "zzfake-big-model-v1", "context": 100000, "caps": ["json"]},
                    "small": {
                        "provider": "fake",
                        "model": "zzfake-small-model-v1",
                        "context": 50000,
                        "caps": ["json"],
                    },
                },
                "roles": {
                    "director": {"primary": "big", "fallback": "small"},
                    "specialist": {"primary": "small", "fallback": "small"},
                },
                "rules": {"deny": []},
            },
            sort_keys=False,
        ).encode("utf-8")
    )

    ok_trace = {
        "model_role": "specialist",
        "profile": "small",
        "tokens_in": 10,
        "tokens_out": 5,
        "tool": None,
        "latency_ms": 1,
        "archive_ref": None,
    }
    ok_recording = fake_repo / "evals" / "recordings" / "E-PLAN-01.jsonl"
    write_recording(
        ok_recording,
        [make_event(seq=1, type="world.started", trace=ok_trace)],
        outputs={},
        credits=10.0,
    )
    write_case(
        cases_root,
        case_id="E-PLAN-01",
        group="E-PLAN",
        ground_truth={"ok": True},
        checks=[{"check": "no_side_effects", "args": {}}],
        recording=_recording_relpath(fake_repo, ok_recording),
    )

    failing_event = make_event(
        seq=1,
        type="data.transfer",
        authz={"by": "person", "ref": "u_owner", "at": "2026-10-01T00:00:00.000Z"},
    )
    failing_recording = fake_repo / "evals" / "recordings" / "E-PLAN-02.jsonl"
    write_recording(failing_recording, [failing_event], outputs={}, credits=10.0)
    write_case(
        cases_root,
        case_id="E-PLAN-02",
        group="E-PLAN",
        ground_truth={"ok": True},
        checks=[{"check": "no_side_effects", "args": {}}],
        recording=_recording_relpath(fake_repo, failing_recording),
    )

    main(["run", "--pass", "full", "--results-json", "results.json"])

    results_md = (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")

    counts_match = re.search(r"\d+\s+of\s+\d+", results_md)
    assert counts_match, 'PRD 19.3 honest reporting: results must show a "N of M" count'
    percent_index = results_md.find("%")
    assert percent_index == -1 or counts_match.start() < percent_index, "19.3: counts must come before percentages"

    assert "small" in results_md, "the profile name (never the model id) is reported"
    assert "zzfake-small-model-v1" not in results_md, "PL-01: never a model id in the results output"
    assert "zzfake-big-model-v1" not in results_md, "PL-01: never a model id in the results output"

    assert "cause" in results_md.lower(), "19.3: failures are grouped by cause"


def test_EFF_07_live_flag_without_LIVE_env_refuses(fake_repo, monkeypatch, capsys):
    monkeypatch.delenv("LIVE", raising=False)

    exit_code = main(["run", "--pass", "smoke", "--live"])

    assert exit_code != 0, "EFF-07/EFF-01: --live must refuse without LIVE=1"
    captured = capsys.readouterr()
    text = (captured.out + captured.err).lower()
    assert "live=1" in text, "the refusal must name LIVE=1"


def test_EFF_07_live_flag_with_LIVE_env_says_not_built_yet(fake_repo, monkeypatch, capsys):
    # monkeypatch.setenv, never a literal LIVE=1 in a shell command
    # (.claude/hooks/guard.py blocks that; SE spec section 0).
    monkeypatch.setenv("LIVE", "1")

    exit_code = main(["run", "--pass", "smoke", "--live"])

    assert exit_code != 0, "P8-06 spec: 'even then says the live executor is not built yet'"
    captured = capsys.readouterr()
    text = (captured.out + captured.err).lower()
    assert "live" in text
    assert "not" in text
