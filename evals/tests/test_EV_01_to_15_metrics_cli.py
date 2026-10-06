"""EV-01..EV-15 CLI: `python -m tilo_evals metrics [--bank-dir evals/bank] [--case ID]... [--cases-root evals/cases]
[--results-md evals/metrics.local.md] [--results-json PATH]` (PRD 3.5, 19.3, 19.5).

It replays the case set (a full pass under config/evals.yaml's credit cap), runs the bank on fakes, builds records,
computes the rows and writes the markdown (UTF-8 bytes, LF). One summary line is printed, exit 0; exit 2 when the
bank is refused (LIVE, K_SERVICE or CLOUD_RUN_JOB set) or a case file is bad. Tests use a fake repo under tmp_path
(never evals/cases) and an empty bank dir, except the one slow test that runs the real bank case B-007.

Ambiguity resolved here (not in the PRD): `--case ID` selects that id in whichever set holds it (the replay cases or
the bank); an id found in neither exits 2. With `--case B-007` the replay set therefore runs nothing."""

import json
import re
import shutil

import pytest
from _evals_lib import REPO_ROOT, add_case, write_evals_config
from _metrics_lib import CLAIM_SENTENCE, EV_IDS, MODEL_ID, completed, handoff, planned
from tilo_evals.__main__ import main
from tilo_metering.prices import PriceBook

SUMMARY = re.compile(
    r"^metrics: (\d+) computed, (\d+) no data, (\d+) need live or pilot data; report: (\S.*)$", re.MULTILINE
)


@pytest.fixture
def repo(fake_repo):
    """The fake repo plus config/prices.yaml (a copy of the real file) and an empty bank dir."""
    shutil.copyfile(REPO_ROOT / "config" / "prices.yaml", fake_repo / "config" / "prices.yaml")
    (fake_repo / "bank").mkdir()
    return fake_repo


def _seed_cases(repo):
    add_case(repo, "E-PLAN-01", [planned(8, 12, "town"), completed(10)], measures=["EV-01", "EV-03", "EV-07"])
    add_case(repo, "E-RES-01", [completed(4)], measures=["EV-01"])
    add_case(repo, "E-RES-02", status="skeleton", ground_truth=None, recording=None, measures=["EV-01"])
    add_case(repo, "E-HAND-01", [handoff(True)], measures=["EV-10"])


def _run(repo, *extra):
    argv = ["metrics", "--bank-dir", str(repo / "bank"), "--results-md", "out.md", "--results-json", "out.json", *extra]
    return main(argv)


def _json_rows(repo):
    return json.loads((repo / "out.json").read_text(encoding="utf-8"))["rows"]


def _row(rows, ev_id, basis):
    found = [r for r in rows if r["id"] == ev_id and r["basis"] == basis]
    assert len(found) == 1, [(r["id"], r["basis"]) for r in rows if r["id"] == ev_id]
    return found[0]


def test_EV_01_to_15_cli_writes_an_lf_report_with_every_metric_and_prints_one_summary_line(repo, capsys):
    _seed_cases(repo)

    code = _run(repo)

    out = capsys.readouterr().out
    assert code == 0
    match = SUMMARY.search(out)
    assert match, f"summary line missing: {out!r}"
    computed, no_data, live = (int(match.group(i)) for i in (1, 2, 3))
    assert (computed, no_data, live) == (5, 3, 7), "EV-01, 03, 04, 07, 10 computed; 06, 08, 09 no data; seven live-only"
    assert match.group(4).endswith("out.md")
    data = (repo / "out.md").read_bytes()
    assert b"\r\n" not in data
    text = data.decode("utf-8")
    assert CLAIM_SENTENCE in text
    for ev_id in EV_IDS:
        assert ev_id in text


def test_EV_01_to_15_cli_default_report_path_is_the_git_ignored_local_file(repo):
    _seed_cases(repo)

    assert main(["metrics", "--bank-dir", str(repo / "bank")]) == 0

    assert (repo / "evals" / "metrics.local.md").is_file()
    assert not (repo / "evals" / "results.md").exists(), "the official results file is never touched"


def test_EV_01_to_15_the_default_report_path_is_git_ignored():
    lines = {ln.strip() for ln in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}

    assert "evals/metrics.local.md" in lines


def test_EV_01_to_15_cli_rows_show_replay_coverage_and_recorded_basis(repo):
    _seed_cases(repo)

    assert _run(repo) == 0

    rows = _json_rows(repo)
    ev01 = _row(rows, "EV-01", "recorded")
    assert (ev01["n"], ev01["of"]) == (2, 2)
    assert "3 cases measure this, 2 recorded" in ev01["note"], "E-RES-02 is a skeleton without a recording"
    assert (_row(rows, "EV-03", "recorded")["value"], _row(rows, "EV-03", "recorded")["n"]) == (pytest.approx(1.0), 1)
    assert _row(rows, "EV-10", "recorded")["value"] == pytest.approx(1.0)
    assert all(r["basis"] != "scripted_fakes" for r in rows), "an empty bank gives no scripted_fakes row"
    assert not MODEL_ID.search((repo / "out.md").read_text(encoding="utf-8"))


