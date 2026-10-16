"""The person's morning brief (ADR-0049, MO-05 to MO-11, contracts/morning_brief.rules.md).

`make_brief` reads the person's own calendar and mail headers through ADR-0048's read route (`MeetingHostRpc.read`,
`read_events` and `search_email`, never a body; each ok read is recorded as WT-05 records it), copies their plate's
deadlines, cleans every copied text like a quote (PE-24), screens the mail headers, makes at most one `assistant` call
that only picks the mail needing a reply and writes cited suggestions and to-dos, and stores the result as a version of
the Desk-world artifact `art_mbrief_<yyyymmdd>`. The model's reply is untrusted data: code keeps only item numbers it
offered and lines that are already clean, and drops anything else (never repairs it). A failed, flagged or missing model
call leaves the mail shown as unread, never as needing a reply (MO-12). Nothing here sends, asks, gates or writes an
outbox entry except the owner-only email copy through the digest path (MO-10, MO-11). Logs carry error types only.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tilo_memory.artifacts import ArtifactStore
from tilo_people.text import clean_line
from tilo_policy.schemas import conforms

from tilo_api import events as event_parts
from tilo_api.brief_store import BriefStore
from tilo_api.people_writes import _unhide
from tilo_api.workspace_tools import CONNECTOR_OF, SUMMARIES

logger = logging.getLogger("tilo_api.morning_brief")
SCHEMA = "morning_brief.schema.json"
ON_DEMAND_MAX = 3
MAX_MEETINGS, MAX_MAIL, MAX_DEADLINES, DEADLINE_DAYS = 20, 10, 20, 2
MAIL_QUERY = "in:inbox newer_than:1d -category:promotions -category:social -in:spam -in:trash"
RAW_CAP = 600  # a copied field is cut to this many characters before any other work (no quadratic cleaning)
_DEADLINE_KINDS = ("work_item", "pinboard_item", "world")
_MASK = re.compile(
    r"[^\s@]+@[^\s@]+|\S+://\S+|www\.\S+|\+?\d[\d ().-]{6,}\d|[A-Za-z0-9-]+\.[A-Za-z]{2,63}(?::[0-9]{1,5})?/\S*"
)  # addresses, links, phone numbers, host/path (PE-24 and the contract's title pattern)


@dataclass
class Ctx:
    """Everything one brief needs, resolved by the caller from the app's seams (the route or the Scheduler's sweep)."""

    org: str
    user: str
    demo: bool
    now: str
    zone: str
    trigger: str  # schedule | on_demand
    artifacts: ArtifactStore
    events: Any
    desks: Any
    redact: Callable[[str], str]
    plate: Callable[[], dict[str, Any] | None]
    rpc: Callable[[], Any]
    briefs: BriefStore
    screen: Callable[[str], bool] | None = None  # True when the text is flagged; raises when it cannot tell
    ask: Callable[[str, str], str] | None = None  # one metered `assistant` JSON call: (system, user turn) -> reply text
    mailer: Any = None
    email_copy: bool = False


DOMAIN = re.compile(r"(?<![\w@.-])(?:[^\W_](?:[\w-]{0,61}[^\W_])?[.。])+[^\W\d_]{2,63}(?![\w-])")
# a bare domain name ("evil-pay.com", "bücher-pay.de"; run it on NFKC text so fullwidth letters and dots count): a
# title may carry one, but a line a model wrote, or the email copy, may not


def local_date(now: str, zone: str) -> str:
    return datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(ZoneInfo(zone)).date().isoformat()


def artifact_id(day: str) -> str:
    return "art_mbrief_" + day.replace("-", "")


# -- cleaning (MO-06) ------------------------------------------------------------------------------------------------


def clean(ctx: Ctx, value: Any, cap: int) -> str:
    """PE-24: controls, format and separator characters out, the secret redactor, addresses, phone numbers and links
    replaced by `[removed]`, whitespace collapsed, cut at the cap on a word boundary. A raw prefix first."""
    text = _unhide(clean_line(str(value)[:RAW_CAP]))
    text = " ".join(_MASK.sub("[removed]", ctx.redact(text)).split())
    if len(text) > cap:
        text = text[: cap + 1].rsplit(" ", 1)[0] if " " in text[: cap + 1] else text[:cap]
    return text.strip()


def _sender_name(ctx: Ctx, sender: Any) -> str | None:
    """The display name only, never the address (no `parseaddr`: it recurses on crafted input)."""
    raw = str(sender)[:200]
    if "<" not in raw and "@" in raw:
        return None
    name = clean(ctx, raw.rsplit("<", 1)[0].strip().strip("\"'"), 80)
    return None if not name or "@" in name or name == "[removed]" else name


# -- the reads (MO-05) -----------------------------------------------------------------------------------------------


def _record(ctx: Ctx, world: str, tool: str, connected_at: str) -> None:
    """WT-05: one `data.transfer` (in) for an ok read, fixed text only, in the person's own Desk world."""
    connector = CONNECTOR_OF[tool]
    ctx.events.append(
        world,
        {
            "id": event_parts.new_part_id(), "type": "data.transfer", "actor": ctx.user, "target": world,
            "summary": SUMMARIES[connector], "vis": [], "severity": "info",
            "authz": {"by": "person", "ref": ctx.user, "at": connected_at},
            "data": {"connector": connector, "action_type": tool, "direction": "in", "artifact": None,
                     "outbox_id": None, "risk_tier": "T1"},
        },
    )  # fmt: skip


