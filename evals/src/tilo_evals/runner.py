"""The eval runner (EFF-07; PRD 19.1-19.3, 6.6 "Lean evals", MT-09).

Picks the cases for a pass (smoke | full | gate), replays each in turn while it still fits the pass's credit
cap (config/evals.yaml), and runs its deterministic checks. Autorater checks are not run here: they are
reported as pending and never count as a pass. Dev and CI replay recordings, so nothing here is paid.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import checks as checks_registry
from .cases import Case, load_cases
from .checks import CheckResult
from .config import EvalsConfig
from .executors import Executor, ExecutorError, ReplayExecutor

PASS_KINDS = ("smoke", "full", "gate")


class SelectionError(ValueError):
    """The pass kind, --case or --group names nothing: the pass cannot run as asked."""


def _one_line(text: str) -> str:
    """One bounded line: a reason or cause can echo recorded text, and results.md is split on lines."""
    return " ".join(text.split())[:300]


@dataclass
class CaseRunResult:
    case: Case
    passed: bool | None  # None: only autorater checks, still pending
    check_results: list[dict[str, Any]] = field(default_factory=list)
    cost: float = 0.0
    role_costs: dict[str, float] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)  # model_role -> profile name, never a model id
    cause: str | None = None
    pending_autoraters: list[str] = field(default_factory=list)
    events: tuple[dict[str, Any], ...] = ()  # the replayed outcome, kept for the EV metrics (metrics.py)
    outputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class PassResult:
    pass_kind: str
    cap: float = 0.0
    ran: list[CaseRunResult] = field(default_factory=list)
    not_run: list[Case] = field(default_factory=list)
    not_runnable: dict[str, str] = field(default_factory=dict)  # case id -> why
    case_groups: dict[str, str] = field(default_factory=dict)  # case id -> group, for every selected case
    stopped_at_cap: bool = False
    stop_reason: str | None = None
    spent: float = 0.0

    @property
    def repeated(self) -> bool:
        """True when a case ran more than once (deploy-gate repeats), so counts are of runs, not cases."""
        ids = [r.case.id for r in self.ran]
        return len(ids) != len(set(ids))

    @property
    def failed(self) -> list[CaseRunResult]:
        return [r for r in self.ran if r.passed is False]


def _is_runnable(case: Case) -> bool:
    return case.status != "skeleton" and bool(case.recording)


def _select(
    cases: list[Case], pass_kind: str, group: str | None, case_ids: list[str], config: EvalsConfig
) -> list[Case]:
    if case_ids and (unknown := sorted(set(case_ids) - {c.id for c in cases})):
        raise SelectionError(f"unknown case id(s): {', '.join(map(_one_line, unknown))}")
    if group and not any(c.group == group for c in cases):
        raise SelectionError(f"no cases in group {_one_line(group)!r}")
    selected = [c for c in cases if c.id in case_ids] if case_ids else [c for c in cases if group in (None, c.group)]
    repeats = config.deploy_gate_repeats
    if pass_kind == "smoke":  # one ready, runnable case per group
        picked: dict[str, Case] = {}
        for case in sorted(selected, key=lambda c: c.id):
            if case.status == "ready" and _is_runnable(case):
                picked.setdefault(case.group, case)
        return list(picked.values())
    if pass_kind == "gate":  # deploy-gate cases only, each repeated
        return [c for c in selected if c.deploy_gate] * repeats
    # full: every case once, deploy-gate cases deploy_gate_repeats times (PRD 19.2, MT-09)
    return [c for case in selected for c in [case] * (repeats if case.deploy_gate else 1)]


def _evaluate(case: Case, outcome: Any) -> CaseRunResult:
    role_costs: dict[str, float] = {}
    roles: dict[str, str] = {}
    for event in outcome.events:
        trace = event.get("trace") or {}
        if role := trace.get("model_role"):
            role_costs[role] = role_costs.get(role, 0.0) + float(event.get("credits") or 0.0)
            if trace.get("profile"):
                roles[role] = trace["profile"]
    results: list[dict[str, Any]] = []
    pending: list[str] = []
    cause: str | None = None
    for entry in case.checks:
        name = entry["check"]
        if entry.get("kind") == "autorater" or checks_registry.kind(name) == "autorater":
            pending.append(name)
            continue
        try:
            result = checks_registry.get(name)(case, outcome, entry["args"])
        except Exception as exc:  # noqa: BLE001 - a bad check or args fails the case, never the pass
            result = CheckResult(False, f"{name}: check raised {type(exc).__name__}: {exc}")
        results.append({"check": name, "passed": result.passed, "cause": result.cause})
        if not result.passed and cause is None:  # one line, bounded: a cause can echo recorded text
            cause = _one_line(result.cause or f"{name} failed")
    passed = None if not results and pending else cause is None
    return CaseRunResult(
        case, passed, results, outcome.credits or 0.0, role_costs, roles, cause, pending,
        tuple(outcome.events), dict(outcome.outputs),
    )  # fmt: skip


def run_pass(
    *,
    pass_kind: str,
    config: EvalsConfig,
    cases_root: str = "evals/cases",
    base: Path = Path("."),
    group: str | None = None,
    case_ids: list[str] | None = None,
    executor: Executor | None = None,
) -> PassResult:
    """Runs one pass (MT-09). A case that would take spent-plus-its-recorded-cost over `credit_cap[pass_kind]`,
    and every case after it, is listed under `not_run`, with `stopped_at_cap` and `stop_reason` set. A pass
    whose cap is already reached starts no further case. The cap is never exceeded."""
    if pass_kind not in PASS_KINDS:
        raise SelectionError(f"pass kind must be one of {PASS_KINDS}, got {pass_kind!r}")
    selected = _select(load_cases(root=cases_root), pass_kind, group, case_ids or [], config)
    cap = float(config.credit_cap[pass_kind])
    result = PassResult(pass_kind, cap=cap, case_groups={c.id: c.group for c in selected})
    executor = executor or ReplayExecutor(base)
    for case in selected:
        if result.stopped_at_cap:
            result.not_run.append(case)
            continue
        if not _is_runnable(case):
            result.not_runnable[case.id] = "status skeleton" if case.status == "skeleton" else "no recording"
            continue
        try:
            outcome = executor.run(case)
        except ExecutorError as exc:
            result.not_runnable[case.id] = _one_line(str(exc))
            continue
        cost = outcome.credits or 0.0
        if not math.isfinite(cost) or result.spent >= cap or result.spent + cost > cap:
            result.stopped_at_cap = True
            result.stop_reason = (
                f"credit cap for the {pass_kind} pass is {cap:g}: {result.spent:g} spent, {case.id} needs {cost:g}"
            )
            result.not_run.append(case)
            continue
        result.spent += cost
        result.ran.append(_evaluate(case, outcome))
    return result
