"""Cost report by task, world tier, model profile and task type (FR-MTR-10, PRD 14.4, 14.5, EV-07).

Pure: no I/O, no clock, no model; inputs are never changed. Spend is the credits each ledger `commit` entry recorded
at the price in effect on its date (FR-MTR-01): nothing is re-priced. Credits saved are FR-MTR-06's, each `memory.hit`
event id once, reported beside spend and never netted off it. A task is a run. Rows only ever name profile ids
(`providers.schema.json` profile_id), never a model id (PL-01), and are sorted so the same inputs in any order give
the same report.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NamedTuple

from .prices import PriceBook
from .savings import hit_saving
from .treasury import LedgerEntry

TIER_ORDER = ("outpost", "village", "town", "city")  # PRD 9.1: world size
_PROFILE_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_UNIT_TYPE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")  # common.schema.json slug, as plan.schema.json unit_type


class _Spend(NamedTuple):
    run: str
    tier: str | None
    profile: str | None
    task_type: str | None
    credits: float


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _profile(entry: LedgerEntry) -> str | None:
    name = entry.usage.profile if entry.usage else None
    return name if isinstance(name, str) and _PROFILE_ID.match(name) else None


def _task_type(unit_types: Mapping[str, Mapping[str, str]], entry: LedgerEntry) -> str | None:
    kind = (unit_types.get(entry.run) or {}).get(entry.step or "")
    return kind if isinstance(kind, str) and _UNIT_TYPE.match(kind) else None


def _order(value: str | None, ranking: tuple[str, ...] = ()) -> tuple[bool, int, str]:
    """Sort key: known names first (by `ranking` if given, else alphabetically), then null."""
    if value is None:
        return (True, 0, "")
    return (False, ranking.index(value) if value in ranking else 0, value)


def _read_events(events: Iterable[Mapping[str, Any]]) -> tuple[dict, set, dict]:
    """(tier of each planned run, completed runs, credits saved per run) from the events; every event id once."""
    latest: dict[str, tuple[int, str, str | None]] = {}
    done: set[str] = set()
    saved: dict[str, list[float]] = {}
    seen: set[str] = set()
    for event in events:
        run, kind = _text(event.get("run_id")), event.get("type")
        if kind == "memory.hit":
            event_id = _text(event.get("id"))
            if event_id in seen:
                continue
            saving = hit_saving(event)  # raises on a hit that disagrees with its own costs
            seen.add(str(event_id))
            if run:
                saved.setdefault(run, []).append(saving)
        elif run and kind == "world.completed":
            done.add(run)
        elif run and kind == "world.planned":
            data = event.get("data")
            tier = data.get("tier") if isinstance(data, Mapping) else None
            seq = event.get("seq")
            key = (seq if isinstance(seq, int) else 0, str(event.get("id")), tier if tier in TIER_ORDER else None)
            if run not in latest or key[:2] > latest[run][:2]:  # a re-plan replaces the tier
                latest[run] = key
    return {run: key[2] for run, key in latest.items()}, done, {run: math.fsum(v) for run, v in saved.items()}


def _groups(items: Iterable[tuple[str, Any, float | None]]) -> dict[Any, tuple[set[str], list[float]]]:
    """key -> (runs, credits): a `None` credits only puts the run in the group."""
    groups: dict[Any, tuple[set[str], list[float]]] = {}
    for run, key, credits in items:
        runs, amounts = groups.setdefault(key, (set(), []))
        runs.add(run)
        if credits is not None:
            amounts.append(credits)
    return groups


def _row(runs: set[str], amounts: list[float], credit_usd: float) -> dict[str, Any]:
    credits = math.fsum(amounts)
    return {
        "tasks": len(runs),
        "credits": credits,
        "usd": credits * credit_usd,
        "credits_per_task": credits / len(runs),  # a group exists only with a run in it
    }


def load_credit_usd(path: str | os.PathLike[str]) -> float:
    """US$ per credit from a prices file (FR-MTR-01): the one place callers of `cost_report` get it from.
    Raises `MeteringConfigError` when the file is unreadable or invalid."""
    return PriceBook.load(path).credit_usd


def cost_report(
    ledger: Iterable[LedgerEntry],
    events: Iterable[Mapping[str, Any]],
    *,
    unit_types: Mapping[str, Mapping[str, str]],
    credit_usd: float,
) -> dict[str, Any]:
    """The report of PRD 14.5 ("cost per task by tier and profile"); shape in services/api/tests/API_FR_MTR_10.md."""
    tier_of, completed, saved = _read_events(events)
    spend = [
        _Spend(e.run, tier_of.get(e.run), _profile(e), _task_type(unit_types, e), e.credits or 0.0)
        for e in ledger
        if e.kind == "commit"
    ]
    runs = sorted({s.run for s in spend} | tier_of.keys() | completed | saved.keys())
    credits_of = _groups((s.run, s.run, s.credits) for s in spend)

    tasks = [
        {
            "run_id": run,
            "tier": tier_of.get(run),
            "completed": run in completed,
            "credits": (c := math.fsum(credits_of.get(run, (set(), []))[1])),
            "usd": c * credit_usd,
            "credits_saved": saved.get(run, 0),
        }
        for run in runs
    ]

    def grouped(name: str, key_of: Callable[[_Spend], Any], *, idle: bool = False) -> list[dict[str, Any]]:
        """Rows for the group `name` ("tier", "profile", "tier+profile"); a tier is ranked by world size."""
        items: list[tuple[str, Any, float | None]] = [(s.run, key_of(s), s.credits) for s in spend]
        if idle:  # a planned run with no spend still counts as a task in its tier
            items += [(run, tier_of.get(run), None) for run in runs]
        names = name.split("+")
        ranks = [TIER_ORDER if n == "tier" else () for n in names]
        rows = []
        for key, (members, amounts) in _groups(items).items():
            parts = key if isinstance(key, tuple) else (key,)
            row = dict(zip(names, parts, strict=True)) | _row(members, amounts, credit_usd)
            if idle:
                row["credits_saved"] = math.fsum(saved.get(run, 0) for run in members)
            rows.append((tuple(_order(p, rank) for p, rank in zip(parts, ranks, strict=True)), row))
        return [row for _, row in sorted(rows, key=lambda pair: pair[0])]

    total = math.fsum(s.credits for s in spend)
    total_saved = math.fsum(saved.values())
    return {
        "credit_usd": credit_usd,
        "totals": {
            "tasks": len(runs),
            "completed_tasks": len(completed),
            "credits": total,
            "usd": total * credit_usd,
            "credits_saved": total_saved,
            "usd_saved": total_saved * credit_usd,
        },
        "tasks": tasks,
        "by_tier": grouped("tier", lambda s: s.tier, idle=True),
        "by_profile": grouped("profile", lambda s: s.profile),
        "by_task_type": grouped("task_type", lambda s: s.task_type),
        "by_tier_profile": grouped("tier+profile", lambda s: (s.tier, s.profile)),
    }
