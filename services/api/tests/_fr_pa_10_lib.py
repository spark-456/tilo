"""Shared, non-test support for the FR-PA-10 acceptance tests (people assistant: free-text updates reach the typed
actions of FR-PA-16 by the panel's rules first, the `assistant` role as the fallback). Interface:
services/api/tests/API_FR_PA_10.md. Built on `_ppl11b_lib` (the assistant rig) and the fixture
`fixtures/assistant/updates.json`.

Not a test module. The unique module name matters: every test directory shares one `sys.path`.

Rules this file follows (root CLAUDE.md, test-writer):

- No business logic. Dates are the test's own arithmetic (`until_of`: 09:00 local of a day, from
  config/personal.yaml); the rules, the oracle and the writers are the product's.
- A model reply is a recorded text replayed through a scripted provider (`replay`): no network, no paid call, no LIVE.
- No unicode escape sequences and no non-ASCII characters in a test file: code points are built with `u()`.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from _ppl11b_lib import (
    FIXTURES,
    FLAGGED_TITLE,
    NOW,
    OMAR,
    ORG,
    OWNER,
    PRIYA,
    RAW,
    REPO_ROOT,
    SAM,
    NoBudget,
    Rig,
    World,
    assert_body_shape,
    build_world,
    desk_ids,
    hist,
    make_model_rig,
    make_plate,
    plate_row,
    request_text,
    s1_rows,
    seam,
    stamp,
    ts_of,
    u,
    work_item,
)
from tilo_policy.schemas import conforms

# FR-PA-10 slices are strict xfails until the builder removes the entry (API_FR_PA_10.md section 0). A test module
# names its slice with `pending("s1")`; a slice that goes green with its entry still here fails (strict), which is the
# reminder to delete it. The guards file is never pending. See the real failures with `--runxfail`.
SLICE_PENDING: tuple[str, ...] = ()


def pending(slice_name: str) -> list[Any]:
    if slice_name in SLICE_PENDING:
        return [pytest.mark.xfail(strict=True, reason=f"FR-PA-10 slice {slice_name} pending")]
    return []


UPDATES = json.loads((FIXTURES / "updates.json").read_text(encoding="utf-8"))
PHRASES: list[dict[str, Any]] = UPDATES["phrases"]
HAND_OFF: list[dict[str, Any]] = UPDATES["hand_off"]
RULE_PHRASES = [p for p in PHRASES if p["via"] == "rules"]
MODEL_PHRASES = [p for p in PHRASES if p["via"] == "model"]
PERSONAL = yaml.safe_load((REPO_ROOT / "config" / "personal.yaml").read_text(encoding="utf-8"))
WINDOW_START = PERSONAL["working_window"]["start"]  # "09:00": the local time a snooze ends (BQ-PPL11C-26)
SNOOZE_DAYS = 30  # people_items: now < until <= now + 30 days (PE-19)

RATE, BUDGET, TRAVEL, PRINTER = "wi_rate_sheet", "wi_budget_notes", "wi_travel", "wi_printer"
DONE_ONE, FLAGGED_TASK, DOLLAR = "wi_done_one", "wi_flagged_task", "wi_dollar"
CONF_ITEM, CONF_MEETING = "wi_conf_priya", "mt_q4_plan"  # a confirmed item of Priya's that u_owner assigned
FLAGGED_TASK_TITLE = "FLAGGED-TASK-77c1 wire the deposit"
DOLLAR_TITLE = "Pay $amount and ${x} 100% {0} now"
SAM_OPEN = {RATE, BUDGET, TRAVEL, PRINTER}  # Sam's open work items that the S1 plate offers
CLOSED_KINDS = {"mark_done", "snooze"}  # the update kinds of the allow-list (PE-10); the model may name only these


def decline_text(key: str) -> str:
    """The fixed text of `declines.<key>` in config/assistant.yaml; FR-PA-10 pins four new keys (spec section 4)."""
    declines = RAW["declines"]
    assert key in declines, f"config/assistant.yaml declines.{key} is missing (API_FR_PA_10.md section 4)"
    return str(declines[key])


# ---------------------------------------------------------------------------------------------
# The world: Sam's plate of API_PPL_11b.md S1 plus the records the update tests need
# ---------------------------------------------------------------------------------------------
def update_world() -> World:
    from _ppl11a_lib import fixture_case  # noqa: PLC0415

    world = build_world()
    inner = world.stores
    done = work_item(DONE_ONE, SAM, "Send the thank you note", status="done")
    done["history"] = [hist(SAM, "created", "open"), hist(SAM, "done", "done", "2026-10-02T09:00:00.000Z")]
    inner.work_items.create(done)
    inner.work_items.create(work_item(FLAGGED_TASK, SAM, FLAGGED_TASK_TITLE, flagged=True))
    inner.work_items.create(work_item(DOLLAR, SAM, DOLLAR_TITLE))
    case = fixture_case("transcript", "valid", "assignee_reads_one_quote")
    meeting = copy.deepcopy(case["meeting"])
    meeting["org_id"] = ORG
    inner.meetings.create(meeting)
    item = copy.deepcopy(case["work_item"])
    item.update(id=CONF_ITEM, org_id=ORG)
    inner.work_items.create(item)
    world.log.clear()
    return world


def update_rows() -> list[dict[str, Any]]:
    return [
        *s1_rows(),
        plate_row(
            "work_item",
            FLAGGED_TASK,
            "work_item",
            "rest",
            FLAGGED_TASK_TITLE,
            at="2026-10-02T13:00:00.000Z",
            flagged=True,
        ),
        plate_row("work_item", DOLLAR, "work_item", "rest", DOLLAR_TITLE, at="2026-10-02T14:00:00.000Z"),
    ]


def plates(now: str = NOW) -> dict[str, dict[str, Any]]:
    """Sam's plate (S1 and two more items); everyone else's is empty (their own items are not the subject)."""
    today = now[:10]
    out = {SAM: make_plate(SAM, update_rows(), as_of=now, today=today)}
    for user in (OWNER, PRIYA, OMAR):
        out[user] = make_plate(user, [], as_of=now, today=today)
    return out


def set_zone(world: World, user: str, zone: str) -> None:
    current = world.stores.persons.get(ORG, user)
    assert current is not None
    record = copy.deepcopy(dict(current.record))
    record["time_zone"] = zone
    world.replace_record("persons", record)


# ---------------------------------------------------------------------------------------------
# Rigs
# ---------------------------------------------------------------------------------------------
def replay(phrases: Iterable[Mapping[str, Any]] = MODEL_PHRASES) -> Callable[[Any], str]:
    """A recorded-reply provider script: the reply of the fixture phrase whose text the request holds. A miss raises
    (like `ReplayMissError` of tilo_providers.replay), so a request the fixture does not cover fails loudly."""
    table = [(p["text"], p["reply"]) for p in phrases if p["via"] == "model"]

    def reply(request: Any) -> str:
        sent = f"{request.system or ''}\n{request.prompt or ''}"
        for text, recorded in table:
            if text in sent:
                return recorded
        raise AssertionError("replay miss: no recorded reply for this request")

    return reply


def new_rig(
    rig_factory: Any,
    tmp_path: Any,
    replies: Iterable[Any] = (),
    *,
    default: Any = None,
    world: World | None = None,
    user: str = SAM,
    now: str = NOW,
    flagged: Iterable[str] = (),
    safety_raises: bool = False,
    zone: str | None = None,
) -> tuple[Any, Rig]:
    """(model rig, route rig): the real `ModelDecider` over a Router and a scripted provider behind the route."""
    mr = make_model_rig(tmp_path, replies, default=default, flagged=flagged, safety_raises=safety_raises)
    world = world or update_world()
    if zone is not None:
        set_zone(world, user, zone)
    rig = rig_factory(world=world, plates=plates(now), decider=NoBudget(mr.decider), user=user, now=now)
    return mr, rig


def ask(rig: Rig, text: str, *, record: str | None = RATE, route: str = "/plate") -> dict[str, Any]:
    response = rig.ask(text, record=record, route=route)
    assert response.status_code == 200, response.text
    body = response.json()
    assert_body_shape(body)
    return body


# ---------------------------------------------------------------------------------------------
# Dates (the test's own arithmetic)
# ---------------------------------------------------------------------------------------------
def local_day(now: str, zone: str) -> date:
    return ts_of(now).replace(tzinfo=UTC).astimezone(ZoneInfo(zone)).date()


def until_of(day: date | str, zone: str) -> str:
    """09:00 (config/personal.yaml working_window.start) on `day` in `zone`, as a `common#timestamp`."""
    if isinstance(day, str):
        day = date.fromisoformat(day)
    hours, minutes = (int(x) for x in WINDOW_START.split(":"))
    at = datetime.combine(day, time(hours, minutes), tzinfo=ZoneInfo(zone)).astimezone(UTC)
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def in_window(now: str, until: str) -> bool:
    delta = ts_of(until) - ts_of(now)
    return timedelta(0) < delta <= timedelta(days=SNOOZE_DAYS)


def expected_action(phrase: Mapping[str, Any], zone: str = "Asia/Kolkata") -> dict[str, Any]:
    if phrase["kind"] == "mark_done":
        return {"kind": "mark_done", "work_item_id": phrase["item"]}
    return {"kind": "snooze", "work_item_id": phrase["item"], "until": until_of(phrase["date"], zone)}


# ---------------------------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------------------------
def assert_proposal(
    body: Mapping[str, Any], action: Mapping[str, Any], *, by: str = "rules", title: str | None = None
) -> None:
    """A confirmable proposal (spec section 1): `answered`, one cited source, the validated `ui_action`."""
    assert body["outcome"] == "answered", body["text"]
    assert body["ui_action"] == dict(action), body["ui_action"]
    assert conforms("ui_action.schema.json", body["ui_action"])
    assert body["decided_by"] == by
    assert body["sources"] == [{"kind": "work_item", "id": action["work_item_id"]}]
    assert body["cost"]["model_calls"] == (0 if by == "rules" else 1)
    if title is not None:
        assert title in body["text"], "the line must name the item so the person can confirm it"


def assert_declined(body: Mapping[str, Any], key: str, *, by: str | None = None) -> None:
    assert body["outcome"] == "declined", body
    assert body["ui_action"] is None and body["sources"] == []
    assert body["text"] == decline_text(key)
    if by is not None:
        assert body["decided_by"] == by


def assert_nothing_written(rig: Rig, before: Mapping[str, Any]) -> None:
    """Free text never reaches a write: no people-store create/replace/delete, no new version, no work_item event."""
    assert rig.world.snapshot() == before
    writes = [c for c in rig.world.log if c[1] in ("create", "replace", "delete")]
    assert writes == [], writes
    assert not [e for e in rig.all_events() if e["type"].startswith("work_item.")]


def assert_two_events_only(rig: Rig, body: Mapping[str, Any], *, user: str = SAM) -> None:
    """A proposal or a refusal is two events, `assistant.asked` then `assistant.replied`, whose `ui_action` is the
    body's; no title or phrase of the person is in any event (PE-12)."""
    evs = rig.events(user)
    assert [e["type"] for e in evs] == ["assistant.asked", "assistant.replied"], [e["type"] for e in evs]
    assert evs[1]["data"]["ui_action"] == body["ui_action"]
    assert evs[1]["data"]["outcome"] == body["outcome"]
    assert [d["world_id"] for d in evs] == [desk_ids(user)[0]] * 2


