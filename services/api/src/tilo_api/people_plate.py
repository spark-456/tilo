"""The plate read model (PPL-11a slice B; ADR-0021, people.rules.md PE-26 to PE-30). One builder, per request, for the
signed-in person only, never stored and never an event. Six sources: the person's own work items, pins and calendar
entries from the people stores (each read through `decide`, so PE-01 to PE-08 hold as everywhere else) and cards,
runs and mail from the plate sources, filtered again here by owner, world role and state. Groups, order, caps and the
fingerprint are code (PE-28, PE-30). A source that cannot be read, a fact that is not what it should be or a plate that
does not validate raises, and the route answers 503: an honest plate is complete or absent (HR-1). No model, no clock
read (`now` is handed in), no network, no artifact store, no redactor.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tilo_people.access import AccessRequest, decide
from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores
from tilo_people.text import clean_line
from tilo_policy.schemas import conforms

from tilo_api.deps import PlateSources, SourceOwners
from tilo_api.people_quotes import MAX_HISTORY

ROWS_CAP, PARKED_CAP = 200, 100
ORDER = ("attention", "overdue", "soon", "rest", "snoozed", "asked", "done")
Found = tuple[str, dict[str, Any]]  # (lane, row)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _title(text: str | None) -> str | None:
    """Cleaned like a quote line (PE-24, PE-29) and cut to 140 characters; U+2065 is unassigned, so only the title
    schema bans it."""
    return (clean_line(text or "").replace("⁥", ""))[:140] or None


def _row(kind: str, record_id: str, reason: str, **fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ref": {"kind": kind, "id": record_id},
        "reason": reason,
        "group": None,
        "title": None,
        "due": None,
        "at": None,
        "from": None,
        "flagged": False,
        "evidence": False,
        "actions": ["open"],
    }
    return row | fields


def _group(row: Mapping[str, Any], today: str) -> str:
    """PE-28: the group of a row in `rows`."""
    soon = (date.fromisoformat(today) + timedelta(days=2)).isoformat()
    if row["reason"] in ("gate", "consent", "blocked"):
        return "attention"
    if row["due"] is not None and row["due"] < today:
        return "overdue"
    if (row["due"] is not None and row["due"] <= soon) or row["reason"] in ("calendar", "question", "meeting_card"):
        return "soon"
    return "rest"


def _order(row: Mapping[str, Any]) -> tuple[int, str, str, str, str]:
    """PE-28: group, then due and `at` ascending (null last), then kind and id."""
    ref = row["ref"]
    return ORDER.index(row["group"]), row["due"] or "~", row["at"] or "~", ref["kind"], ref["id"]


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    """PE-30: SHA-256 of `rows` as JSON with sorted keys and no whitespace."""
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


@dataclass
class _Ask:
    """Who asks, when, and what the builder may read through."""

    stores: PeopleStores
    owners: SourceOwners
    org: str
    actor: str
    now: str
    directory: Directory
    zone: tzinfo
    today: str
    _meetings: dict[str, Mapping[str, Any] | None] = field(default_factory=dict)

    def meeting(self, ref: str | None) -> Mapping[str, Any] | None:
        """The stored meeting (or its PE-19 tombstone) a record's source names; none when there is none."""
        meeting_id = (ref or "").partition("#")[0]
        if meeting_id not in self._meetings:
            found = self.stores.meetings.get(self.org, meeting_id) if meeting_id else None
            self._meetings[meeting_id] = None if found is None else found.record
        return self._meetings[meeting_id]

    def may_read(self, kind: str, record: Mapping[str, Any], **extra: Any) -> bool:
        request = AccessRequest(self.actor, "read_full", kind, record, self.now, **extra)
        return decide(request, self.directory).allowed


