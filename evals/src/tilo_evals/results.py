"""Results reporting (EFF-07; PRD 19.3 "Honest reporting: counts first
('34 of 40'), then percentages, ..., failures grouped by cause"; PRD 19.5:
"Results go to evals/results.md with the date, the build hash, the roles
mapped to model profiles, the pass kind, the cost of the pass and every
failure listed"). PL-01: only profile names appear here, taken straight from
each event's own `trace.model_role` / `trace.profile` fields -- this module
never reads config/models.yaml and so never resolves, and never prints, a
model id.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from .runner import PassResult


def build_hash(repo_root: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _role_profile_pairs(pass_result: PassResult) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for run in pass_result.ran:
        pairs.update(run.roles)
    return pairs


def _cost_per_role(pass_result: PassResult) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for run in pass_result.ran:
        for role, cost in run.role_costs.items():
            totals[role] += cost
    return dict(totals)


def _failures_by_cause(pass_result: PassResult) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for run in pass_result.ran:
        if run.passed is False:
            grouped[run.cause or "unspecified"].append(run.case.id)
    return dict(grouped)


def render_results_md(*, pass_result: PassResult, build_hash: str, now_utc: str) -> str:
    ran = pass_result.ran
    total = len(ran)
    passed = [r for r in ran if r.passed is True]
    pending = [r for r in ran if r.passed is None]
    n_passed = len(passed)

    role_profiles = _role_profile_pairs(pass_result)
    total_cost = sum(r.cost for r in ran)

    lines: list[str] = []
    lines.append(f"## Eval run {now_utc}")
    lines.append("")
    lines.append(f"- Build hash: `{build_hash}`")
    lines.append(f"- Pass: `{pass_result.pass_kind}`")
    lines.append(
        "- Roles: " + (", ".join(f"{role} -> {profile}" for role, profile in sorted(role_profiles.items())) or "none")
    )
    lines.append(f"- Cost: {total_cost:g} credits (unpriced; config/prices.yaml status is unset)")
    lines.append("")

    lines.append("### Results")
    if total:
        percent = f" ({n_passed / total:.0%})"
    else:
        percent = ""
    lines.append(f"{n_passed} of {total} passed{percent}")
    if pending:
        lines.append(f"{len(pending)} pending autorater (not counted as passed)")
    lines.append("")

    lines.append("### Spread")
    if pass_result.pass_kind == "gate":
        by_case: dict[str, list[bool | None]] = defaultdict(list)
        for run in ran:
            by_case[run.case.id].append(run.passed)
        for case_id, outcomes in sorted(by_case.items()):
            n_ok = sum(1 for o in outcomes if o is True)
            lines.append(f"- {case_id}: {n_ok} of {len(outcomes)} repeats passed")
        if not by_case:
            lines.append("- no deploy_gate cases ran")
    else:
        lines.append("- one run per case (no repeats at this pass kind)")
    lines.append("")

    lines.append("### Failures grouped by cause")
    by_cause = _failures_by_cause(pass_result)
    if by_cause:
        for cause, case_ids in sorted(by_cause.items()):
            lines.append(f"- {cause}: {', '.join(sorted(case_ids))}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("### Not runnable")
    if pass_result.not_runnable:
        lines.append(", ".join(sorted(c.id for c in pass_result.not_runnable)))
    else:
        lines.append("none")
    lines.append("")

    lines.append("### Not run (credit cap)")
    if pass_result.stopped_at_cap:
        lines.append(f"Stopped at the `{pass_result.pass_kind}` credit cap after {pass_result.spent:g} credits.")
        lines.append(", ".join(sorted(c.id for c in pass_result.not_run)))
    else:
        lines.append("none")

    return "\n".join(lines) + "\n"


def render_results_json(*, pass_result: PassResult) -> dict[str, Any]:
    ran = pass_result.ran
    return {
        "pass": pass_result.pass_kind,
        "ran": [r.case.id for r in ran],
        "passed": [r.case.id for r in ran if r.passed is True],
        "failed": [r.case.id for r in ran if r.passed is False],
        "pending_autorater": [r.case.id for r in ran if r.passed is None],
        "not_run": [c.id for c in pass_result.not_run],
        "not_runnable": [c.id for c in pass_result.not_runnable],
        "stopped_at_cap": pass_result.stopped_at_cap,
        "spent": pass_result.spent,
        "cost_per_case": {r.case.id: r.cost for r in ran},
        "cost_per_role": _cost_per_role(pass_result),
        "failures_by_cause": _failures_by_cause(pass_result),
    }
