"""Results reporting (EFF-07; PRD 19.3 "Honest reporting", 19.5): counts first ("34 of 40"), then percentages,
then the spread across repeats, failures grouped by cause. `evals/results.md` holds the latest run of each
pass kind, with its build hash, the model roles mapped to profile names, the cost of the pass and every
failure. PL-01: only profile names appear, read from each event's own trace; no model id is ever resolved
or printed here.
"""

import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from .runner import PassResult

_SECTION = "## Pass: "
_HEADER = "# Eval results\n\nThe latest run of each pass kind (PRD 19.5). Replayed recordings: no paid calls.\n"


def build_hash(repo_root: Path | None = None) -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
        )
        return done.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


_COUNTS = ("ran", "passed", "failed", "pending", "not_run", "not_runnable")


def _share(n: int, total: int, runs: bool = False) -> str:
    """ "34 of 40 passed"; with repeats (deploy-gate cases run several times) the unit is runs, not cases."""
    return f"{n} of {total} {'runs ' if runs else ''}passed" + (f" ({n / total:.0%})" if total else "")


def group_summary(result: PassResult) -> dict[str, dict[str, int]]:
    """Per case group: cases run, passed, failed, pending autorater, not run (cap) and not runnable."""
    groups: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(_COUNTS, 0))
    for run in result.ran:
        row = groups[run.case.group]
        row["ran"] += 1
        row["passed" if run.passed is True else "failed" if run.passed is False else "pending"] += 1
    for case in result.not_run:
        groups[case.group]["not_run"] += 1
    for case_id in result.not_runnable:
        groups[result.case_groups[case_id]]["not_runnable"] += 1
    return dict(sorted(groups.items()))


def _group_line(group: str, row: dict[str, int], runs: bool = False) -> str:
    extra = [
        f"{row[k]} {label}" for k, label in (("pending", "pending autorater"), ("not_run", "not run (cap)")) if row[k]
    ]
    extra += [f"{row['not_runnable']} not runnable"] if row["not_runnable"] else []
    return f"- {group}: {_share(row['passed'], row['passed'] + row['failed'], runs)}" + "".join(f"; {e}" for e in extra)


def failures_by_cause(result: PassResult) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for run in result.failed:
        grouped[run.cause or "unspecified"].append(run.case.id)
    return dict(grouped)


def _roles(result: PassResult) -> dict[str, str]:
    return {role: profile for run in result.ran for role, profile in run.roles.items()}


def _cost_per_role(result: PassResult) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for run in result.ran:
        for role, cost in run.role_costs.items():
            totals[role] += cost
    return dict(totals)


def summary_text(result: PassResult) -> str:
    """The CLI summary: counts first, then per case group, then why a partial pass stopped."""
    done = [r for r in result.ran if r.passed is not None]
    share = _share(sum(r.passed is True for r in done), len(done), result.repeated)
    lines = [f"{result.pass_kind} pass: {share}, {result.spent:g} credits"]
    lines += [_group_line(g, row, result.repeated) for g, row in group_summary(result).items()]
    if result.stop_reason:
        lines.append(f"stopped: {result.stop_reason}; {len(result.not_run)} case(s) not run")
    if result.not_runnable:
        lines.append(f"not runnable: {len(result.not_runnable)} case(s)")
    return "\n".join(lines)


def render_section(result: PassResult, *, build_hash: str, now_utc: str) -> str:
    done = [r for r in result.ran if r.passed is not None]
    n_pass = sum(r.passed is True for r in done)
    roles = ", ".join(f"{role} -> {profile}" for role, profile in sorted(_roles(result).items())) or "none"
    lines = [f"{_SECTION}{result.pass_kind}", ""]
    lines += [f"- Run at: {now_utc}", f"- Build hash: `{build_hash}`", f"- Roles: {roles}"]
    lines += [f"- Cost: {result.spent:g} credits of a {result.cap:g} cap (replayed recordings)", ""]
    lines += ["### Results", _share(n_pass, len(done), result.repeated)]
    if pending := [r for r in result.ran if r.passed is None]:
        lines.append(f"{len(pending)} pending autorater (not counted as passed)")
    lines += ["", "### By case group"] + [
        _group_line(g, row, result.repeated) for g, row in group_summary(result).items()
    ]
    lines += ["", "### Spread"]
    if result.repeated:
        repeats: dict[str, list[bool | None]] = defaultdict(list)
        for run in result.ran:
            repeats[run.case.id].append(run.passed)
        lines += [
            f"- {cid}: {sum(o is True for o in outs)} of {len(outs)} repeats passed"
            for cid, outs in sorted(repeats.items())
            if len(outs) > 1
        ]
    else:
        lines.append("- one run per case (no repeats ran)")
    lines += ["", "### Failures grouped by cause"]
    by_cause = failures_by_cause(result)
    lines += [f"- {cause}: {', '.join(sorted(set(ids)))}" for cause, ids in sorted(by_cause.items())] or ["- none"]
    lines += ["", "### Not runnable"]
    lines += [f"- {cid}: {why}" for cid, why in sorted(result.not_runnable.items())] or ["none"]
    lines += ["", "### Not run (credit cap)"]
    if result.stop_reason:
        lines += [f"Stopped: {result.stop_reason}.", ", ".join(sorted({c.id for c in result.not_run}))]
    else:
        lines.append("none")
    return "\n".join(lines) + "\n"


def merge_results_md(existing: str, section: str, pass_kind: str) -> str:
    """Replaces the section of `pass_kind` in the file's text (adding it if absent), keeping the others."""
    parts = existing.split("\n" + _SECTION)
    kept = [p for p in parts[1:] if p.split("\n", 1)[0].strip() != pass_kind]
    body = "".join("\n" + _SECTION + p.rstrip("\n") + "\n" for p in kept)
    return _HEADER + "\n" + section + body


def render_json(result: PassResult) -> dict[str, Any]:
    return {
        "pass": result.pass_kind,
        "cap": result.cap,
        "spent": result.spent,
        "ran": [r.case.id for r in result.ran],
        "passed": [r.case.id for r in result.ran if r.passed is True],
        "failed": [r.case.id for r in result.failed],
        "pending_autorater": [r.case.id for r in result.ran if r.passed is None],
        "not_run": [c.id for c in result.not_run],
        "not_runnable": sorted(result.not_runnable),
        "not_runnable_reasons": result.not_runnable,
        "stopped_at_cap": result.stopped_at_cap,
        "stop_reason": result.stop_reason,
        "by_group": group_summary(result),
        "cost_per_case": {r.case.id: r.cost for r in result.ran},
        "cost_per_role": _cost_per_role(result),
        "failures_by_cause": failures_by_cause(result),
    }
