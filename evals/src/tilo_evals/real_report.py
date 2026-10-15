"""CX-EVALS-REAL: a single honest report for fake runs and recording replays."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bank_report import CaseResult
    from .runner import PassResult


def render_report(bank: list[CaseResult], replay: PassResult, *, build_hash: str) -> str:
    """Count attempts, failures, and unavailable recordings as different outcomes."""
    bank_failed = [r.case.id for r in bank if not r.passed]
    replay_failed = [r.case.id for r in replay.failed]
    executed = len(bank) + len(replay.ran)
    failed = len(bank_failed) + len(replay_failed)
    not_runnable = len(replay.not_runnable)
    lines = [
        "# Eval execution report",
        "",
        "`just eval` runs the held-out bank end to end with a scripted Director and fake providers,",
        "then replays the available E- cases from recordings. No network or paid model calls.",
        "The bank checks pipeline structure and policy, not model quality on unseen briefs.",
        "",
        f"Build: `{build_hash}`",
        "",
        "| Outcome | Cases |",
        "| --- | ---: |",
        f"| Executed | {executed} |",
        f"| Passed | {executed - failed - sum(r.passed is None for r in replay.ran)} |",
        f"| Failed | {failed} |",
        f"| Not runnable | {not_runnable} |",
        f"| Not run (credit cap) | {len(replay.not_run)} |",
        "",
        f"Executed by source: {len(bank)} fake-provider bank cases; {len(replay.ran)} recorded replay cases.",
        "A bank failure is an executed case; a replay without a recording is not runnable.",
        "",
        "## Failed cases",
        "",
        *[f"- {case_id}" for case_id in [*bank_failed, *replay_failed]],
    ]
    if not failed:
        lines.append("- none")
    lines += ["", "## Not runnable replay cases", ""]
    lines += [f"- {case_id}: {reason}" for case_id, reason in sorted(replay.not_runnable.items())] or ["- none"]
    if replay.not_run:
        lines += ["", "## Not run at credit cap", ""]
        lines += [f"- {case.id}" for case in replay.not_run]
    return "\n".join(lines) + "\n"
