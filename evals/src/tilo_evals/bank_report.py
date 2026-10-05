"""Runs the bank and reports it (issue #272, GEN-02, GEN-04, GEN-11; PRD 19.3 "honest reporting").

Counts first ("27 of 30"), then per domain and per shape, failures grouped by check, and the spread over repeats.
The claim is stated in the report itself: a structural pass rate over the bank on fakes, never "handles any
scenario" (the bank scripts the Director, so it cannot judge the model; only the live generator can).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .bank import BankCase
from .bank_checks import Finding, check_case, drift, hard_findings, same_run
from .bank_run import DEFAULT_TIMEOUT_S, Observation, run_case

CLAIM = (
    "Claim scope: this is a structural pass rate over the held-out bank, run end to end on fakes with the "
    "Director scripted per case. It shows the pipeline stays valid and honest across these plan shapes. It does "
    "not show that the model plans well on unseen briefs (the live generator measures that) and it is not a "
    "statement that Tilo handles any scenario."
)


@dataclass
class CaseResult:
    case: BankCase
    runs: list[Observation]
    findings: list[Finding]  # of the first run
    deterministic: bool = True  # every repeat gave the same outcome and event types
    drift: str = ""  # what differed, when it did

    @property
    def passed(self) -> bool:
        return not hard_findings(self.findings) and self.deterministic


def run_bank(cases: list[BankCase], *, repeat: int = 1, timeout_s: float = DEFAULT_TIMEOUT_S) -> list[CaseResult]:
    results = []
    for case in cases:
        runs = [run_case(case, timeout_s=timeout_s) for _ in range(max(1, repeat))]
        same = all(same_run(runs[0], r) for r in runs[1:])
        what = next((d for r in runs[1:] if (d := drift(runs[0], r))), "")
        results.append(CaseResult(case, runs, check_case(runs[0]), same, what))
    return results


def _fraction(passed: int, total: int) -> str:
    return f"{passed} of {total}" + (f" ({passed / total:.0%})" if total else "")


def render(results: list[CaseResult], *, repeat: int, bank_digest: str) -> str:
    total, ok = len(results), sum(r.passed for r in results)
    lines = ["# Generality bank results", "", CLAIM, ""]
    lines += [f"**{_fraction(ok, total)} cases pass every hard check.**", ""]
    lines += [f"Bank digest `{bank_digest[:16]}`; {repeat} run(s) per case; no network, no paid call.", ""]

    def table(title: str, groups: dict[str, list[CaseResult]]) -> None:
        lines.extend([f"## {title}", "", "| Group | Passed |", "| --- | --- |"])
        for name, members in sorted(groups.items()):
            lines.append(f"| {name} | {_fraction(sum(m.passed for m in members), len(members))} |")
        lines.append("")

    by_domain: dict[str, list[CaseResult]] = defaultdict(list)
    by_shape: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_domain[r.case.domain].append(r)
        for shape in r.case.shapes:
            by_shape[shape].append(r)
    table("By domain", by_domain)
    table("By shape", by_shape)

    causes = Counter(f.check for r in results for f in r.findings if f.hard)
    lines += ["## Failures by cause (hard checks)", ""]
    lines += [f"- {check}: {count}" for check, count in causes.most_common()] or ["- none"]
    reported = Counter(f.check for r in results for f in r.findings if not f.hard)
    lines += ["", "## Reported, not gated", ""]
    lines += [f"- {check}: {count} of {total} cases" for check, count in reported.most_common()] or ["- none"]
    if repeat > 1:
        stable = sum(r.deterministic for r in results)
        lines += [
            "",
            "## Spread over repeats",
            "",
            f"- same outcome and event types on every repeat: {_fraction(stable, total)}",
        ]
    lines += ["", "## Every failure", ""]
    failed = [r for r in results if not r.passed]
    for r in failed:
        for f in r.findings if r.findings else []:
            lines.append(f"- {r.case.id} [{f.check}{'' if f.hard else ', reported'}]: {f.detail}")
        if not r.deterministic:
            lines.append(f"- {r.case.id} [determinism]: {r.drift}")
    if not failed:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)