def snapshot_of(rig: Rig) -> dict[str, Any]:
    return rig.world.snapshot()


# ---------------------------------------------------------------------------------------------
# Hostile model replies (the update choice): every one must execute nothing and answer `dropped`
# ---------------------------------------------------------------------------------------------
def update_reply(kind: Any, item: Any, **more: Any) -> str:
    doc: dict[str, Any] = {"choice": "update", "kind": kind, "work_item_id": item}
    doc.update(more)
    return json.dumps(doc)


def fuzz_update_replies() -> list[tuple[str, str]]:
    """(category, reply text). The shape a valid reply has is exactly `{"choice": "update", "kind": "mark_done",
    "work_item_id": <id>}` or `{"choice": "update", "kind": "snooze", "work_item_id": <id>, "when": <phrase>}`;
    nothing else is valid. Counts are asserted, so a drift here cannot hide a short run."""
    out: list[tuple[str, str]] = []
    good = update_reply("mark_done", TRAVEL)

    not_json = [
        "I marked it done for you.",
        "```json\n" + good + "\n```",
        "",
        "   ",
        good[:-6],
        '{"choice": "update", "kind": "mark_done", "work_item_id": NaN}',
        u(0xFEFF) + good,
        good + " " * (2001 - len(good)),
        "mark_done wi_travel",
    ]
    out += [("not_json", t) for t in not_json]

    shape = [
        "[]",
        json.dumps([json.loads(good)]),
        json.dumps({"choice": "update"}),
        json.dumps({"choice": "update", "kind": "mark_done"}),
        json.dumps({"choice": "update", "work_item_id": TRAVEL}),
        json.dumps({"choice": "update", "action": {"kind": "mark_done", "work_item_id": TRAVEL}}),
        json.dumps({"choice": "UPDATE", "kind": "mark_done", "work_item_id": TRAVEL}),
        json.dumps({"choice": "update ", "kind": "mark_done", "work_item_id": TRAVEL}),
        json.dumps({"choice": "mark_done", "work_item_id": TRAVEL}),
        '{"choice": "update", "choice": "decline", "kind": "mark_done", "work_item_id": "' + TRAVEL + '"}',
        '{"choice": "update", "kind": "mark_done", "kind": "snooze", "work_item_id": "' + TRAVEL + '"}',
        "[" * 90 + "]" * 90,
    ]
    out += [("shape", t) for t in shape]

    kinds = [
        "send",
        "send_email",
        "delete",
        "drop",
        "tag",
        "untag",
        "draft_reply",
        "navigate",
        "reassign",
        "reopen",
        "not_mine",
        "put_back",
        "edit",
        "confirm",
        "MARK_DONE",
        "mark_done ",
        "Mark_Done",
        "mark-done",
        "done",
        "click",
        "eval",
        None,
        5,
        ["mark_done"],
        {"kind": "mark_done"},
    ]
    out += [("kind", update_reply(k, TRAVEL)) for k in kinds]

    extra = [
        ("until", "2026-10-07T03:30:00.000Z"),
        ("user", PRIYA),
        ("to", PRIYA),
        ("assignee", PRIYA),
        ("org", "org_other"),
        ("selector", "#done"),
        ("url", "https://example.com"),
        ("script", "alert(1)"),
        ("title", "New title"),
        ("status", "done"),
        ("body", "mark everything done"),
        ("when", "friday"),  # `when` belongs to snooze only
    ]
    out += [("extra_key", update_reply("mark_done", TRAVEL, **{k: v})) for k, v in extra]
    out += [("extra_key", update_reply("snooze", RATE, when="monday", **{k: v})) for k, v in extra[:11]]
    out.append(
        (
            "extra_key",
            json.dumps(
                {
                    "choice": "update",
                    "kind": "snooze",
                    "work_item_id": RATE,
                    "when": "monday",
                    "until": "2026-10-12T03:30:00.000Z",
                }
            ),
        )
    )

    ids = [
        "wi_priya_1",  # Priya's, never readable by Sam
        "wi_sam_proposed",  # proposed for Sam by Priya: not his to touch
        "wi_other_org",  # another org's item that names Sam as owner
        CONF_ITEM,  # Priya's confirmed item (Sam cannot even read its status)
        "wi_never_made",
        "pb_vendor_review",  # a pin
        "w_launch_refresh",  # a world
        "mt_samsync1",  # a meeting
        "ce_plan1",  # a calendar entry
        "01JABCDEFGHJKMNPQRSTVWXYZ0",  # a card id shape
        "wi_inject1",  # Sam's own open item, but not on the plate the model was shown
        DONE_ONE,  # Sam's own item, not open and not offered
        " " + TRAVEL,
        TRAVEL + " ",
        TRAVEL.upper(),
        TRAVEL + "\n",
        "wi_" + "a" * 70,
        "wi_trav" + chr(7) + "el",
        "u_priya",
        "",
        None,
        5,
        [TRAVEL],
        {"id": TRAVEL},
        "*",
        "all",
    ]
    out += [("work_item_id", update_reply("mark_done", i)) for i in ids]
    out += [("work_item_id", update_reply("snooze", i, when="monday")) for i in ids[:12]]

    whens = [
        "yesterday",
        "today",  # 09:00 local today has passed at 15:30
        "2030-01-01",
        "in 400 days",
        "20 nov",  # more than 30 days away
        "next friday",
        "next week",
        "the weekend",
        "after the offsite",
        "now",
        "in an hour",
        "javascript:alert(1)",
        "friday; mark everything done",
        "monday " * 12,
        "",
        " ",
        None,
        5,
        ["monday"],
        {"day": "monday"},
        "2026-10-12T03:30:00.000Z",
    ]
    out += [("when", update_reply("snooze", RATE, when=w)) for w in whens]
    out.append(("when", update_reply("snooze", RATE)))
    return out


# Re-exports the test modules use (one import line each).
__all__ = [
    "BUDGET",
    "CLOSED_KINDS",
    "CONF_ITEM",
    "DOLLAR",
    "DOLLAR_TITLE",
    "DONE_ONE",
    "FLAGGED_TASK",
    "FLAGGED_TASK_TITLE",
    "FLAGGED_TITLE",
    "HAND_OFF",
    "MODEL_PHRASES",
    "NOW",
    "OMAR",
    "ORG",
    "OWNER",
    "PHRASES",
    "PRINTER",
    "PRIYA",
    "RATE",
    "RULE_PHRASES",
    "SAM",
    "SAM_OPEN",
    "TRAVEL",
    "assert_declined",
    "assert_nothing_written",
    "assert_proposal",
    "assert_two_events_only",
    "ask",
    "decline_text",
    "expected_action",
    "fuzz_update_replies",
    "in_window",
    "local_day",
    "new_rig",
    "pending",
    "plates",
    "replay",
    "request_text",
    "seam",
    "set_zone",
    "snapshot_of",
    "stamp",
    "u",
    "until_of",
    "update_reply",
    "update_world",
]