def test_EV_07_cli_usd_is_credits_times_credit_usd_from_the_prices_file(repo):
    add_case(repo, "E-RES-01", [completed(8)], measures=["EV-01"])
    credit_usd = PriceBook.load(REPO_ROOT / "config" / "prices.yaml").credit_usd

    assert _run(repo) == 0

    note = _row(_json_rows(repo), "EV-07", "recorded")["note"]
    assert f"{8 * credit_usd:.2f}" in note, "USD = 8 credits * credit_usd of config/prices.yaml"


def test_EV_07_cli_takes_credit_usd_from_tilo_metering_not_from_a_literal(repo, monkeypatch):
    add_case(repo, "E-RES-01", [completed(8)], measures=["EV-01"])
    monkeypatch.setattr(PriceBook, "load", classmethod(lambda cls, *paths: cls(credit_usd=0.0125, versions=())))

    assert _run(repo) == 0

    note = _row(_json_rows(repo), "EV-07", "recorded")["note"]
    assert "0.1" in note and "0.04" not in note, "8 credits * 0.0125 = 0.1; the default 0.005 would give 0.04"


def test_EV_01_cli_replay_is_a_full_pass_under_the_credit_cap(repo):
    write_evals_config(repo / "config", credit_cap={"full": 50, "smoke": 50, "gate": 50})
    for n in (1, 2, 3):
        add_case(repo, f"E-RES-0{n}", [completed(1)], measures=["EV-01"], credits=40.0)

    assert _run(repo) == 0

    ev01 = _row(_json_rows(repo), "EV-01", "recorded")
    assert ev01["of"] == 1, "the cap of 50 credits stops the pass after the first 40-credit case"


def test_EV_01_cli_case_option_selects_replay_cases_by_id(repo):
    add_case(repo, "E-RES-01", [completed(1)], measures=["EV-01"])
    add_case(repo, "E-RES-02", [completed(1)], measures=["EV-01"])

    assert _run(repo, "--case", "E-RES-01") == 0

    assert _row(_json_rows(repo), "EV-01", "recorded")["of"] == 1


def test_EV_01_cli_a_case_id_found_nowhere_exits_2(repo, capsys):
    add_case(repo, "E-RES-01", [completed(1)], measures=["EV-01"])

    assert _run(repo, "--case", "NOPE-99") == 2

    assert "NOPE-99" in capsys.readouterr().err
    assert not (repo / "out.md").exists()


def test_EV_01_cli_a_bad_case_file_exits_2_and_writes_nothing(repo, capsys):
    path = repo / "evals" / "cases" / "E-PLAN" / "E-PLAN-01.yaml"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"id: E-PLAN-01\n")  # fails evals/case.schema.json

    assert _run(repo) == 2

    assert "E-PLAN-01" in capsys.readouterr().err
    assert not (repo / "out.md").exists() and not (repo / "out.json").exists()


@pytest.mark.parametrize("variable", ["LIVE", "K_SERVICE", "CLOUD_RUN_JOB"])
def test_EV_01_cli_exits_2_when_the_bank_is_refused_in_a_live_or_deployed_environment(
    repo, monkeypatch, capsys, variable
):
    add_case(repo, "E-RES-01", [completed(1)], measures=["EV-01"])
    shutil.copyfile(REPO_ROOT / "evals" / "bank" / "B-007.yaml", repo / "bank" / "B-007.yaml")
    monkeypatch.setenv(variable, "1")

    assert _run(repo) == 2

    assert capsys.readouterr().err.strip(), "the refusal is explained on stderr"
    assert not (repo / "out.md").exists(), "no report is written from a refused run"


@pytest.mark.slow
def test_EV_07_cli_real_bank_case_b007_gives_a_scripted_fakes_cost_row_and_no_recorded_rows(repo):
    """The only real run in the suite: B-007 end to end on fakes (about 15 s). `--case B-007` leaves the replay set
    (one recorded case below) unrun, so every figure in the report must be on basis scripted_fakes."""
    add_case(repo, "E-RES-01", [completed(1)], measures=["EV-01"])
    argv = ["metrics", "--bank-dir", str(REPO_ROOT / "evals" / "bank"), "--case", "B-007"]

    code = main([*argv, "--results-md", "out.md", "--results-json", "out.json"])

    assert code == 0
    rows = _json_rows(repo)
    ev07 = _row(rows, "EV-07", "scripted_fakes")
    assert ev07["status"] == "computed" and ev07["value"] > 0 and ev07["n"] == 1
    assert ev07["note"].startswith("mechanics only")
    ev01 = _row(rows, "EV-01", "scripted_fakes")
    assert (ev01["n"], ev01["of"]) == (1, 1), "B-007 passes its hard checks and was expected to complete"
    assert all(r["basis"] != "recorded" for r in rows), "the replay set did not run"
    text = (repo / "out.md").read_text(encoding="utf-8")
    assert CLAIM_SENTENCE in text and not MODEL_ID.search(text)
    ev02 = _row(rows, "EV-02", None)
    assert (ev02["status"], ev02["value"]) == ("needs_live_or_pilot", None)


def test_EV_01_to_15_cli_default_run_adds_only_the_git_ignored_report_under_evals(repo):
    _seed_cases(repo)
    before = {p.name for p in (repo / "evals").iterdir()}

    assert main(["metrics", "--bank-dir", str(repo / "bank")]) == 0

    created = {p.name for p in (repo / "evals").iterdir()} - before
    assert created == {"metrics.local.md"}
