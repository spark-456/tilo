"""NFR-02, NFR-03, NFR-05 (PRD 17.1): the `latency` CLI and the NFR rows in the metrics report.

`uv run python -m tilo_evals latency --n N [--json]` prints the `measure(N)` report: one line per measure with p50, p95,
n and the scope label (text), or the report as one JSON document on stdout (`--json`). Exit 0; exit 2 when it is
refused (LIVE, K_SERVICE or CLOUD_RUN_JOB set, as the EV-07 `metrics` and `bank` CLIs do) or `--n` is not a positive
integer; nothing is printed on stdout in a refusal.

`python -m tilo_evals metrics` gains `--latency-n N` (default the builder's choice, at least 1) and then reports the NFR
rows from a local `measure(N)`:
- the markdown has one table row per NFR-02, NFR-03 and NFR-05 with p50, p95, n and the scope label;
- the JSON gains a top-level `latency` object (the `measure` report) and its `rows` stay the EV rows only;
- the one-line summary (`metrics: A computed, B no data, C need live or pilot data; report: P`) counts EV rows only,
  so it is unchanged;
- the EV-02 row ("Time to first plan", live wall-clock latency) is NOT filled from these local numbers: it stays
  `needs_live_or_pilot`, no value, n 0, in both the table and the JSON.
"""

import json
import re
import shutil

import pytest
from _evals_lib import REPO_ROOT, add_case
from _latency_lib import (
    BUDGETS,
    ENTRY_KEYS,
    IDS,
    REFUSING_ENV,
    SCOPE,
    _offline_env,  # noqa: F401  (autouse: no live switch, no network)
    latency,
)
from _metrics_lib import completed
from tilo_evals.__main__ import main

SUMMARY = re.compile(
    r"^metrics: (\d+) computed, (\d+) no data, (\d+) need live or pilot data; report: (\S.*)$", re.MULTILINE
)
CLAIM_MET = re.compile(r"\b(meets?|target met|targets met|met the target|goal met)\b", re.IGNORECASE)


def _exit(argv):
    """The exit code of `main`, whether it returns it or argparse raises SystemExit."""
    try:
        return main(argv)
    except SystemExit as stop:
        return stop.code


def _not_a_usage_error(err):
    """Exit 2 must be the harness's own refusal, not argparse not knowing the command or option yet."""
    assert "unrecognized arguments" not in err and "invalid choice" not in err, err


@pytest.fixture
def repo(fake_repo):
    """The fake repo plus config/prices.yaml (a copy of the real file) and an empty bank dir."""
    shutil.copyfile(REPO_ROOT / "config" / "prices.yaml", fake_repo / "config" / "prices.yaml")
    (fake_repo / "bank").mkdir()
    add_case(fake_repo, "E-RES-01", [completed(4)], measures=["EV-01"])
    return fake_repo


def _metrics(repo, *extra):
    argv = ["metrics", "--bank-dir", str(repo / "bank"), "--results-md", "out.md", "--results-json", "out.json"]
    return _exit([*argv, "--latency-n", "2", *extra])


def _table_line(text, label):
    lines = [ln for ln in text.splitlines() if ln.startswith("|") and re.search(rf"\b{re.escape(label)}\b", ln)]
    assert len(lines) == 1, f"exactly one table row for {label}, got {lines}"
    return lines[0]


# ---- the latency CLI ------------------------------------------------------------------------------------------


def test_NFR_02_cli_json_prints_the_measure_report_and_exits_0(capsys):
    code = _exit(["latency", "--n", "3", "--json"])

    out = capsys.readouterr().out
    assert code == 0
    report = json.loads(out)  # the whole of stdout is one JSON document
    for nfr in IDS:
        entry = report[nfr]
        assert set(entry) >= ENTRY_KEYS
        assert entry["n"] == 3 and entry["scope"] == SCOPE and entry["live"] is None
        assert entry["budget"] == BUDGETS[nfr]
        assert 0 < entry["p50_ms"] <= entry["p95_ms"]


def test_NFR_03_cli_text_has_one_line_per_measure_with_p50_p95_n_and_scope(capsys):
    code = _exit(["latency", "--n", "3"])

    out = capsys.readouterr().out
    assert code == 0
    for nfr in IDS:
        lines = [ln for ln in out.splitlines() if ln.strip().startswith(nfr)]
        assert len(lines) == 1, f"one line starting with {nfr}: {lines}"
        line = lines[0]
        assert "p50" in line and "p95" in line and SCOPE in line
        assert re.search(r"\bn[= ]3\b", line), f"{nfr}: the sample count is shown: {line!r}"
        assert not CLAIM_MET.search(line), "a number is reported, never a verdict that a target is met"


def test_NFR_05_cli_text_names_the_local_scope_and_claims_nothing_live(capsys):
    assert _exit(["latency", "--n", "2"]) == 0

    out = capsys.readouterr().out
    assert "client receipt" in out.lower(), "NFR-05 says its figure stops at client receipt"
    for line in out.splitlines():
        if re.search(r"\blive\b", line.lower()):
            assert any(w in line.lower() for w in ("not", "no ", "never", "without")), f"claims live: {line!r}"


