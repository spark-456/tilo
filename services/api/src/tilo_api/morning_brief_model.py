"""The morning brief's one model call (ADR-0049, MO-07, MO-08): the numbered, fenced, untrusted items it is given and
what code keeps of its reply. Only item numbers code offered and lines that are already clean survive; anything else is
dropped, never repaired. A model error, a bad reply, a flagged reply or no room in the allowance never fails the brief:
it leaves `model` failed, flagged or skipped and the mail shown as unread (MO-12)."""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from tilo_people.text import clean_line
from tilo_policy.schemas import conforms
from tilo_providers.prompts import load_prompt, neutralise_marker

from tilo_api import deps, spend
from tilo_api.morning_brief import DOMAIN, MAX_MAIL, RAW_CAP, SCHEMA, Ctx, clean
from tilo_api.people_writes import _unhide

logger = logging.getLogger("tilo_api.morning_brief")
_REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "needs_reply": {"type": "array", "items": {"type": "integer"}},
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "items": {"type": "array", "items": {"type": "integer"}}},
                "required": ["text", "items"],
            },
        },
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "due_text": {"type": ["string", "null"]},
                    "item": {"type": "integer"},
                },
                "required": ["title", "due_text", "item"],
            },
        },
    },
    "required": ["needs_reply", "suggestions", "todos"],
}


# -- the one model call (MO-07, MO-08) -------------------------------------------------------------------------------


@dataclass
class Picks:
    needs_reply: set[str]  # message ids
    suggestions: list[dict[str, Any]]  # {"text", "numbers"}
    todos: list[dict[str, Any]]  # {"title", "due_text", "id"}


def _offered(meetings: list[dict[str, Any]], mail: list[dict[str, Any]], deadlines: list[dict[str, Any]]) -> list[Any]:
    """The numbered items, 1 up: ("meeting" | "mail" | "deadline", item)."""
    return (
        [("meeting", m) for m in meetings] + [("mail", r["mail"]) for r in mail] + [("deadline", d) for d in deadlines]
    )


def _prompt(day: str, items: list[Any]) -> str:
    rows: list[dict[str, Any]] = []
    for n, (kind, item) in enumerate(items, 1):
        if kind == "meeting":
            rows.append(
                {"n": n, "kind": kind, "title": item["title"], "start": item["start"], "guests": item["attendee_count"]}
            )
        elif kind == "mail":
            rows.append(
                {"n": n, "kind": kind, "from": item["from_name"], "subject": item["subject"], "at": item["received_at"]}
            )
        else:
            rows.append({"n": n, "kind": kind, "title": item["title"], "due": item["due"], "overdue": item["overdue"]})
    data = neutralise_marker(json.dumps(rows, ensure_ascii=False), "ITEMS")
    return load_prompt("assistant", "morning_brief_task.md", {"today": day, "items": data})


def _own_line(ctx: Ctx, value: Any, cap: int, kind: str) -> str | None:
    """A model-written line that is already exactly what cleaning leaves, and fits the contract; else None (dropped)."""
    if not isinstance(value, str):
        return None
    if DOMAIN.search(unicodedata.normalize("NFKC", value[:RAW_CAP])):
        return None  # a bare domain is a link a mail client may open: dropped, never repaired
    text = clean(ctx, value, cap)
    same = text == " ".join(_unhide(clean_line(value[:RAW_CAP])).split())
    return text if text and same and len(value) <= RAW_CAP and conforms(f"{SCHEMA}#/$defs/{kind}", text) else None


def _numbers(value: Any, offered: int, *, most: int) -> list[int] | None:
    ok = isinstance(value, list) and 1 <= len(value) <= most
    if not ok or not all(type(n) is int and 1 <= n <= offered for n in value) or len(set(value)) != len(value):
        return None
    return list(value)


def _rows(reply: dict[str, Any], key: str) -> list[Any]:
    found = reply.get(key)
    return found if isinstance(found, list) else []


def _picks(ctx: Ctx, reply: Any, items: list[Any]) -> Picks:
    out = Picks(set(), [], [])
    if not isinstance(reply, dict):
        return out
    kinds = {n: kind for n, (kind, _) in enumerate(items, 1)}
    mail_ids = {n: item["source"]["id"] for n, (kind, item) in enumerate(items, 1) if kind == "mail"}
    for n in _rows(reply, "needs_reply"):
        if type(n) is int and n in mail_ids and len(out.needs_reply) < MAX_MAIL:
            out.needs_reply.add(mail_ids[n])
    for row in _rows(reply, "suggestions")[:20]:
        numbers = _numbers(row.get("items"), len(items), most=5) if isinstance(row, dict) else None
        text = _own_line(ctx, row.get("text"), 240, "line") if numbers else None
        if text and numbers and len(out.suggestions) < 5:
            out.suggestions.append({"text": text, "numbers": numbers})
    for row in _rows(reply, "todos")[:20]:
        item = row.get("item") if isinstance(row, dict) else None
        if type(item) is not int or kinds.get(item) != "mail":
            continue
        title = _own_line(ctx, row.get("title"), 140, "title")
        due = row.get("due_text")
        due_text = None if due is None else _own_line(ctx, due, 60, "due_text")
        if title and (due is None or due_text) and len(out.todos) < 5:
            out.todos.append({"title": title, "due_text": due_text, "id": mail_ids[item]})
    return out


def ask_model(ctx: Ctx, day: str, items: list[Any]) -> tuple[str, Picks | None]:
    """(model state, picks): nothing to read or no room is skipped, an error failed, a flagged reply flagged."""
    if not items or ctx.ask is None:
        return "skipped", None
    try:
        text = ctx.ask(load_prompt("assistant", "morning_brief_system.md"), _prompt(day, items))
        reply = json.loads(text)
        if ctx.screen is None or ctx.screen(text):
            return ("failed" if ctx.screen is None else "flagged"), None
        return "used", _picks(ctx, reply, items)
    except (HTTPException, spend.SpendCapReached, deps.ReplayOnly) as exc:
        # The allowance wraps a router error as 429; its cause tells a call that did not fit from one that failed.
        cause = exc.__context__
        no_room = (
            isinstance(exc, HTTPException)
            and exc.status_code == 429
            and not (cause is not None and not isinstance(cause, (spend.SpendCapReached, deps.ReplayOnly)))
        )
        return ("skipped" if no_room or not isinstance(exc, HTTPException) else "failed"), None
    except Exception as exc:  # noqa: BLE001 - an error, a bad reply or a timeout: the type only
        logger.warning("the brief's model call failed (%s)", type(exc).__name__)
        return "failed", None