def _work_items(a: _Ask, items: Iterable[Mapping[str, Any]]) -> Iterable[Found]:
    for wi in items:
        if wi["owner"] != a.actor or wi["status"] not in ("open", "done") or len(wi["history"]) > MAX_HISTORY:
            continue  # cheap checks first: an unreadable record never reaches `decide`
        source = wi["source"]
        meeting = a.meeting(source["ref"]) if source["kind"] == "meeting" else None
        if not a.may_read("work_item", wi, meeting=meeting):
            continue
        if wi["status"] == "done":
            if _ts(a.now) - _ts(wi["updated_at"]) > timedelta(hours=24):
                continue
            lane, group = "parked", "done"
        else:
            asked = wi["history"][-1]["change"] == "reassign_requested"
            snoozed = (wi["snoozed_until"] or "") > a.now  # asked wins over snoozed (ambiguity 12)
            lane, group = ("parked", "asked" if asked else "snoozed") if asked or snoozed else ("rows", "")
        assigner = (wi["assigned_by"] or {}).get("by")
        other = assigner if assigner and assigner != a.actor else None
        actions = ["open", "put_back"] if lane == "parked" else ["open", "done", "snooze"]
        yield (
            lane,
            _row(
                "work_item",
                wi["id"],
                "work_item",
                group=group,
                title=_title(wi["title"]),
                due=wi["due"],
                at=wi["created_at"],
                **{"from": other},
                flagged=bool(wi.get("flagged")),
                evidence=source["kind"] == "meeting" and bool(source["evidence"]),
                actions=[*actions, *(["not_mine"] if other else [])],
            ),
        )


def _pins(a: _Ask, me: Mapping[str, Any]) -> Iterable[Found]:
    tagged = {
        (m.record["pin_id"], m.record["team"])
        for m in a.stores.mentions.list(a.org, "user", a.actor)
        if m.record["removed"] is None
    }
    pins = {s.record["id"]: s.record for s in a.stores.pins.list(a.org, "scope.user", a.actor)}
    for team in sorted({m["team"] for m in me["memberships"]}):
        pins |= {s.record["id"]: s.record for s in a.stores.pins.list(a.org, "scope.team", team)}
    for pin in pins.values():
        scope = pin["scope"]
        if pin["status"] != "active" or len(pin["history"]) > MAX_HISTORY:
            continue
        if scope["kind"] == "personal":
            if scope["user"] != a.actor or pin["due"] is None:
                continue
        elif pin["owner"] != a.actor and (pin["id"], scope["team"]) not in tagged:
            continue
        source = pin["source"] or {}
        meeting = a.meeting(source.get("ref")) if source.get("kind") == "meeting" else None
        asked_owner = pin["created_by"]["by"] == "tilo" and source.get("kind") in ("mail", "request") and source["ref"]
        owner = a.owners.owner_of(source["kind"], source["ref"]) if asked_owner else None
        if not a.may_read("pinboard_item", pin, meeting=meeting, source_owner=owner):
            continue
        mine = scope["kind"] == "personal" or pin["owner"] == a.actor
        yield (
            "rows",
            _row(
                "pinboard_item",
                pin["id"],
                "pin_owner" if mine else "pin_tagged",
                title=_title(pin["title"]),
                due=pin["due"],
                at=pin["updated_at"],
                **{"from": pin["set_up_by"] if pin["set_up_by"] != a.actor else None},
                flagged=bool(pin.get("flagged")),
            ),
        )


def _calendar(a: _Ask, items: Iterable[Mapping[str, Any]]) -> Iterable[Found]:
    released = {i["source"]["ref"]: i for i in items if i["source"]["ref"] and len(i["history"]) <= MAX_HISTORY}
    for entry in (s.record for s in a.stores.calendar.list(a.org, "owner", a.actor)):
        if entry["owner"] != a.actor or entry["state"] not in ("accepted", "proposed"):
            continue
        if _ts(entry["start"]).astimezone(a.zone).date().isoformat() != a.today:
            continue
        source, meeting, owner, item = entry["source"], None, None, None
        if source["kind"] == "tilo" and source["from"] in ("meeting", "transcript"):
            meeting, item = a.meeting(source["ref"]), released.get(source["ref"])
        elif source["kind"] == "tilo" and source["ref"]:
            owner = a.owners.owner_of(source["from"], source["ref"])
        elif source["kind"] == "google":
            owner = a.actor  # a sync writes the connected person's own entries only (PE-08)
        if not a.may_read("calendar_entry", entry, meeting=meeting, work_item=item, source_owner=owner):
            continue
        yield (
            "rows",
            _row(
                "calendar_entry",
                entry["id"],
                "calendar",
                title=_title(entry["title"]),
                at=entry["start"],
                flagged=bool(entry.get("flagged")),
            ),
        )