@pytest.mark.parametrize("variable", REFUSING_ENV)
def test_NFR_02_cli_refuses_when_live_or_deployed(monkeypatch, capsys, variable):
    monkeypatch.setenv(variable, "1")

    code = _exit(["latency", "--n", "2", "--json"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.strip() == "", "no report is printed from a refused run"
    assert variable in captured.err, "the refusal is explained on stderr and names the switches"
    _not_a_usage_error(captured.err)


@pytest.mark.parametrize("bad", ["0", "-3", "abc"])
def test_NFR_02_cli_n_must_be_a_positive_integer(capsys, bad):
    assert _exit(["latency", "--n", bad]) == 2

    captured = capsys.readouterr()
    assert captured.out.strip() == "" and captured.err.strip()
    _not_a_usage_error(captured.err)


def test_NFR_02_the_cli_module_is_wired_as_python_m_tilo_evals_latency():
    assert latency().measure is not None and latency().percentiles is not None
    import tilo_evals.__main__ as entry

    assert "latency" in entry._parser().format_help()


# ---- the metrics report rows ----------------------------------------------------------------------------------


def test_NFR_02_03_05_metrics_markdown_has_a_row_per_measure_with_p50_p95_n_and_scope(repo, capsys):
    assert _metrics(repo) == 0

    text = (repo / "out.md").read_bytes().decode("utf-8")
    for nfr in IDS:
        line = _table_line(text, nfr)
        assert "p50" in line and "p95" in line, f"{nfr}: both percentiles in the row: {line!r}"
        assert SCOPE in line, f"{nfr}: the scope label is in the row"
        assert re.search(r"\b2\b", line), f"{nfr}: n (2) is in the row"
        assert not CLAIM_MET.search(line)
    assert b"\r\n" not in (repo / "out.md").read_bytes(), "LF line endings"


def test_NFR_02_03_05_metrics_json_gains_a_latency_object_and_keeps_the_ev_rows(repo):
    assert _metrics(repo) == 0

    data = json.loads((repo / "out.json").read_text(encoding="utf-8"))
    for nfr in IDS:
        entry = data["latency"][nfr]
        assert set(entry) >= ENTRY_KEYS
        assert entry["n"] == 2 and entry["scope"] == SCOPE and entry["live"] is None
        assert entry["budget"] == BUDGETS[nfr]
    assert {r["id"] for r in data["rows"]} <= {f"EV-{n:02d}" for n in range(1, 16)}, "rows stay the EV rows only"


def test_NFR_03_metrics_summary_line_counts_ev_rows_only_and_is_unchanged(repo, capsys):
    assert _metrics(repo) == 0

    match = SUMMARY.search(capsys.readouterr().out)
    assert match, "the metrics summary line keeps its shape"
    computed, no_data, live = (int(match.group(i)) for i in (1, 2, 3))
    assert computed + no_data + live == len(
        {r["id"] for r in json.loads((repo / "out.json").read_text(encoding="utf-8"))["rows"]}
    ), "one count per EV id; the NFR rows are not in it"


def test_NFR_03_ev_02_is_not_filled_from_the_local_numbers(repo):
    """EV-02 (time to first plan) needs a live wall-clock run (PRD 3.5). The local NFR-03 figure is a different
    thing (Tilo's own overhead on a fake Director) and never stands in for it."""
    assert _metrics(repo) == 0

    data = json.loads((repo / "out.json").read_text(encoding="utf-8"))
    ev02 = [r for r in data["rows"] if r["id"] == "EV-02"]
    assert len(ev02) == 1
    assert (ev02[0]["status"], ev02[0]["value"], ev02[0]["n"], ev02[0]["basis"]) == (
        "needs_live_or_pilot",
        None,
        0,
        None,
    )
    assert "live" in ev02[0]["method"].lower()
    line = _table_line((repo / "out.md").read_text(encoding="utf-8"), "EV-02")
    assert "needs live or pilot data" in line
    cells = [c.strip() for c in line.strip("|").split("|")]
    assert (cells[4], cells[5]) == ("-", "0"), "no value and n 0 in the EV-02 row"
    assert SCOPE not in line, "the local scope label never appears on the EV-02 row"


def test_NFR_05_metrics_report_makes_no_live_claim_about_the_nfr_rows(repo):
    assert _metrics(repo) == 0

    text = (repo / "out.md").read_text(encoding="utf-8")
    for nfr in IDS:
        line = _table_line(text, nfr)
        assert not re.search(r"\blive\b", line.lower()) or any(w in line.lower() for w in ("not", "no ")), line


@pytest.mark.parametrize("bad", ["0", "-1", "abc"])
def test_NFR_02_metrics_latency_n_must_be_a_positive_integer(repo, bad, capsys):
    argv = ["metrics", "--bank-dir", str(repo / "bank"), "--results-md", "out.md", "--latency-n", bad]

    assert _exit(argv) == 2
    assert not (repo / "out.md").exists(), "no report is written from a bad option"
    _not_a_usage_error(capsys.readouterr().err)


@pytest.mark.parametrize("variable", REFUSING_ENV)
def test_NFR_02_metrics_still_refuses_when_live_or_deployed_and_writes_no_latency(repo, monkeypatch, variable, capsys):
    monkeypatch.setenv(variable, "1")

    assert _metrics(repo) == 2

    _not_a_usage_error(capsys.readouterr().err)

    assert not (repo / "out.md").exists() and not (repo / "out.json").exists()
