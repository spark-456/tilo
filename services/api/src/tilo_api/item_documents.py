"""tilo_api.item_documents: the run path's producer of the L5 item documents (ADR-0035 L6b, FR-CON-02, BQ-ADR35L6-1).

`build_document` turns (an action, the declared fields, the unit's body artifact) into the UTF-8 JSON document
tilo-connectors reads (BQ-ADR35L5-1): `email` {subject, body_text, in_reply_to?, references?}, `file` {name, mime_type,
content_b64, origin?}, `calendar_event` {title, start, end, time_zone}. It is deterministic and generic over the action
type: a field is declared (by the action resolver, or supplied by the person) and is never read out of prose, so a
missing subject, name or time is `Needs`, never a guess. Header-injection characters, an oversize document and a guest
on the no-guest `create_event` are `DocumentRefused` with a plain reason. Nothing here imports tilo_connectors.
"""

from __future__ import annotations

import base64
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

KIND_OF = {  # action type -> the kind of document its connector parses
    "create_draft": "email", "send_email": "email", "save_file": "file", "save_as_google_file": "file",
    "create_event": "calendar_event", "create_event_with_guests": "calendar_event", "update_event": "calendar_event",
}  # fmt: skip
NO_RECIPIENT_ACTIONS = frozenset(
    {"save_file", "save_as_google_file", "create_event", "update_event"}
)  # they reach no one but the owner
ORDER = ("email", "file", "calendar_event")  # a stable index per kind (an artifact key)
MAX_DOCUMENT = 32_768  # decoded bytes of one item: the execute contract's content_b64 maxLength (43692) is its base64
MAX_TEXT = 150  # a subject, name or title: short enough for the gate card to show whole
_REQUIRED = {"email": ("subject",), "file": ("name",), "calendar_event": ("title", "start", "end", "time_zone")}
_HEADERS = ("in_reply_to", "references")
_ZONE = re.compile(r"[A-Za-z_]+(?:/[A-Za-z0-9_+-]+){0,2}")
_MSG_ID = re.compile(r"<[^<>\s@]+@[^<>\s@]+>")
_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")


NO_GUESTS = "an event with guests needs the guest version, which a person must approve"  # LC-09


class DocumentRefused(Exception):
    """The document cannot be built from what was declared; `reason` is plain words for the person."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Needs:
    """Required fields nobody declared yet, in the document's order."""

    fields: tuple[str, ...]


def kind_of(action: str) -> str | None:
    return KIND_OF.get(action)


def required_fields(action: str) -> tuple[str, ...]:
    return _REQUIRED.get(KIND_OF.get(action, ""), ())