def _cards(a: _Ask, facts: Iterable[Mapping[str, Any]]) -> Iterable[Found]:
    for fact in facts:
        card = fact["data"]
        expired = _ts(card["created_at"]) + timedelta(seconds=card["timeout"]) <= _ts(a.now)
        mine = fact["world_owner"] == a.actor or (card["kind"] == "gate" and fact["approver"] == a.actor)
        if not mine or fact["answered"] is not False or expired:
            continue
        kind = card["kind"]
        blocked = "blocked" if card["rung"] == "blocked" else "question"
        reason = {"meeting": "meeting_card", "needs_you": blocked}.get(kind, kind)
        yield "rows", _row("card", card["id"], reason, title=_title(card["what_happened"]), at=card["created_at"])


def _runs(a: _Ask, facts: Iterable[Mapping[str, Any]]) -> Iterable[Found]:
    for run in facts:
        if run["world_owner"] != a.actor or run["state"] not in ("running", "blocked"):
            continue
        yield (
            "rows",
            _row(
                "world",
                run["world_id"],
                "blocked" if run["state"] == "blocked" else "run",
                title=_title(run["goal"]),
                due=run["deadline"],
                at=run["started_at"],
            ),
        )


def _mail(a: _Ask, facts: Iterable[Mapping[str, Any]]) -> Iterable[Found]:
    for mail in facts:
        if mail["account_owner"] != a.actor or mail["answered"] is not False or mail["dismissed"] is not False:
            continue
        yield (
            "rows",
            _row(
                "mail",
                mail["message_id"],
                "mail_reply",
                at=mail["received_at"],
                flagged=mail["flagged"] is True,
                actions=["open", "draft_reply"],
            ),
        )


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return UTC


def build_plate(
    stores: PeopleStores, sources: PlateSources, owners: SourceOwners, org: str, actor: str, now: str
) -> dict[str, Any] | None:
    """The plate of `actor` at `now`, or None when Tilo has no such person in `org` (the route's 404). Raises when a
    source or a store cannot be read (the route's 503)."""
    directory = Directory.of(s.record for s in stores.persons.list(org))
    me = directory.record(actor)
    if me is None:
        return None
    zone = _zone(me["time_zone"])
    today = _ts(now).astimezone(zone).date().isoformat()
    ask = _Ask(stores, owners, org, actor, now, directory, zone, today)
    items = [s.record for s in stores.work_items.list(org, "owner", actor)]
    found = [
        *_work_items(ask, items),
        *_pins(ask, me),
        *_calendar(ask, items),
        *_cards(ask, list(sources.cards(actor))),
        *_runs(ask, list(sources.runs(actor))),
        *_mail(ask, list(sources.mail(actor))),
    ]
    for lane, row in found:
        row["group"] = _group(row, today) if lane == "rows" else row["group"]
    rows = sorted((r for lane, r in found if lane == "rows"), key=_order)
    parked = sorted((r for lane, r in found if lane == "parked"), key=_order)
    plate = {
        "v": "1.0",
        "user": actor,
        "as_of": now,
        "today": today,
        "rows": rows[:ROWS_CAP],
        "parked": parked[:PARKED_CAP],
        "truncated": len(rows) > ROWS_CAP or len(parked) > PARKED_CAP,
        "fingerprint": _fingerprint(rows[:ROWS_CAP]),
    }
    if not conforms("plate.schema.json", plate):
        raise ValueError("the plate does not validate")
    return plate
