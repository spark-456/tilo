"""Shared, non-test support for the FR-CAL-07 part (a) acceptance tests (the assistant panel half: "what is on my
calendar today" and "what should I prepare for the 3pm"; interface: services/api/tests/API_FR_CAL_07a.md).

Not a test module. The unique module name matters: every test directory shares one `sys.path` under pytest's prepend
mode. Built on `_ppl11b_lib` (the assistant rig: the real `tilo_api.app`, the real `tilo_people` oracle over in-memory
stores, a fake plate source, a scripted decider, a fixed clock).

Rules this file follows (root CLAUDE.md, test-writer):

- No business logic. The oracles below (`expected_today`, `expected_prepare`) are independent implementations of
  API_FR_CAL_07a.md sections 2 and 3: they read the existing line templates from config/assistant.yaml and carry the
  new fixed words in `TEXT`, which is the spec's wording; they never import `tilo_api.assistant`.
- Nothing from a module that does not exist yet is imported at module level.
- No unicode escape sequences and no non-ASCII characters in a test file: code points are built with `chr()`.
- No network, no paid call, no real account. A fake secret is assembled at run time (`FAKE_KEY`).
"""

from __future__ import annotations

import string
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from _ppl11b_lib import (
    ANSWER,
    INTENTS,
    ORG,
    PRIYA,
    SAM,
    ScriptedDecider,
    World,
    build_world,
    calendar_entry,
    hist,
    make_plate,
    maker,
    model_decision,
    plate_row,
    s1_rows,
    stamp,
    work_item,
)

# Each slice is a strict xfail until its builder deletes its entry (API_FR_CAL_07a.md section 0). An entry is a
# substring of a pytest node id, so it names a whole file. `test_FR_CAL_07a_guards.py` is never pending: it passes
# today and must keep passing.
SLICE_PENDING: tuple[str, ...] = ()
PENDING_EXEMPT: tuple[str, ...] = ("test_FR_CAL_07a_guards",)

IST = "Asia/Kolkata"
PREPARE = "calendar_prepare"  # the new fact intent id
TODAY_INTENT = "calendar_today"  # the existing one, amended
ZONE = ZoneInfo(IST)

# The fixed words of the new answers (API_FR_CAL_07a.md sections 3 and 4). $label, $start, $end, $n are the only
# placeholders. The builder puts these in config/assistant.yaml (`answer.prepare.*`, `declines.which_entry`).
TEXT: dict[str, str] = {
    "header": "To prepare:",
    "entry": "$label at $start to $end",
    "entry_open": "$label at $start",
    "attendees": "Other attendees: $n",
    "meeting": "Meeting: $label",
    "item": "Action item: $label",
    "nothing": "Nothing else is linked to it.",
    "which_entry": "Which calendar entry do you mean? Say its start time, like the 3pm.",
}
PREPARE_KEYS = ("header", "entry", "entry_open", "attendees", "meeting", "item", "nothing")

# Phrasings that must resolve (each is asked against the entry at 15:00 Asia/Kolkata of the standard world).
PREPARE_QUESTIONS: tuple[str, ...] = (
    "What should I prepare for the 3pm?",
    "what should i prepare for the 3 pm meeting",
    "What should I prepare for my 3:00pm?",
    "Prep for the 15:00 please",
    "What do I need to prepare for the 3pm one",
    "Anything to prepare for the 3 PM?",
    "what should I prepare for the 3pm meeting on my calendar",
    "What should I prepare for my 3pm today?",
)

# (phrase, local "HH:MM" it names). 12pm is noon, 12am is midnight; a colon without am/pm is 24-hour.
TIME_FORMS: tuple[tuple[str, str], ...] = (
    ("3pm", "15:00"),
    ("3 pm", "15:00"),
    ("3:30pm", "15:30"),
    ("3:30 PM", "15:30"),
    ("15:30", "15:30"),
    ("9am", "09:00"),
    ("9:05 am", "09:05"),
    ("12pm", "12:00"),
    ("12am", "00:00"),
    ("12:05 am", "00:05"),
    ("11:59pm", "23:59"),
    ("23:45", "23:45"),
    ("0:30", "00:30"),
)
# Not a time of day: the rules find no time and decline with `which_entry`.
NOT_A_TIME = (
    "What should I prepare for the 13pm?",
    "What should I prepare for the 3:75pm?",
    "What should I prepare for the 25:00?",
    "What should I prepare for the 0pm?",
    "What should I prepare for meeting 3?",
    "What should I prepare?",
    "Prepare",
)


