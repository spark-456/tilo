"""The meeting owner's reads and edits (PPL-11c slices 2b and 6; people.rules.md PE-05, PE-07, PE-13, PE-19, PE-22 to
PE-24, FR-MTG-10, BQ-273, services/api/tests/API_PPL_11c.md sections 3 and 6). Owner only; every refusal is the one 404.
`get` and `edit` take the meeting from the store and the five editable fields from the body, nothing else; `minutes`
reads the minutes document through the artifact store in the meeting's own `Scope`; `set_world` stores the id the world
maker answered, once. Deterministic code only: no model, no clock read (`now` is handed in).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from tilo_memory.artifacts import ArtifactStore, Scope
from tilo_people.access import AccessRequest, decide, read
from tilo_people.directory import Directory
from tilo_people.text import clean_line
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.people_quotes import GONE, read_doc
from tilo_api.people_writes import AgendaIn, AttendeeIn, Refusal, Text, WindowIn, Writer, meeting_attendees

_WORLD = re.compile(r"w_[0-9A-Za-z_]{1,48}")


class MeetingEditIn(BaseModel):
    """The five editable fields, at least one. The defaults are never read: only a field the caller sent counts, so
    `series` and `scheduled` can be cleared with null and nothing else can."""

    model_config = ConfigDict(extra="forbid", strict=True)
    title: Text = ""
    series: Text | None = None
    scheduled: WindowIn | None = None
    agenda: Annotated[list[AgendaIn], Field(max_length=20)] = []
    attendees: Annotated[list[AttendeeIn], Field(max_length=50)] = []

    @model_validator(mode="after")
    def _names_one(self) -> MeetingEditIn:
        if not self.model_fields_set:
            raise ValueError("empty")
        return self


def _not_found() -> Refusal:
    return Refusal(404, "not_found")


def _mine(w: Writer, meeting_id: str, action: str, gone: tuple[str, ...]) -> tuple[dict[str, Any], int, Directory]:
    """The owner's meeting, its version and a directory of the owner alone (no whole-org listing, PE-19)."""
    stored, me = w.stores.meetings.get(w.org, meeting_id), w.stores.persons.get(w.org, w.actor)
    if stored is None or me is None or stored.record["status"] in gone:
        raise _not_found()
    d = Directory.of([me.record])
    if not decide(AccessRequest(w.actor, action, "meeting", stored.record, w.now), d).allowed:
        raise _not_found()
    return dict(stored.record), stored.version, d


def get_meeting(w: Writer, meeting_id: str) -> dict[str, Any]:
    """The stored meeting, a discarded one too; a deleted meeting is gone for everyone (FR-MTG-10)."""
    return _mine(w, meeting_id, "read_full", ("deleted",))[0]


def list_meetings(w: Writer) -> dict[str, Any]:
    """Owner-indexed, oracle-vetted records; deleted meetings never leave the store."""
    directory = w.directory()
    if directory.record(w.actor) is None:
        raise _not_found()
    rows = []
    for stored in w.stores.meetings.list(w.org, "owner", w.actor):
        record = stored.record
        if record["owner"] != w.actor or record["status"] == "deleted":
            continue
        got = read(AccessRequest(w.actor, "read_full", "meeting", record, w.now), directory)
        if got is not None:
            rows.append(got)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return {"items": rows[:200], "truncated": len(rows) > 200}


def edit_meeting(w: Writer, meeting_id: str, body: MeetingEditIn) -> dict[str, Any]:
    """Title, series, schedule, agenda and attendees (PE-07); legacy captions keep their resolved `user`, emails
    resolve in the current team directory (PE-15). Text goes through `Writer.text`; the schema refuses a link."""
    m, version, d = _mine(w, meeting_id, "edit", GONE)
    sent, after = body.model_fields_set, dict(m)
    if "title" in sent:
        after["title"] = w.text(body.title)
    if "series" in sent:
        after["series"] = None if body.series is None else w.text(body.series)
    if "scheduled" in sent:
        after["scheduled"] = body.scheduled and body.scheduled.model_dump()
    if "agenda" in sent:
        after["agenda"] = [{"title": w.text(a.title), "minutes": a.minutes} for a in body.agenda]
    if "attendees" in sent:
        known = {a["name"]: a["user"] for a in reversed(m["attendees"])}
        after["attendees"] = meeting_attendees(w, body.attendees, known)
    if not conforms("meeting.schema.json", after):
        raise Refusal(422, "invalid_record")
    request = AccessRequest(w.actor, "edit", "meeting", m, w.now)
    w.commit(request, after, w.stores.meetings, d, _not_found(), version=version)
    return after


def _clean(value: Any, redact: Callable[[str], str]) -> Any:
    """PE-24: every string of the document, control, format and separator characters out, then the secret redactor."""
    if isinstance(value, str):
        return redact(clean_line(value))
    if isinstance(value, list):
        return [_clean(v, redact) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v, redact) for k, v in value.items()}
    return value


def read_minutes(
    w: Writer, artifacts: ArtifactStore, redact: Callable[[str], str], meeting_id: str
) -> dict[str, Any] | None:
    """The minutes of the owner's minuted meeting, before `delete_minutes_after` (`>=` it is gone, like the transcript
    sweep). The owner may read them before confirming them (S-26). None is the 404; a document that is not a minutes
    document raises (the route's 503)."""
    m = _mine(w, meeting_id, "read_full", GONE)[0]
    ref, world, until = m["minutes"], m.get("world_id"), m["delete_minutes_after"]
    if m["status"] != "minuted" or ref is None or world is None or (until is not None and w.now >= until):
        return None
    doc = read_doc(artifacts, Scope(m["org_id"], world, m["owner"]), ref)
    if doc is None or doc.get("meeting_id") != m["id"]:
        return None
    cleaned = _clean(doc, redact)
    if not conforms("minutes.schema.json", cleaned):
        raise ValueError("not a minutes document")
    return cleaned  # type: ignore[no-any-return]


def set_world(w: Writer, worlds: deps.MeetingWorlds, meeting_id: str) -> dict[str, Any]:
    """Stores the world the maker answered, once (BQ-273): a meeting that has one answers unchanged and the maker is
    not asked. The id never comes from the request; an answer that is not a world id is never stored (503)."""
    m, version, d = _mine(w, meeting_id, "edit", GONE)
    if m.get("world_id") is not None:
        return m
    world = worlds.make_meeting_world(org_id=w.org, owner=m["owner"], meeting_id=m["id"])
    if not isinstance(world, str) or _WORLD.fullmatch(world) is None:
        raise ValueError("not a world id")
    after = {**m, "world_id": world}
    w.commit(
        AccessRequest(w.actor, "edit", "meeting", m, w.now), after, w.stores.meetings, d, _not_found(), version=version
    )
    return after