def _plain(field: str, value: Any, *, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DocumentRefused(f"the {field} must be some text")
    if any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Zl", "Zp") for c in value):
        raise DocumentRefused(f"the {field} has line breaks or hidden characters")
    if len(value) > limit:
        raise DocumentRefused(f"the {field} is longer than {limit} characters")
    return value.strip()


def _moment(field: str, value: Any) -> str:
    text = _plain(field, value, limit=40)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise DocumentRefused(f"the {field} is not a date and time like 2026-10-12T09:00:00Z") from None
    return text


def check_fields(action: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """The declared fields that belong to this action's document, each validated; DocumentRefused on a bad one.
    An absent or blank required field is simply not in the result (`build_document` then says what is needed)."""
    kind, out = KIND_OF.get(action), {}
    if kind is None:
        raise DocumentRefused("this action has no document to build")
    if action in ("create_event", "update_event") and (fields.get("attendees") or fields.get("guests")):
        raise DocumentRefused(NO_GUESTS)
    for name in (*_REQUIRED[kind], *({"email": _HEADERS, "file": ("mime_type",)}.get(kind, ()))):
        value = fields.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if name in ("start", "end"):
            out[name] = _moment(name, value)
        elif name == "time_zone":
            out[name] = _plain(name, value, limit=64)
            if not _ZONE.fullmatch(out[name]):
                raise DocumentRefused("the time_zone is not a time zone name like Asia/Kolkata")
        elif name == "mime_type":
            out[name] = _plain(name, value, limit=100)
            if not _MIME.fullmatch(out[name]):
                raise DocumentRefused("the mime_type is not a file type like text/plain")
        elif name == "in_reply_to":
            out[name] = _plain(name, value, limit=998)
            if not _MSG_ID.fullmatch(out[name]):
                raise DocumentRefused("the in_reply_to is not one message id like <id@example.org>")
        elif name == "references":
            out[name] = _plain(name, value, limit=2000)
        elif name == "name":
            out[name] = _plain(name, value)
            if "/" in out[name] or "\\" in out[name]:
                raise DocumentRefused("the name has a slash")
        else:
            out[name] = _plain(name, value, limit=998 if name in _HEADERS else MAX_TEXT)
    if kind == "calendar_event" and "reminders" in fields:
        reminders = fields["reminders"]
        if (
            not isinstance(reminders, list)
            or len(reminders) > 5
            or any(
                not isinstance(row, dict)
                or set(row) != {"method", "minutes"}
                or row["method"] not in ("popup", "email")
                or type(row["minutes"]) is not int
                or not 0 <= row["minutes"] <= 40320
                for row in reminders
            )
        ):
            raise DocumentRefused("reminders need at most five popup or email entries from 0 to 40320 minutes")
        out["reminders"] = [{"method": row["method"], "minutes": row["minutes"]} for row in reminders]
    return out


def reminder_fields(fields: Mapping[str, Any], *, email: bool = False) -> dict[str, Any]:
    """A Director reminder unit is an ordinary own-calendar create, 15 minutes at the supplied start."""
    out = dict(fields)
    out["reminders"] = [{"method": "popup", "minutes": 0}]
    if email:
        out["reminders"].append({"method": "email", "minutes": 0})
    if start := out.get("start"):
        try:
            moment = datetime.fromisoformat(_moment("start", start).replace("Z", "+00:00"))
            end = (moment + timedelta(minutes=15)).isoformat()
        except OverflowError:
            raise DocumentRefused("the reminder time is out of range") from None
        out["end"] = end.replace("+00:00", "Z") if start.endswith("Z") else end
    return out


def build_document(
    action: str,
    fields: Mapping[str, Any],
    *,
    body: bytes,
    media_type: str,
    origin: Mapping[str, Any] | None = None,
    threaded: bool = False,
) -> bytes | Needs:
    """The document's bytes, or `Needs` when a required field is missing. `body` is the unit's artifact as stored
    (the email text, the file's content); `media_type` is the store's own record of it, never a model's word."""
    kind, declared = KIND_OF.get(action), check_fields(action, fields)
    if kind is None:
        raise DocumentRefused("this action has no document to build")
    if missing := tuple(name for name in _REQUIRED[kind] if name not in declared):
        return Needs(missing)
    if (
        kind == "email" and threaded and "in_reply_to" not in declared
    ):  # connectors would take the subject from the thread
        raise DocumentRefused("a reply must name the message it answers, so the subject sent is the one approved")
    document: dict[str, Any] = {"kind": kind, **{name: declared[name] for name in _REQUIRED[kind]}}
    if kind == "calendar_event" and "reminders" in declared:
        document["reminders"] = declared["reminders"]
    if kind == "email":
        try:
            document["body_text"] = bytes(body).decode("utf-8")
        except UnicodeDecodeError:
            raise DocumentRefused("the email text is not text") from None
        document |= {name: declared[name] for name in _HEADERS if name in declared}
    elif kind == "file":
        document["mime_type"] = declared.get("mime_type", media_type)
        document["content_b64"] = base64.b64encode(bytes(body)).decode("ascii")
        if origin == {"kind": "render"}:  # only a file tilo-render made, as the store records it (FR-CON-11)
            document["origin"] = {"kind": "render"}
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_DOCUMENT:
        raise DocumentRefused(f"the {kind.replace('_', ' ')} is over the {MAX_DOCUMENT // 1024} KiB limit")
    return raw


def summary(document: bytes) -> str:
    """What the gate card says the document is, from its own fields only (no body text)."""
    parsed = json.loads(document)
    if parsed["kind"] == "email":
        return f"subject: {parsed['subject']}"
    if parsed["kind"] == "file":
        return f"file {parsed['name']} ({parsed['mime_type']})"
    return f"event {parsed['title']}, {parsed['start']} to {parsed['end']} ({parsed['time_zone']})"