# ---------------------------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------------------------
def quiet_decider() -> ScriptedDecider:
    """A decider that declines when asked, so a question no rule reads fails on `decided_by` and the call count (a
    rule-answered question must never reach it) instead of on an exception inside the decider."""
    return ScriptedDecider(default=model_decision("decline"))


def ist(hour: int, minute: int = 0, day: int = 0) -> str:
    """The instant (UTC stamp) of `hour:minute` Asia/Kolkata on the person's local day of NOW plus `day` days."""
    local = datetime(2026, 10, 6, hour, minute, tzinfo=ZONE) + timedelta(days=day)
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def clock(stamp_text: str | None, tz: str = IST) -> str:
    assert stamp_text is not None
    moment = datetime.strptime(stamp_text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return moment.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def fill(template: str, **values: str) -> str:
    return string.Template(template).substitute(**values)


# ---------------------------------------------------------------------------------------------
# Records, worlds, plates
# ---------------------------------------------------------------------------------------------
def entry(
    cid: str,
    title: str,
    start: str,
    end: str | None = None,
    *,
    state: str = "accepted",
    owner: str = SAM,
    attendees: int = 0,
    share: str | None = None,
    flagged: bool = False,
    tilo_ref: str | None = None,
) -> dict[str, Any]:
    """A calendar entry. `tilo_ref` makes it Tilo's proposal from that meeting (and, when accepted, confirmed by the
    owner: PE-07); otherwise it is the person's own manual entry."""
    rec = calendar_entry(cid, owner, title, start, start, share=share, state=state)
    rec["end"] = end
    rec["attendee_count"] = attendees
    rec["flagged"] = flagged
    if tilo_ref is not None:
        rec["source"] = {"kind": "tilo", "from": "meeting", "ref": tilo_ref}
        rec["created_by"] = maker("A_cal", "tilo")
        if state == "accepted":
            rec["confirmed_by"] = stamp(owner)
    return rec


def cal_world(entries: Iterable[Mapping[str, Any]] = (), *, keep_plan: bool = False) -> World:
    """The standard org (`_ppl11b_lib.build_world`) with Sam's `ce_plan1` (15:00 to 16:00 IST) removed unless
    `keep_plan`, then `entries` created. Priya's `ce_priya_private` (13:30 IST) and `ce_priya_shared` (17:30 IST,
    shared with tm_launch, readable by Sam through the team calendar) stay."""
    world = build_world()
    if not keep_plan:
        world.stores.calendar.delete(ORG, "ce_plan1", expected_version=1)
    for rec in entries:
        world.stores.calendar.create(dict(rec))
    world.reset_log()
    return world


def linked_sam() -> tuple[World, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(world, entry, meeting, item): Sam's own meeting `mt_samsync1` ("Sam sync"), minuted and confirmed by him, a
    released action item `wi_prep1` of his from it (due 2026-10-09) and his accepted Tilo-made entry `ce_prep1`
    "Budget review" 17:00 to 17:45 IST with 2 other attendees that cites the item (`mt_samsync1#ai1`). All three are
    readable by Sam; `ce_plan1` is removed."""
    world = cal_world()
    minuted = {
        **world.stores.meetings.get(ORG, "mt_samsync1").record,
        "status": "minuted",
        "transcript": {"artifact_id": "art_transcript2", "version": 1},
        "minutes": {"artifact_id": "art_minutes2", "version": 1},
        "minutes_confirmed_by": stamp(SAM),
    }
    world.replace_record("meetings", minuted)
    item = work_item("wi_prep1", SAM, "Send the budget deck", due="2026-10-09")
    item.update(
        created_by=maker("A_notes", "tilo"),
        assigned_by=stamp(SAM),
        confirmed_by=stamp(SAM, "2026-10-02T09:00:00.000Z"),
        source={"kind": "meeting", "ref": "mt_samsync1#ai1", "evidence": ["u0004"]},
        history=[hist("A_notes", "created", "proposed"), hist(SAM, "confirmed", "open", "2026-10-02T09:00:00.000Z")],
    )
    world.stores.work_items.create(item)
    rec = entry("ce_prep1", "Budget review", ist(17), ist(17, 45), attendees=2, tilo_ref="mt_samsync1#ai1")
    world.stores.calendar.create(rec)
    world.reset_log()
    return world, rec, minuted, item


def linked_priya() -> tuple[World, dict[str, Any], dict[str, Any]]:
    """(world, entry, item): Priya's meeting `mt_priya1` (title holds a sentinel; Sam cannot read it), minuted and
    confirmed by her, the action item `wi_released` she released to Sam ("Released action item") and Sam's accepted
    Tilo-made entry `ce_rel1` "Follow-up slot" 17:00 to 17:30 IST that cites it. Sam reads the entry and the item,
    never the meeting. `ce_plan1` is removed."""
    world = cal_world()
    minuted = {
        **world.stores.meetings.get(ORG, "mt_priya1").record,
        "status": "minuted",
        "transcript": {"artifact_id": "art_transcript1", "version": 1},
        "minutes": {"artifact_id": "art_minutes1", "version": 1},
        "minutes_confirmed_by": stamp(PRIYA),
    }
    world.replace_record("meetings", minuted)
    item = work_item("wi_released", SAM, "Released action item")
    item.update(
        created_by=maker("A_notes", "tilo"),
        assigned_by=stamp(PRIYA),
        confirmed_by=stamp(PRIYA, "2026-10-02T09:00:00.000Z"),
        source={"kind": "meeting", "ref": "mt_priya1#ai1", "evidence": ["u0004"]},
        history=[hist("A_notes", "created", "proposed"), hist(PRIYA, "confirmed", "open", "2026-10-02T09:00:00.000Z")],
    )
    world.stores.work_items.create(item)
    rec = entry("ce_rel1", "Follow-up slot", ist(17), ist(17, 30), tilo_ref="mt_priya1#ai1")
    world.stores.calendar.create(rec)
    world.reset_log()
    return world, rec, item


def cal_row(rec: Mapping[str, Any]) -> dict[str, Any]:
    """The plate row the PE-26 builder makes for an entry (group `soon`, `at` = the start)."""
    return plate_row(
        "calendar_entry", rec["id"], "calendar", "soon", rec["title"], at=rec["start"], flagged=bool(rec["flagged"])
    )


def cal_plate(recs: Iterable[Mapping[str, Any]], *, with_s1: bool = False) -> dict[str, Any]:
    """Sam's plate holding a calendar row per record (the real builder lists accepted and proposed own entries that
    start today; a buggy builder may list more, and the tests pass such records on purpose). `with_s1` adds the
    other rows of plate S1 (every non-calendar row)."""
    rows = [cal_row(r) for r in recs]
    if with_s1:
        rows += [r for r in s1_rows() if r["ref"]["kind"] != "calendar_entry"]
    return make_plate(SAM, rows)


def stored(world: World, cid: str) -> dict[str, Any]:
    got = world.stores.calendar.get(ORG, cid)
    assert got is not None, cid
    return dict(got.record)


# ---------------------------------------------------------------------------------------------
# The oracles (API_FR_CAL_07a.md sections 2 and 3)
# ---------------------------------------------------------------------------------------------
def expected_today(world: World, plate: Mapping[str, Any], tz: str = IST) -> dict[str, Any]:
    """The `calendar_today` answer: the plate's calendar rows whose stored entry is the signed-in person's own and
    `accepted`, in plate order; a navigate to the entry when exactly one."""
    intent = INTENTS[TODAY_INTENT]
    kept = []
    for row in plate["rows"]:
        if row["reason"] != "calendar":
            continue
        got = world.stores.calendar.get(ORG, row["ref"]["id"])
        if got is not None and got.record["owner"] == SAM and got.record["state"] == "accepted":
            kept.append((row, got.record))
    if not kept:
        return {"outcome": "declined", "lines": [(intent["empty"], None)], "ui_action": None, "decline": "empty"}
    lines: list[tuple[str, tuple[str, str] | None]] = [(intent["header"], None)]
    for row, rec in kept:
        text = fill(ANSWER["lines"]["calendar"], label=row["title"], time=clock(row["at"], tz))
        if rec["flagged"]:
            text += ANSWER["flagged_suffix"]
        lines.append((text, ("calendar_entry", rec["id"])))
    ui = None
    if len(kept) == 1:
        ui = {"kind": "navigate", "route": "calendar", "target": {"kind": "calendar_entry", "id": kept[0][1]["id"]}}
    return {"outcome": "answered", "lines": lines, "ui_action": ui, "decline": None}


def navigate_entry(cid: str) -> dict[str, Any]:
    return {"kind": "navigate", "route": "calendar", "target": {"kind": "calendar_entry", "id": cid}}


def expected_prepare(
    rec: Mapping[str, Any],
    *,
    meeting: Mapping[str, Any] | None = None,
    item: Mapping[str, Any] | None = None,
    tz: str = IST,
) -> dict[str, Any]:
    """The `calendar_prepare` answer for an entry. `meeting` and `item` are the linked records the person may read
    (the test says which, by building the world so); nothing else is ever listed."""
    start = clock(rec["start"], tz)
    if rec["end"] is None:
        first = fill(TEXT["entry_open"], label=rec["title"], start=start)
    else:
        first = fill(TEXT["entry"], label=rec["title"], start=start, end=clock(rec["end"], tz))
    if rec["flagged"]:
        first += ANSWER["flagged_suffix"]
    src = ("calendar_entry", rec["id"])
    lines: list[tuple[str, tuple[str, str] | None]] = [(TEXT["header"], None), (first, src)]
    if rec["attendee_count"] > 0:
        lines.append((fill(TEXT["attendees"], n=str(rec["attendee_count"])), src))
    if meeting is not None:
        lines.append((fill(TEXT["meeting"], label=meeting["title"]), ("meeting", meeting["id"])))
    if item is not None:
        text = fill(TEXT["item"], label=item["title"])
        if item["due"] is not None:
            text += fill(ANSWER["due_suffix"], due=item["due"])
        if item["flagged"]:
            text += ANSWER["flagged_suffix"]
        lines.append((text, ("work_item", item["id"])))
    if meeting is None and item is None:
        lines.append((TEXT["nothing"], None))
    return {
        "outcome": "answered",
        "lines": lines,
        "ui_action": navigate_entry(rec["id"]),
        "decline": None,
    }


def which_entry() -> dict[str, Any]:
    return {"outcome": "declined", "lines": [(TEXT["which_entry"], None)], "ui_action": None, "decline": "which_entry"}


def shape_of(answer: Any) -> dict[str, Any]:
    """A `core.Answer` as the dict the oracles return."""
    return {
        "outcome": answer.outcome,
        "lines": [(ln.text, None if ln.source is None else (ln.source.kind, ln.source.id)) for ln in answer.lines],
        "ui_action": answer.ui_action,
        "decline": answer.decline,
    }


def shape_of_body(body: Mapping[str, Any], decline: str | None = None) -> dict[str, Any]:
    """A 200 response body as the dict the oracles return (the body has no `decline`; pass the expected one)."""
    return {
        "outcome": body["outcome"],
        "lines": [
            (ln["text"], None if ln["source"] is None else (ln["source"]["kind"], ln["source"]["id"]))
            for ln in body["lines"]
        ],
        "ui_action": body["ui_action"],
        "decline": decline,
    }


def sources_of_lines(lines: Sequence[tuple[str, tuple[str, str] | None]]) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    for _, src in lines:
        if src is not None and src not in seen:
            seen.append(src)
    return seen
