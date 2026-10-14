"""VERTEX-EVAL-1 (PR 1b; design 3.4 report, 4.3-4.4 what leaves and comes back; PRD 19.3 honest reporting, 9.4 HR-1):
`report.local.md` (and `--report-json`) lead with counts, are labelled LIVE or FAKE, carry provenance without a model
id or any environment value, redact and cap every explanation, and never touch the EV rows or `evals/results.md`.

Criteria covered (design section 5 numbers): 36 counts first, mode label, fixed scope sentence; 37 provenance has no
model id or environment values; 38 the report never touches EV rows; plus a live run end to end on an injected judge
(header LIVE, `basis` live_autorater) and the LF, deterministic shape of the files.
Ambiguity resolved (design silent): the JSON's only pinned keys are `basis` (`live_autorater` or `fake`) and that every
judgement's explanation is kept; "build hash" is `tilo_evals.results.build_hash()` and the time is UTC ISO-8601.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from _vertex_eval_lib import (
    GROUNDED_FILE,
    GROUNDED_ID,
    JUDGED_RE,
    LIVE_ENV,
    PAIRWISE_FILE,
    PAIRWISE_ID,
    PROJECT,
    REPO_ROOT,
    RecordingEvalProvider,
    ids_of,
    invoke,
    leaks,
    live_run_argv,
    network_guard,  # noqa: F401  (autouse fixture)
    pair_row,
    planted,
    rubric,
    run_argv,
    write_pairs,
)
from tilo_evals.results import build_hash

FAKE_HEADER = "FAKE: deterministic dev stand-in, not a measurement"
LIVE_HEADER = "LIVE: Vertex AI Gen AI evaluation service"
SCOPE = "It is not an EV row, not EV-05, and not a claim about any other case."
MODEL_ID = "zz-judge-model-under-test"


def _pairs(tmp_path: Path, n: int = 4, **kw) -> Path:
    return write_pairs(tmp_path, [pair_row(i) for i in ids_of(n)], **kw)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- 36: counts first, the mode label, the scope --------------------------------------------------------------------


def test_VERTEX_EVAL_1_report_counts_first_and_labels_mode(tmp_path: Path) -> None:
    judge = RecordingEvalProvider(prefer={"B-002": "baseline", "B-003": "tie"})
    result = invoke(run_argv(tmp_path, _pairs(tmp_path)), provider=judge)
    assert result.code == 0, result.err
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert FAKE_HEADER in report and "LIVE:" not in report
    assert SCOPE in report
    assert re.search(r"judgements? of recorded Director output on 4 pairs", report), report
    # the counts come first: "N of M" before any percentage
    judged = JUDGED_RE.search(report)
    assert judged and (judged["k"], judged["n"]) == ("4", "4"), report
    first_percent = re.search(r"\d+%", report)
    assert first_percent and judged.start() < first_percent.start()
    assert re.search(r"Candidate preferred in 2 of 4,\s+baseline in 1 of 4,\s+tie in 1 of 4", report)
    assert re.search(r"50% \(2 of 4\)", report) and re.search(r"67% \(2 of 3\) excluding ties", report)
    assert re.search(r"grounded in 4 of 4", report)
    assert not any(line.lstrip().startswith("| EV-") for line in report.splitlines())


def test_VERTEX_EVAL_1_report_is_labelled_live_for_a_live_run_and_json_has_the_basis(tmp_path: Path) -> None:
    judge = RecordingEvalProvider()
    argv = live_run_argv(tmp_path, _pairs(tmp_path), report_json=tmp_path / "report.json")
    result = invoke(argv, environ=LIVE_ENV, provider=judge)
    assert result.code == 0, result.err
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert LIVE_HEADER in report and "FAKE:" not in report and SCOPE in report
    assert "plan groundedness (live judge)" in report  # never named as an EV row (BQ-VEVAL-2)
    data = json.loads((tmp_path / "report.json").read_bytes())
    assert data["basis"] == "live_autorater"
    fake = invoke(
        run_argv(tmp_path, _pairs(tmp_path), report=tmp_path / "f.md", report_json=tmp_path / "f.json"), provider=judge
    )
    assert fake.code == 0, fake.err
    assert json.loads((tmp_path / "f.json").read_bytes())["basis"] == "fake"
    assert FAKE_HEADER in (tmp_path / "f.md").read_text(encoding="utf-8")


def test_VERTEX_EVAL_1_report_says_estimated_and_names_the_credits_and_stop_reason(tmp_path: Path) -> None:
    result = invoke(run_argv(tmp_path, _pairs(tmp_path, 3)), provider=RecordingEvalProvider())
    assert result.code == 0, result.err
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "estimated; reconcile against the billing export" in report
    assert "US$" in report and "credits" in report.lower()


def test_VERTEX_EVAL_1_report_json_keeps_every_judgement(tmp_path: Path) -> None:
    judge = RecordingEvalProvider(explanation="kept-judgement-text")
    result = invoke(run_argv(tmp_path, _pairs(tmp_path, 3), report_json=tmp_path / "report.json"), provider=judge)
    assert result.code == 0, result.err
    text = (tmp_path / "report.json").read_text(encoding="utf-8")
    json.loads(text)
    assert text.count("kept-judgement-text") >= len(judge.requests)  # one kept per call
    for case_id in ids_of(3):
        assert case_id in text


def test_VERTEX_EVAL_1_report_files_are_lf_and_stable_apart_from_the_clock(tmp_path: Path) -> None:
    pairs = _pairs(tmp_path)
    for name in ("a", "b"):
        argv = run_argv(tmp_path, pairs, report=tmp_path / f"{name}.md", report_json=tmp_path / f"{name}.json")
        assert invoke(argv, provider=RecordingEvalProvider()).code == 0
    clock = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
    for suffix in ("md", "json"):
        first, second = (tmp_path / f"a.{suffix}").read_bytes(), (tmp_path / f"b.{suffix}").read_bytes()
        assert b"\r" not in first and first.endswith(b"\n")
        assert clock.sub("T", first.decode("utf-8")) == clock.sub("T", second.decode("utf-8"))


# --- explanations are redacted again and capped ---------------------------------------------------------------------


def test_VERTEX_EVAL_1_report_redacts_and_caps_explanations(tmp_path: Path) -> None:
    secrets = planted()
    long_part = "ABCDEFGH" * 40  # 320 characters
    explanation = f"saw {secrets['email']} and {secrets['oauth']} {secrets['labelled']} " + long_part
    judge = RecordingEvalProvider(explanation=explanation[:500])
    result = invoke(run_argv(tmp_path, _pairs(tmp_path, 2), report_json=tmp_path / "report.json"), provider=judge)
    assert result.code == 0, result.err
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert leaks(report) == [] and leaks((tmp_path / "report.json").read_text(encoding="utf-8")) == []
    assert ("ABCDEFGH" * 16)[:121] not in report  # a table explanation is at most 120 characters
    rows = [ln for ln in report.splitlines() if ln.lstrip().startswith("|") and "B-001" in ln]
    assert rows and all(len(re.sub(r"\s+", " ", ln)) < 600 for ln in rows)


def test_VERTEX_EVAL_1_report_never_shows_control_characters_from_a_judge(tmp_path: Path) -> None:
    bell, esc = chr(7), chr(27)
    judge = RecordingEvalProvider(explanation=f"fine{bell}{esc}[31m red{chr(0x202E)} done")
    assert invoke(run_argv(tmp_path, _pairs(tmp_path, 2)), provider=judge).code == 0
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert bell not in text and esc not in text and chr(0x202E) not in text


# --- 37: provenance --------------------------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_report_provenance_has_no_model_id_or_env_values(tmp_path: Path) -> None:
    pairs = _pairs(tmp_path, 3, candidate_label="After fix 1.2", baseline_label="scripted-bank")
    argv = live_run_argv(tmp_path, pairs, report_json=tmp_path / "report.json")
    environ = {**LIVE_ENV, "TILO_VERTEX_EVAL_LOCATION": "asia-southeast1"}
    result = invoke(argv, environ=environ, provider=RecordingEvalProvider())
    assert result.code == 0, result.err
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    as_json = (tmp_path / "report.json").read_text(encoding="utf-8")
    # what it must show
    assert build_hash() in report
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", report)
    assert "judge-live" in report and "eval_judge" in report  # the profile id and the role
    assert PAIRWISE_ID in report and GROUNDED_ID in report
    assert hashlib.sha256(rubric(PAIRWISE_FILE).encode("utf-8")).hexdigest() in report
    assert hashlib.sha256(rubric(GROUNDED_FILE).encode("utf-8")).hexdigest() in report
    assert _sha(pairs) in report
    assert "After fix 1.2" in report and "scripted-bank" in report
    # what it must never show: the model id, the project, the location, the machine's paths
    paths = [str(tmp_path), tmp_path.as_posix(), str(REPO_ROOT), REPO_ROOT.as_posix(), str(Path.home())]
    env_values = [MODEL_ID, PROJECT, "asia-southeast1", "tilo-test-no-gcloud-config"]
    for text in (report, as_json):
        for needle in [*env_values, *paths]:
            assert needle not in text, needle
    for text in (result.out, result.err, result.logs):  # a printed report path is fine; the rest never is
        for needle in env_values:
            assert needle not in text, needle


def test_VERTEX_EVAL_1_fake_report_provenance_also_has_no_paths_or_model_id(tmp_path: Path) -> None:
    result = invoke(
        run_argv(tmp_path, _pairs(tmp_path, 2), report_json=tmp_path / "r.json"), provider=RecordingEvalProvider()
    )
    assert result.code == 0, result.err
    for text in (
        (tmp_path / "report.md").read_text(encoding="utf-8"),
        (tmp_path / "r.json").read_text(encoding="utf-8"),
    ):
        for needle in (MODEL_ID, str(tmp_path), tmp_path.as_posix(), str(Path.home())):
            assert needle not in text, needle
        assert "judge-fake" in text


# --- 38: the EV rows are never touched ------------------------------------------------------------------------------


def test_VERTEX_EVAL_1_report_never_touches_ev_rows(tmp_path: Path) -> None:
    watched = [
        REPO_ROOT / "evals" / name
        for name in ("results.md", "results.local.md", "metrics.local.md", "bank-results.local.md", "nightly.local.md")
    ]
    before = {p: (p.read_bytes() if p.exists() else None) for p in watched}
    result = invoke(
        run_argv(tmp_path, _pairs(tmp_path), report_json=tmp_path / "report.json"), provider=RecordingEvalProvider()
    )
    assert result.code == 0, result.err
    after = {p: (p.read_bytes() if p.exists() else None) for p in watched}
    assert after == before  # no committed or local EV file changed, and none was created
    data = json.loads((tmp_path / "report.json").read_bytes())
    assert data["basis"] == "fake"
    # the metrics and results code never read this module or its basis (static: no import, no mention)
    src = REPO_ROOT / "evals" / "src" / "tilo_evals"
    for name in ("metrics.py", "metrics_report.py", "results.py"):
        text = (src / name).read_text(encoding="utf-8")
        assert "vertex_eval" not in text and "live_autorater" not in text, name


def test_VERTEX_EVAL_1_default_paths_are_named_in_the_help_text() -> None:
    """The defaults are named in the help text (design 3.2), so no test has to write into the repo to read them."""
    run_help = invoke(["vertex-eval", "run", "--help"])
    assert run_help.code == 0, run_help.err
    assert "evals/vertex-eval/report.local.md" in " ".join(run_help.out.split())
    export_help = invoke(["vertex-eval", "export", "--help"])
    assert export_help.code == 0, export_help.err
    assert "evals/vertex-eval/pairs.local.yaml" in " ".join(export_help.out.split())
