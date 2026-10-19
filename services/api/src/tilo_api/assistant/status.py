"""FR-PA-08 (API_FR_PA_08.md): the `status` and `weekly` fact intents. Pure templates over rows the oracle already
admitted and over the person's own finished work items; no clock (`now` is an argument), no I/O, no model. A title
is only ever a value in a config template, so it can change no fixed word, no source and no count."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tilo_api.assistant.config import AssistantConfig, FactIntent
from tilo_api.assistant.facts import Line, claim, fill, moment_of
from tilo_api.assistant.gate import Ref

Row = Mapping[str, Any]
_WAITING = ("gate", "consent", "question", "meeting_card")


def _ref(row: Row) -> Ref:
    return Ref(row["ref"]["kind"], row["ref"]["id"])


def day_start(now: datetime, zone: ZoneInfo | None, days_back: int) -> datetime:
    """00:00 of the person's local day `days_back` days before the day of `now`, as an instant (section 2)."""
    tz = zone or UTC
    return datetime.combine(now.astimezone(tz).date() - timedelta(days=days_back), time.min, tz).astimezone(UTC)


def status_lines(
    intent: FactIntent,
    rows: Sequence[Row],
    parked: Sequence[Row],
    *,
    now: datetime,
    zone: ZoneInfo | None,
    config: AssistantConfig,
) -> tuple[tuple[Line, ...], Mapping[str, Any] | None]:
    """Running tasks, then what changed since 00:00 yesterday; `rows` and `parked` are gated, in plate order."""
    a, cap = config.answer, config.answer["max_lines"]
    since = day_start(now, zone, 1)
    seen: set[Ref] = set()
    tasks: list[Line] = []
    changed: list[Line] = []
    for row in rows:
        ref = _ref(row)
        if ref in seen:
            continue
        if ref.kind == "world":
            if row["reason"] in ("run", "blocked"):
                seen.add(ref)
                tasks.append(Line(claim(row, a["lines"][row["reason"]], config), ref))
        elif row["reason"] != "calendar":
            at = moment_of(row["at"])
            if at is not None and since <= at <= now:
                seen.add(ref)
                changed.append(Line(claim(row, a["lines"][row["reason"]], config), ref))
    listed = {_ref(r) for r in rows}
    for row in parked:  # the `done` lane of work items: finished in the last 24 hours, so always a change (PE-27)
        ref = _ref(row)
        if row["group"] == "done" and ref.kind == "work_item" and ref not in listed and ref not in seen:
            seen.add(ref)
            changed.append(Line(claim(row, a["status"]["done"], config, due=False), ref))
    if not tasks and not changed:
        return (Line(intent.empty, None),), None
    lines = [Line(intent.header or "", None), *(tasks[:cap] or [Line(a["status"]["tasks_empty"], None)])]
    lines += [Line(a["status"]["changed_header"], None), *(changed[:cap] or [Line(a["status"]["changed_empty"], None)])]
    if len(tasks) <= cap and len(changed) <= cap:
        return tuple(lines), None
    return (*lines, Line(a["more"], None)), {"kind": "navigate", "route": "plate", "target": None}


def _done_stamp(item: Row, start: datetime, now: datetime) -> datetime | None:
    """When the item was last marked done, if it is done now and that was inside the window."""
    if item.get("status") != "done" or not isinstance(item.get("history"), list):
        return None
    stamps = [moment_of(h.get("at")) for h in item["history"] if isinstance(h, Mapping) and h.get("change") == "done"]
    latest = max((s for s in stamps if s is not None), default=None)
    return latest if latest is not None and start <= latest <= now else None


def weekly_lines(
    intent: FactIntent,
    rows: Sequence[Row],
    finished: Sequence[Row],
    *,
    truncated: bool,
    now: datetime,
    zone: ZoneInfo | None,
    config: AssistantConfig,
) -> tuple[tuple[Line, ...], None]:
    """Five counts over the last seven local days; `finished` holds the person's own, oracle-admitted work items."""
    w, start = config.answer["weekly"], day_start(now, zone, 6)
    done: dict[str, datetime] = {}
    for item in finished:
        stamp = _done_stamp(item, start, now)
        if stamp is not None and isinstance(item.get("id"), str):
            done[item["id"]] = stamp
    latest = min(done, key=lambda wid: (-done[wid].timestamp(), wid), default=None)
    plus = w["truncated"] if truncated else ""
    groups = (
        ("open", [r for r in rows if r["ref"]["kind"] == "work_item" and r["reason"] == "work_item"]),
        ("overdue", [r for r in rows if r["group"] == "overdue"]),
        ("tasks", [r for r in rows if r["ref"]["kind"] == "world" and r["reason"] in ("run", "blocked")]),
        ("waiting", [r for r in rows if r["reason"] in _WAITING]),
    )
    counts = [Line(fill(w["done"], n=str(len(done))), None if latest is None else Ref("work_item", latest))]
    counts += [Line(fill(w[name], n=f"{len(hit)}{plus}"), _ref(hit[0]) if hit else None) for name, hit in groups]
    if not any(line.source is not None for line in counts):
        return (Line(intent.empty, None),), None
    return (Line(intent.header or "", None), *counts), None
