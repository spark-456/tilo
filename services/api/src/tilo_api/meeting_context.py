"""ADR-0042 amendment 1 (owner 21 Oct, relayed): what the meeting bot may know of the meeting owner's Tilo workspace.

Read-only and compact: the meeting OWNER's own view (the attend's claim names them; a caption name never picks whose).
One-on-one: their teams and teammates, pins (personal and team), upcoming meetings and recent worlds. In a group call
only what their teams share: team names, teammates and ACTIVE team pins, never a personal item, because others are
listening (the bot narrows it further unless everyone present is the owner or a teammate). Flagged pins never.
Titles and names only, each cut to `MAX_TEXT`; no body, link, attendee, id or record text beyond them. Every list goes
through the same functions and access rules a signed-in request uses (`list_pins`, `list_meetings`, the worlds list's
`_item`), and world loads never settle runs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from tilo_api import deps
from tilo_api.people_meetings import list_meetings
from tilo_api.people_pins import list_pins
from tilo_api.people_teams import _entry_view
from tilo_api.people_writes import Writer
from tilo_api.worlds_list import _item

MAX_TEXT, MAX_PINS, MAX_MEETINGS, MAX_WORLDS, MAX_TEAMMATES = 80, 15, 8, 5, 20
_UPCOMING = ("scheduled", "joining", "live")
_RECENT = timedelta(hours=12)  # a meeting that started this long ago still counts as today's


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:MAX_TEXT] or None


def build(
    w: Writer, owners: deps.SourceOwners, store: deps.Store, names: Mapping[str, str], *, one_on_one: bool
) -> dict[str, Any]:
    """The owner's (`w.actor`'s) context for the bot's model; a missing person record raises the 404 Refusal."""
    pins = list_pins(w, owners)["items"]  # first: the 404 for a person with no record
    d = w.org_directory()
    me = d.record(w.actor) or {}
    teams = [v for m in me.get("memberships", []) if (v := _entry_view(d, w.actor, m, w.now, names))]
    teams = [v for v in teams if v["state"] == "member"]
    mates: dict[str, dict[str, Any]] = {}
    for team in teams:
        for uid, person in d.persons.items():
            if uid != w.actor and d.is_member(uid, team["team"], w.now):
                seen = mates.setdefault(uid, {"name": _text(person.get("display_name")), "lead": False})
                seen["lead"] = seen["lead"] or d.is_lead(uid, team["team"], w.now)
    # A flagged pin (screened text from mail or minutes) never reaches the model; a group hears only ACTIVE team pins,
    # never one Tilo proposed that the owner has not confirmed (only they can read it yet).
    pins = [p for p in pins if not p.get("flagged")]
    shared = [p for p in pins if _board(p) == "team" and p.get("status") == "active"]
    context: dict[str, Any] = {
        "you": _text(me.get("display_name")),  # the bot checks who is present against the owner and the teammates
        "teams": [{"name": _text(t["name"]), "lead": t["lead"]} for t in teams],
        "teammates": sorted(mates.values(), key=lambda m: m["name"] or "")[:MAX_TEAMMATES],
        "pins": _pins(pins if one_on_one else shared),
    }
    if not one_on_one:
        return context
    context["role"] = me.get("org_role")
    context["meetings"] = _meetings(list_meetings(w)["items"], w.now)
    context["worlds"] = _worlds(w.actor, store)
    return context


def _pins(pins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    newest = sorted(pins, key=lambda p: (p.get("created_at") or "", p.get("id") or ""), reverse=True)
    return [{"title": _text(p.get("title")), "board": _board(p)} for p in newest[:MAX_PINS]]


def _board(pin: dict[str, Any]) -> str:
    return "team" if (pin.get("scope") or {}).get("kind") == "team" else "personal"


def _meetings(meetings: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    since = datetime.fromisoformat(now.replace("Z", "+00:00")) - _RECENT
    rows = []
    for m in meetings:
        start = (m.get("scheduled") or {}).get("start")
        if m.get("status") not in _UPCOMING or not isinstance(start, str):
            continue
        if datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(UTC) < since:
            continue
        rows.append({"title": _text(m.get("title")), "start": start, "status": m["status"]})
    return sorted(rows, key=lambda r: r["start"])[:MAX_MEETINGS]


def _worlds(owner: str, store: deps.Store) -> list[dict[str, Any]]:
    store.load_owner(owner, settle=False)  # a read never settles a run
    viewer = deps.Principal(user_id=owner, role="owner")  # the owner's own view of their own worlds, nothing else
    items = [
        _item(viewer, store, wid, rec)
        for wid, rec in list(store.worlds.items())
        if rec.owner == owner and wid != deps.SAMPLE_WORLD_ID
    ]
    items = [i for i in items if _text(i["title"])]  # the Desk and other untitled worlds say nothing to a person
    items.sort(key=lambda i: i["created_at"] or "", reverse=True)
    return [{"title": _text(i["title"]), "status": i["status"]} for i in items[:MAX_WORLDS]]
