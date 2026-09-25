"""The eval-harness runner (EFF-07; PRD 19.1-19.3, 6.6 "Lean evals"). Picks
the cases for a pass (smoke | full | gate), replays each in turn while it
still fits the pass's credit cap, and runs its deterministic checks.
Autorater checks are never run here -- they are reported as pending and
never count as a pass (P8-06 spec).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .cases import Case, load_cases
from .checks import AUTORATER_CHECKS, CheckResult
from .checks import get as get_check
from .config import EvalsConfig
from .executors import ExecutorError, ReplayExecutor


@dataclass
class CaseRunResult:
    case: Case
    passed: bool | None  # True/False, or None when only pending autoraters ran
    check_results: list[dict[str, Any]] = field(default_factory=list)
    cost: float = 0.0
    role_costs: dict[str, float] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)  # model_role -> profile name
    cause: str | None = None
    pending_autoraters: list[str] = field(default_factory=list)


@dataclass
class PassResult:
    pass_kind: str
    ran: list[CaseRunResult] = field(default_factory=list)
    not_run: list[Case] = field(default_factory=list)
    not_runnable: list[Case] = field(default_factory=list)
    stopped_at_cap: bool = False
    spent: float = 0.0


def _is_runnable(case: Case) -> bool:
    """A case with status: skeleton or no recording is not runnable (P8-06
    spec)."""
    return case.status != "skeleton" and bool(case.recording)


def _select_cases(
    cases: list[Case],
    *,
    pass_kind: str,
    group: str | None,
    case_ids: list[str] | None,
    config: EvalsConfig,
) -> list[Case]:
    selected = cases
    if case_ids:
        wanted = set(case_ids)
        selected = [c for c in selected if c.id in wanted]
    elif group:
        selected = [c for c in selected if c.group == group]

    if pass_kind == "smoke":
        # One ready, runnable case per group.
        seen_groups: set[str] = set()
        picked: list[Case] = []
        for case in sorted(selected, key=lambda c: c.id):
            if case.status == "ready" and _is_runnable(case) and case.group not in seen_groups:
                picked.append(case)
                seen_groups.add(case.group)
        return picked

    if pass_kind == "gate":
        gate_cases = [c for c in selected if c.deploy_gate]
        return gate_cases * config.deploy_gate_repeats

    return list(selected)  # full


def _evaluate_case(case: Case, outcome: Any) -> CaseRunResult:
    role_costs: dict[str, float] = {}
    roles: dict[str, str] = {}
    for event in outcome.events:
        trace = event.get("trace") or {}
        role = trace.get("model_role")
        if role:
            role_costs[role] = role_costs.get(role, 0.0) + float(event.get("credits") or 0.0)
            profile = trace.get("profile")
            if profile:
                roles[role] = profile

    check_results: list[dict[str, Any]] = []
    pending_autoraters: list[str] = []
    passed: bool | None = True
    cause: str | None = None

    for entry in case.checks:
        name = entry["check"]
        args = entry.get("args") or {}
        if name in AUTORATER_CHECKS:
            pending_autoraters.append(name)
            continue
        try:
            result = get_check(name)(case, outcome, **args)
        except Exception as exc:  # noqa: BLE001 -- a bad check/args must fail the case, never crash the pass (qa review)
            result = CheckResult(passed=False, cause=f"{name}: check raised {exc.__class__.__name__}: {exc}")
        check_results.append({"check": name, "passed": result.passed, "cause": result.cause})
        if not result.passed:
            passed = False
            cause = cause or result.cause or f"{name} failed"

    if not check_results and pending_autoraters:
        passed = None

    return CaseRunResult(
        case=case,
        passed=passed,
        check_results=check_results,
        cost=outcome.credits,
        role_costs=role_costs,
        roles=roles,
        cause=cause,
        pending_autoraters=pending_autoraters,
    )


def run_pass(
    *,
    pass_kind: str,
    config: EvalsConfig,
    cases_root: str = "evals/cases",
    group: str | None = None,
    case_ids: list[str] | None = None,
) -> PassResult:
    """Runs one pass (EFF-07): replays each selected case in turn while it
    still fits `config.credit_cap[pass_kind]`. The first case that would
    push spent-plus-estimate over the cap, and every case after it, is
    listed under `not_run` with `stopped_at_cap` set."""
    all_cases = load_cases(root=cases_root)
    selected = _select_cases(all_cases, pass_kind=pass_kind, group=group, case_ids=case_ids, config=config)
    cap = config.credit_cap[pass_kind]

    result = PassResult(pass_kind=pass_kind)
    executor = ReplayExecutor()
    spent = 0.0
    stopped = False

    for case in selected:
        if not _is_runnable(case):
            result.not_runnable.append(case)
            continue
        if stopped:
            result.not_run.append(case)
            continue
        try:
            outcome = executor.run(case)
        except ExecutorError:
            result.not_runnable.append(case)
            continue

        estimate = outcome.credits
        if spent + estimate > cap:
            stopped = True
            result.stopped_at_cap = True
            result.not_run.append(case)
            continue

        spent += estimate
        result.ran.append(_evaluate_case(case, outcome))

    result.spent = spent
    return result
