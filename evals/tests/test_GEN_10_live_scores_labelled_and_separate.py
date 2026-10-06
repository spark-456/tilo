"""GEN-10 (issue #272 (b); PRD 19.3 autoraters, 9.4 HR-1, GEN-03, GEN-11): live autorater scores (plan fit to the
brief, question usefulness) are reported in their own section, labelled "live, N=<n>, <date>", and never count toward
GEN-03: the bank's hard-invariant pass rate is unchanged by them, however high or low they are.

Criteria covered:
  (1) the autorater is the `autorater` role of config/models.yaml, called through the provider layer once per run
      case that was kept; each reply is a JSON object with `plan_fit` and `question_usefulness`, numbers from 0 to 1;
      a reply outside that (or a role that fails) leaves the case unscored, never crashes the run;
  (2) the report has one section whose heading carries `live, N=<n>, <date>` (n = cases scored, date = the run's
      `--date`), holds every score, says they are not counted, and comes after the structural results; no score
      appears anywhere before that heading;
  (3) separation: structural findings, outcome classes, exit code, written cases and the bank's own report and
      digest are identical whether the scores are all 0.0 or all 1.0, and a run of the generator changes nothing in
      the bank (GEN-03's denominator and numerator are bank cases and hard checks only);
  (4) the autorater's credits count against the run's cap (they are model calls), and a dry run scores nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from _generator_lib import (
    AUTORATER_ROLE,
    DATE,
    LIVE_ENV,
    REPO_ROOT,
    SCORES_RE,
    brief_at,
    cli_args,
    copy_bank,
    env,
    gen_world,
    generated_files,
    generator,
    invoke_generate,
    live_generate,
    network_guard,  # noqa: F401  (autouse fixture)
    run_direct,
    tree,
)
from tilo_evals.bank import bank_digest, load_bank
from tilo_evals.bank_report import render, run_bank
from tilo_providers.errors import RequestError

TIMING = re.compile(r"(?i)latency|seconds|\bms\b|elapsed")  # wall-clock numbers differ run to run, by nature
NOT_COUNTED = re.compile(r"(?i)\b(?:not|never)\b[^.\n]*\bcount")


def live_section(text: str) -> tuple[str, str]:
    """(everything before the labelled heading, the section from it to the next heading or the end)."""
    lines = text.splitlines()
    at = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith("#") and SCORES_RE.search(ln))
    end = next((i for i in range(at + 1, len(lines)) if lines[i].lstrip().startswith("#")), len(lines))
    return "\n".join(lines[:at]), "\n".join(lines[at:end])


def test_GEN_10_live_scores_labelled_and_separate(tmp_path: Path) -> None:
    """The headline: three kept cases, three scored; their scores sit under the labelled heading and nowhere else."""
    world = gen_world(scores=(0.37, 0.91))
    result, world = live_generate(tmp_path, world=world, n=3)
    assert result.code == 0, (result.out, result.err)
    assert len(world.calls_of(AUTORATER_ROLE)) >= 3
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    before, section = live_section(text)
    label = SCORES_RE.search(section.splitlines()[0])
    assert label and label["n"] == "3" and label["date"] == DATE
    assert "0.37" in section and "0.91" in section
    assert "0.37" not in before and "0.91" not in before  # a score is never mixed into the structural results
    assert NOT_COUNTED.search(section), "the section does not say the scores are not counted"
    assert len(SCORES_RE.findall(text)) >= 1 and all(m[0] == "3" for m in SCORES_RE.findall(text))


def test_GEN_10_the_autorater_is_a_configured_role_called_through_the_provider_layer(tmp_path: Path) -> None:
    roles = yaml.safe_load((REPO_ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))["roles"]
    assert AUTORATER_ROLE in roles, "config/models.yaml has no `autorater` role"
    result, world = live_generate(tmp_path, n=2)
    assert result.code == 0, result.err
    built = {profile for role, profile in world.built if role == AUTORATER_ROLE}
    assert built and built <= {roles[AUTORATER_ROLE]["primary"], roles[AUTORATER_ROLE].get("fallback")}


def test_GEN_10_each_kept_case_has_its_two_scores_in_the_report(tmp_path: Path) -> None:
    report, _ = run_direct(tmp_path, world=gen_world(scores=(0.25, 0.75)), n=3)
    assert len(report.cases) == 3
    assert set(report.live_scores) == {c.id for c in report.cases}
    for scores in report.live_scores.values():
        assert scores == {"plan_fit": 0.25, "question_usefulness": 0.75}
    text = generator().render_report(report)
    _, section = live_section(text)
    for case in report.cases:
        assert case.id in section


def test_GEN_10_the_label_counts_only_the_cases_that_were_scored(tmp_path: Path) -> None:
    report, _ = run_direct(tmp_path, world=gen_world(briefs=[brief_at(0), brief_at(1, brief=""), brief_at(2)]), n=3)
    assert len(report.cases) == 2  # the empty brief was rejected, so it is neither run nor scored
    _, section = live_section(generator().render_report(report))
    assert SCORES_RE.search(section.splitlines()[0])["n"] == "2"  # type: ignore[index]


@pytest.mark.parametrize("scores", [(7.77, 0.5), (0.5, -1.23), (float("nan"), 0.5)], ids=["above-1", "below-0", "nan"])
def test_GEN_10_a_reply_outside_zero_to_one_is_unscored_not_a_crash(
    scores: tuple[float, float], tmp_path: Path
) -> None:
    report, _ = run_direct(tmp_path, world=gen_world(scores=scores), n=2)
    assert len(report.cases) == 2 and report.live_scores == {}
    text = generator().render_report(report)
    for value in ("7.77", "-1.23"):
        assert value not in text  # an out-of-range number is not repeated as if it were a score


def test_GEN_10_an_autorater_that_fails_leaves_the_run_and_its_structural_results_alone(tmp_path: Path) -> None:
    base_dir, broken_dir = tmp_path / "base", tmp_path / "broken"
    base_dir.mkdir(), broken_dir.mkdir()
    base, _ = run_direct(base_dir, world=gen_world(), n=3)
    world = gen_world()
    world.fail_roles[AUTORATER_ROLE] = RequestError("the autorater is down")
    broken, _ = run_direct(broken_dir, world=world, n=3)
    assert broken.live_scores == {}
    assert [c.outcome_class for c in broken.cases] == [c.outcome_class for c in base.cases]
    assert [(f.check, f.detail) for f in broken.hard_findings] == [(f.check, f.detail) for f in base.hard_findings]
    assert len(generated_files(broken_dir / "generated")) == len(generated_files(base_dir / "generated")) == 3


@pytest.mark.parametrize("low, high", [((0.0, 0.0), (1.0, 1.0))])
def test_GEN_10_the_scores_change_nothing_but_the_live_section(low, high, tmp_path: Path) -> None:
    runs = {}
    for name, scores in (("low", low), ("high", high)):
        folder = tmp_path / name
        folder.mkdir()
        result, world = live_generate(folder, world=gen_world(scores=scores), n=3)
        report = (folder / "report.md").read_text(encoding="utf-8")
        above = "\n".join(ln for ln in live_section(report)[0].splitlines() if not TIMING.search(ln))
        runs[name] = (result.code, above, sorted(p.name for p in generated_files(folder / "generated")))
    assert runs["low"][0] == runs["high"][0] == 0  # a score of 0.0 never fails the run
    assert runs["low"][1] == runs["high"][1]  # everything above the live section is identical
    assert runs["low"][2] == runs["high"][2]
    low_report, high_report = (tmp_path / n / "report.md" for n in ("low", "high"))
    assert low_report.read_text(encoding="utf-8") != high_report.read_text(encoding="utf-8")  # only the scores differ


def test_GEN_10_structural_findings_do_not_depend_on_the_scores(tmp_path: Path) -> None:
    findings = []
    for name, scores in (("a", (0.0, 0.0)), ("b", (1.0, 1.0))):
        folder = tmp_path / name
        folder.mkdir()
        report, _ = run_direct(folder, world=gen_world(scores=scores), n=3)
        findings.append(([(f.check, f.detail) for f in report.hard_findings], [c.outcome_class for c in report.cases]))
    assert findings[0] == findings[1]


def test_GEN_10_the_banks_own_report_and_digest_are_unchanged_by_a_generator_run(tmp_path: Path) -> None:
    bank = copy_bank(tmp_path)

    def bank_report() -> str:
        with env():
            results = run_bank(load_bank(bank))
        return render(results, repeat=1, bank_digest=bank_digest(bank))

    before_report, before_digest, before_tree = bank_report(), bank_digest(bank), tree(bank)
    result, _ = live_generate(tmp_path, world=gen_world(scores=(0.0, 0.0)), n=3, bank=bank)
    assert result.code == 0, result.err
    assert bank_digest(bank) == before_digest and tree(bank) == before_tree  # the frozen set is untouched
    assert bank_report() == before_report  # GEN-03's counts do not move
    assert "pass every hard check" in before_report
    out = tmp_path / "generated" / DATE
    assert out.is_dir() and bank not in out.parents  # generated cases live apart from the bank


def test_GEN_10_the_generated_cases_are_not_part_of_the_banks_pass_rate(tmp_path: Path) -> None:
    """`bank --bank evals/bank` counts bank cases only: a generated folder elsewhere never joins the denominator."""
    import tilo_evals.__main__ as cli  # noqa: PLC0415

    bank = copy_bank(tmp_path)
    live_generate(tmp_path, n=2, bank=bank)
    with env():
        code = cli.main(["bank", "--bank", str(bank), "--results-md", str(tmp_path / "bank-report.md")])
    assert code == 0
    assert "2 of 2" in (tmp_path / "bank-report.md").read_text(encoding="utf-8")  # B-001 and B-007 only


def test_GEN_10_the_autoraters_credits_count_against_the_cap(tmp_path: Path) -> None:
    report, world = run_direct(tmp_path, world=gen_world(), n=2)
    assert world.calls_of(AUTORATER_ROLE)
    assert report.total_credits == pytest.approx(world.spent, abs=1e-3)  # includes the autorater's own calls
    assert report.total_credits <= report.cap_credits


def test_GEN_10_a_dry_run_scores_nothing_and_has_no_live_section(tmp_path: Path) -> None:
    world = gen_world()
    with env(**LIVE_ENV):
        result = invoke_generate(cli_args(tmp_path, dry_run=True), world=world)
    assert result.code == 0, result.err
    assert world.calls_of(AUTORATER_ROLE) == [] and world.built == []
    assert not SCORES_RE.search(result.out) and not (tmp_path / "report.md").exists()