def _read(ctx: Ctx, world: str, tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """("ok", result), ("not_connected", None) or ("unavailable", None). A demo session reads no account, and a read
    that cannot be recorded is not used."""
    if ctx.demo:
        return "not_connected", None
    try:
        answer = ctx.rpc().read(ctx.user, tool, args)
        if answer.outcome == "ok" and answer.result is not None and answer.connected_at is not None:
            result: dict[str, Any] = answer.result.model_dump(mode="json")
            _record(ctx, world, tool, answer.connected_at)
            return "ok", result
        return ("not_connected" if answer.outcome in ("not_connected", "missing_scope") else "unavailable"), None
    except Exception as exc:  # noqa: BLE001 - a fixed kind; no body, id or text is logged
        logger.warning("a brief read failed (%s)", type(exc).__name__)
        return "unavailable", None


def _valid(kind: str, item: dict[str, Any]) -> bool:
    return conforms(f"{SCHEMA}#/$defs/{kind}", item)


def read_meetings(ctx: Ctx, world: str, day: str) -> tuple[str, list[dict[str, Any]]]:
    tz = ZoneInfo(ctx.zone)
    first = date.fromisoformat(day)
    start, end = (datetime.combine(d, time(0), tz).isoformat() for d in (first, first + timedelta(days=1)))
    status, result = _read(ctx, world, "read_events", {"start": start, "end": end})
    if status != "ok" or result is None:
        return status, []
    meetings = []
    for event in result["events"]:
        item = {
            "title": clean(ctx, event["title"], 140) or "Untitled event",
            "start": event["start"], "end": event["end"], "all_day": event["all_day"],
            "attendee_count": event["attendee_count"], "source": {"kind": "calendar_event", "id": event["id"]},
        }  # fmt: skip
        if _valid("meeting", item):
            meetings.append(item)
    return "ok", sorted(meetings, key=lambda m: (m["start"], m["source"]["id"]))[:MAX_MEETINGS]


def read_mail(ctx: Ctx, world: str) -> tuple[str, list[dict[str, Any]]]:
    """Each row is `{"mail": <schema mail>, "unread": bool}`: headers only, the snippet is never read. A flagged
    message is left out; a screen that cannot tell makes the whole section unavailable (fail closed)."""
    status, result = _read(ctx, world, "search_email", {"query": MAIL_QUERY, "max_results": MAX_MAIL})
    if status != "ok" or result is None:
        return status, []
    since = (datetime.fromisoformat(ctx.now.replace("Z", "+00:00")) - timedelta(hours=24)).isoformat()
    rows = []
    for message in result["messages"]:
        when = message["date"]
        if when is not None and datetime.fromisoformat(when.replace("Z", "+00:00")).isoformat() < since:
            continue
        subject = clean(ctx, message["subject"], 140) or None
        item = {
            "from_name": _sender_name(ctx, message["sender"]), "subject": subject, "received_at": when,
            "source": {"kind": "mail", "id": message["id"]},
        }  # fmt: skip
        if _valid("mail", item):
            rows.append({"mail": item, "unread": message["unread"] is True})
    if rows:
        try:
            rows = _unflagged(ctx, rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("mail headers were not screened (%s)", type(exc).__name__)
            return "unavailable", []
    return "ok", rows


def _line_of(row: dict[str, Any]) -> str:
    return f"{row['mail']['from_name'] or ''}: {row['mail']['subject'] or ''}"


def _unflagged(ctx: Ctx, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MO-06: the headers of one brief are screened once together; only when that is flagged is each one checked."""
    if ctx.screen is None:
        raise RuntimeError("no screen")
    if not ctx.screen("\n".join(_line_of(r) for r in rows)):
        return rows
    return [r for r in rows if not ctx.screen(_line_of(r))]


def read_deadlines(ctx: Ctx, day: str) -> tuple[str, list[dict[str, Any]]]:
    try:
        plate = ctx.plate()
    except Exception as exc:  # noqa: BLE001
        logger.warning("the plate could not be read for a brief (%s)", type(exc).__name__)
        return "unavailable", []
    if plate is None:
        return "unavailable", []
    limit = (date.fromisoformat(day) + timedelta(days=DEADLINE_DAYS)).isoformat()
    rows = []
    for row in plate["rows"]:
        ref, due = row["ref"], row["due"]
        if ref["kind"] not in _DEADLINE_KINDS or due is None or due > limit or row["flagged"] or not row["title"]:
            continue
        item = {
            "title": clean(ctx, row["title"], 140), "due": due, "overdue": due < day,
            "source": {"kind": ref["kind"], "id": ref["id"]},
        }  # fmt: skip
        if item["title"] and _valid("deadline", item):
            rows.append(item)
    return "ok", sorted(rows, key=lambda d: (d["due"], d["source"]["id"]))[:MAX_DEADLINES]
