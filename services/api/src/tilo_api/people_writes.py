"""The people writes (PPL-11a slice C; people.rules.md PE-03, PE-07, PE-08, PE-17 to PE-19, API_PPL_11a.md section 5).
Two confirms (a proposed work item, a meeting's minutes) and three creates (a meeting, a person, a work item). Every
write is the same short path: closed JSON body (415, 422), secret redactor on the text fields, the record built from
the body plus the verified actor, the server clock and minted ids only, schema check (422), `tilo_people.check_write`
(its `decide` refusal is the one 404 of a confirm and the 403 of a create), then compare-and-set (one attempt, 409).
No id, org, owner, stamp, status, source, world or `due` ever comes from a request. No model call, no event, no log,
no clock read (`now` is handed in).
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator, model_validator
from tilo_memory.artifacts import ArtifactNotFound, ArtifactStore, Scope
from tilo_people.access import AccessRequest, decide, project
from tilo_people.dates import resolve_due
from tilo_people.directory import Directory
from tilo_people.errors import NotFound, VersionConflict
from tilo_people.stores import PeopleStores, RecordStore, meeting_tombstone
from tilo_people.text import clean_line
from tilo_people.writes import check_write
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.people_quotes import GONE, MAX_HISTORY


class Refusal(HTTPException):
    """An answer with a body beyond `detail` (409 `code`, `problems`); never record text."""

    def __init__(self, status_code: int, detail: str, **extra: Any) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.extra = extra


def _identity(text: str) -> str:
    return text


_ASCII_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FILLERS = frozenset({0x115F, 0x1160, 0x3164, 0xFFA0})  # default-ignorable letters: invisible, never meaningful
_UNASSIGNED_IGNORABLE = frozenset({0x2065, 0x2800})  # unassigned default-ignorable, and the blank braille cell


def _plane14_hidden(o: int) -> bool:
    """Plane 14 is variation selectors and unassigned points; only the tag characters (flag emoji) may stay."""
    return 0xE0000 <= o <= 0xE0FFF and not 0xE0020 <= o <= 0xE007F


def _unhide(text: str) -> str:
    """Invisible characters `clean_line` leaves (default-ignorable Lo and Mn) out, so none can split a token or a link
    before the redactor runs. An invisible mark stays only after a non-ASCII character (an emoji keeps its variation
    selector), and U+FE0E/U+FE0F after a keycap base only when U+20E3 follows (`1` `FE0F` `20E3`)."""
    out: list[str] = []
    for i, c in enumerate(text):
        o = ord(c)
        if o in _FILLERS or o in _UNASSIGNED_IGNORABLE or 0xFFF0 <= o <= 0xFFF8 or _plane14_hidden(o):
            continue
        if o in (0x34F, 0x17B4, 0x17B5) or 0x180B <= o <= 0x180F or 0xFE00 <= o <= 0xFE0F:
            before = out[-1] if out else ""
            keycap = before != "" and before in "#*0123456789" and o in (0xFE0E, 0xFE0F) and text[i + 1 : i + 2] == "⃣"
            if before.isascii() and not keycap:
                continue
        out.append(c)
    return "".join(out)


DUE_TEXT_MAX = 60  # work_item.due_text maxLength
_FROM = ("meeting", "transcript")  # calendar_entry.source.from values that name a meeting


# --- closed request bodies: a field the server owns is a 422 ------------------------------------------------------


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Text = Annotated[str, Field(max_length=1000)]  # a cap before the redactor runs; the schema caps are tighter


class Empty(_Closed):
    """A confirm takes `{}`: the stamp is the actor and the clock."""


class AgendaIn(_Closed):
    title: Text
    minutes: int | None = None


class AttendeeIn(_Closed):
    name: Text  # `user` is never taken from a request: attendees[].user is not identity (PE-15, PPL-20)


class WindowIn(_Closed):
    start: Text
    end: Text | None = None


class MeetingIn(_Closed):
    """`attest` and `notice_version` are the explicit attest step (PE-18, issue #464): the person says `true` and the
    notice version they were shown. Neither is stored from the request; the actor and clock are the server's."""

    attest: StrictBool  # JSON `true` only (`Literal[True]` would admit `1`); anything else is 422, see below
    notice_version: Text
    title: Text
    source: Text
    series: Text | None = None
    scheduled: WindowIn | None = None
    agenda: Annotated[list[AgendaIn], Field(max_length=20)] = []
    attendees: Annotated[list[AttendeeIn], Field(max_length=50)] = []

    @field_validator("attest")
    @classmethod
    def _attested(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("attest")
        return value

    @field_validator("notice_version")
    @classmethod
    def _current_notice(cls, value: str) -> str:
        if value != deps.NOTICE_VERSION:  # read at call time: a stale or future notice was not the one in force
            raise ValueError("notice_version")
        return value


class PersonIn(_Closed):
    display_name: Text
    aliases: Annotated[list[Text], Field(max_length=8)]
    email: Text
    time_zone: Text
    preferred_channel: Text


class SourceIn(_Closed):
    kind: Literal["manual", "mail", "request"]  # a person never claims a meeting or pinboard origin (PE-08)
    ref: Annotated[str, Field(max_length=128)] | None

    @model_validator(mode="after")
    def _ref_iff_tracked(self) -> SourceIn:
        if (self.kind == "manual") != (self.ref is None):
            raise ValueError("ref")
        return self


class ItemIn(_Closed):
    title: Text
    due_text: Text | None = None
    source: SourceIn


def json_body[Body: BaseModel](model: type[Body]) -> Callable[[Request], Awaitable[Body]]:
    """Strict JSON only (415 otherwise: a cross-site form or `text/plain` POST needs no preflight); a 422 that never
    echoes the input."""

    async def parse(request: Request) -> Body:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise Refusal(415, "Send application/json.")
        try:
            return model.model_validate_json(await request.body())
        except ValidationError as exc:
            # A key the caller sent that the model does not know is never echoed (it could be a secret): `?`.
            fields = [[*e["loc"][:-1], "?"] if e["type"] == "extra_forbidden" else list(e["loc"]) for e in exc.errors()]
            raise Refusal(422, "invalid_body", fields=fields) from exc

    return parse


# --- the writes ---------------------------------------------------------------------------------------------------


@dataclass
class Writer:
    """Who writes, into what, when: all from the seams and the verified principal."""

    stores: PeopleStores
    org: str
    actor: str
    now: str
    redact: Callable[[str], str] = _identity

    def directory(self) -> Directory:
        return Directory.of(s.record for s in self.stores.persons.list(self.org))

    def text(self, value: str) -> str:
        """A person's text: every non-ASCII control, format and separator character out first, always (so a zero-width
        character cannot hide a link from the redactor or the schema), then the secret redactor, then the schema.
        ASCII controls are never stripped or joined: the schema refuses them (a line break is a 422), and the
        redactor's output is checked again, since one that removes a multi-line block could otherwise hide them."""
        cleaned = _unhide("".join(c for c in value if c.isascii() or clean_line(c)))
        redacted = self.redact(cleaned)
        if _ASCII_CONTROL.search(redacted):
            raise Refusal(422, "invalid_record")
        return redacted

    def stamp(self) -> dict[str, str]:
        return {"by": self.actor, "at": self.now}

    def commit(
        self,
        request: AccessRequest,
        after: dict[str, Any],
        store: RecordStore,
        directory: Directory,
        denied: Refusal,
        *,
        version: int | None = None,
        also: Callable[[], None] | None = None,
    ) -> None:
        """`check_write`, then the store. `also` runs once the actor is allowed (a source check must not be an oracle
        for people who may not write at all)."""
        problems = check_write(request, after, directory)
        if problems == ("not_allowed",):
            raise denied
        if also is not None:
            also()
        if problems:
            raise Refusal(409, "write_refused", code="write_refused", problems=list(problems))
        try:
            if version is None:
                store.create(after)
            else:
                store.replace(after, expected_version=version)
        except VersionConflict:
            raise Refusal(409, "version_conflict", code="version_conflict") from None
        except NotFound:
            raise denied from None

    def create(
        self,
        kind: str,
        record: dict[str, Any],
        store: RecordStore,
        d: Directory,
        also: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Schema first (422, so it is no oracle), then authorisation (403: no record is revealed)."""
        if not conforms(f"{kind}.schema.json", record):
            raise Refusal(422, "invalid_record")
        request = AccessRequest(self.actor, "create", kind, record, self.now)
        self.commit(request, record, store, d, Refusal(403, "forbidden"), also=also)
        return record


def _mint(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"  # never derived from input, distinct per call


def _not_found() -> Refusal:
    return Refusal(404, "not_found")  # the one body of every refused read or confirm


def confirm_item(w: Writer, item_id: str) -> dict[str, Any]:
    """The assigner confirms a proposed item (PE-03, PE-07): `open`, one `confirmed` entry, the status view back."""
    d = w.directory()
    stored = w.stores.work_items.get(w.org, item_id)
    if stored is None or len(stored.record["history"]) > MAX_HISTORY:  # a huge history is unreadable, never decided
        raise _not_found()
    item = stored.record
    ref = item["source"]["ref"] or ""
    found = w.stores.meetings.get(w.org, ref.partition("#")[0]) if item["source"]["kind"] == "meeting" else None
    if found is not None and found.record["status"] in GONE:  # nothing is released from a gone meeting (#464)
        raise _not_found()
    after = {
        **item,
        "status": "open",
        "confirmed_by": w.stamp(),
        "history": [*item["history"], {**w.stamp(), "change": "confirmed", "status": "open"}],
        "updated_at": w.now,
    }
    request = AccessRequest(w.actor, "confirm", "work_item", item, w.now, meeting=found.record if found else None)
    w.commit(request, after, w.stores.work_items, d, _not_found(), version=stored.version)
    return project("work_item", "status", after) or {}


def confirm_minutes(w: Writer, meeting_id: str) -> dict[str, Any]:
    """The owner confirms the minutes: only `minutes_confirmed_by` changes (PE-05, PE-07)."""
    d = w.directory()
    stored = w.stores.meetings.get(w.org, meeting_id)
    if stored is None:
        raise _not_found()
    after = {**stored.record, "minutes_confirmed_by": w.stamp()}
    request = AccessRequest(w.actor, "confirm", "meeting", stored.record, w.now)
    w.commit(request, after, w.stores.meetings, d, _not_found(), version=stored.version)
    return after


def _drop_proposed(store: RecordStore, org: str, record_id: str, state: str) -> None:
    """Deletes the record while it still exists and is proposed (a racing confirm keeps it); a lost race is retried."""
    for _ in range(3):
        current = store.get(org, record_id)
        if current is None or current.record[state] != "proposed":
            return
        try:
            return store.delete(org, record_id, expected_version=current.version)
        except NotFound:
            return
        except VersionConflict:
            continue
    raise VersionConflict(f"VersionConflict: {store.kind} {record_id}")


def _made_from(meeting_id: str, source: Mapping[str, Any] | None) -> bool:
    """A source naming the meeting or one of its action items (`mt_x`, `mt_x#ai1`) as Tilo's origin (PE-08)."""
    if source is None:  # a pin may have no source
        return False
    ref = source.get("ref")
    meeting_made = source.get("kind") == "meeting" or (source.get("kind") == "tilo" and source.get("from") in _FROM)
    return meeting_made and isinstance(ref, str) and ref.partition("#")[0] == meeting_id


def remove_meeting(w: Writer, artifacts: ArtifactStore, meeting_id: str) -> dict[str, Any]:
    """The owner deletes a meeting and what was made from it (FR-MTG-10, PE-16, PE-19): the transcript and minutes
    artifacts, then the *proposed* items, pins and calendar entries made from it (what the owner released stays the
    assignee's), then the tombstone by compare-and-set, last, so a failure leaves the meeting live and a retry
    finishes. Every step is idempotent; a deleted meeting answers the same again."""
    stored, me = w.stores.meetings.get(w.org, meeting_id), w.stores.persons.get(w.org, w.actor)
    if stored is None or me is None:
        raise _not_found()
    m = stored.record
    if not decide(AccessRequest(w.actor, "edit", "meeting", m, w.now), Directory.of([me.record])).allowed:
        raise _not_found()
    if m["status"] != "deleted":
        if m.get("world_id") is not None:  # no world, no artifact: nothing is stored outside a world
            scope = Scope(m["org_id"], m["world_id"], m["owner"])
            for ref in (m["transcript"], m["minutes"]):
                if ref is not None:
                    _purge(artifacts, scope, ref["artifact_id"])
        for store, state in ((w.stores.work_items, "status"), (w.stores.pins, "status"), (w.stores.calendar, "state")):
            for row in store.list(w.org):
                if row.record[state] == "proposed" and _made_from(meeting_id, row.record["source"]):
                    _drop_proposed(store, w.org, row.record["id"], state)
        try:
            w.stores.meetings.replace(meeting_tombstone(m), expected_version=stored.version)
        except VersionConflict:
            raise Refusal(409, "version_conflict", code="version_conflict") from None
        except NotFound:
            raise _not_found() from None
    return {"id": meeting_id, "status": "deleted"}


def _purge(artifacts: ArtifactStore, scope: Scope, artifact_id: str) -> None:
    """Every stored version of one artifact: blob generations and manifests, then the record (the FR-MEM-09 adapter)."""
    try:
        versions = artifacts.versions(scope, artifact_id)
    except ArtifactNotFound:
        return  # already gone: a retry
    prefix = f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/{artifact_id}/versions"
    for version in versions:
        artifacts.retention().delete(f"{prefix}/{version.version:06d}")


def create_meeting(w: Writer, body: MeetingIn) -> dict[str, Any]:
    """A person of the org adds a meeting they own and attest; the server stamps the attestation (PE-18, G2)."""
    r = w.text
    record: dict[str, Any] = {
        "id": _mint("mt"),
        "org_id": w.org,
        "owner": w.actor,
        "title": r(body.title),
        "series": None if body.series is None else r(body.series),
        "scheduled": body.scheduled and body.scheduled.model_dump(),
        "agenda": [{"title": r(a.title), "minutes": a.minutes} for a in body.agenda],
        "attendees": [{"name": r(a.name), "user": None} for a in body.attendees],
        "attestation": {**w.stamp(), "notice_version": deps.NOTICE_VERSION},
        "source": body.source,
        "status": "scheduled",
        "ended_reason": None,
        "minutes_confirmed_by": None,
        "transcript": None,
        "minutes": None,
        "delete_transcript_after": None,
        "delete_minutes_after": None,
        "created_at": w.now,
    }
    return w.create("meeting", record, w.stores.meetings, w.directory())


def create_person(w: Writer, body: PersonIn) -> dict[str, Any]:
    """An org owner adds a member; the id and the org are the server's (PE-17, G1). Answers the membership view."""
    r = w.text
    record: dict[str, Any] = {
        "id": _mint("u"),
        "org_id": w.org,
        "display_name": r(body.display_name),
        "aliases": [r(a) for a in body.aliases],
        "email": body.email,
        "time_zone": body.time_zone,
        "preferred_channel": body.preferred_channel,
        "org_role": "member",
        "memberships": [],
        "created_by": w.stamp(),
    }
    return project("person", "membership", w.create("person", record, w.stores.persons, w.directory())) or {}


def create_item(w: Writer, body: ItemIn, owners: Callable[[], deps.SourceOwners]) -> dict[str, Any]:
    """A person adds their own item (PE-03, PE-08): owner is the caller, `due` is code's, a mail or request source
    must be the caller's (someone else's ref and a missing ref are one 422)."""
    d = w.directory()
    me = d.record(w.actor)
    due_text = None if body.due_text is None else w.text(body.due_text)
    if due_text is not None and len(due_text) > DUE_TEXT_MAX:
        raise Refusal(422, "invalid_record")  # never a silent null: the person is told the phrase is too long
    due = resolve_due(
        due_text,
        meeting_at=w.now,
        time_zone=me["time_zone"] if me else "UTC",
    )
    record: dict[str, Any] = {
        "id": _mint("wi"),
        "org_id": w.org,
        "owner": w.actor,
        "title": w.text(body.title),
        "due": due.due,
        "due_text": due.due_text,
        "status": "open",
        "source": {"kind": body.source.kind, "ref": body.source.ref, "evidence": []},
        "created_by": {"by": "person", "ref": w.actor, "at": w.now},
        "assigned_by": None,
        "confirmed_by": None,
        "snoozed_until": None,
        "flagged": False,
        "history": [{"at": w.now, "by": w.actor, "change": "created", "status": "open"}],
        "created_at": w.now,
        "updated_at": w.now,
    }

    def own_source() -> None:
        if body.source.ref is not None and owners().owner_of(body.source.kind, body.source.ref) != w.actor:
            raise Refusal(422, "source_not_found", code="source_not_found")

    return w.create("work_item", record, w.stores.work_items, d, own_source)
