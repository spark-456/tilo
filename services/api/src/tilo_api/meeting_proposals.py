"""Prepare owner-only proposed records from pinned minutes; persistence is a separate guarded step."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from tilo_contracts import Minutes, Transcript
from tilo_memory.artifacts import ArtifactError, ArtifactStore, NewVersion, Origin, Scope
from tilo_people.access import AccessRequest
from tilo_people.errors import AlreadyExists, NotFound, VersionConflict
from tilo_people.names import match_name
from tilo_people.writes import check_write
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.people_meetings import _mine
from tilo_api.people_quotes import GONE
from tilo_api.people_writes import Refusal, Writer, _purge


@dataclass(frozen=True)
class ProposedItems:
    """Content and optimistic guards, never authority to persist or confirm these records."""

    meeting_version: int
    minutes: dict[str, Any]
    transcript: dict[str, Any]
    items: tuple[dict[str, Any], ...]


def prepare_proposed_items(
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    meeting_id: str,
    *,
    expected_version: int | None = None,
) -> ProposedItems:
    """Read exact artifact versions after owner/world/retention checks; return schema-valid proposed items.

    Nothing is stored, linked in minutes, confirmed, emitted or sent. The future persistence caller must
    recheck meeting_version, both pins and access at its write boundary, then use the existing confirmation
    flow. Unverified, unresolved, already linked or unrepresentable actions remain in the minutes.
    """
    meeting, version, _ = _mine(w, meeting_id, "read_full", GONE)
    if expected_version is not None and version != expected_version:
        raise Refusal(409, "version_conflict")
    if meeting["status"] != "minuted":
        raise Refusal(409, "minutes_unavailable")
    world_id, minutes_ref, transcript_ref = meeting.get("world_id"), meeting["minutes"], meeting["transcript"]
    if world_id is None or minutes_ref is None or transcript_ref is None:
        raise Refusal(409, "minutes_unavailable")
    if any(
        meeting[field] is None or w.now >= meeting[field]
        for field in ("delete_minutes_after", "delete_transcript_after")
    ):
        raise Refusal(409, "minutes_unavailable")
    world = store.load_world(world_id, settle=False)
    if world is None or world.owner != w.actor:
        raise Refusal(404, "not_found")
    scope = Scope(w.org, world_id, w.actor)
    try:
        minutes = json.loads(artifacts.read(scope, minutes_ref))
        Minutes.model_validate(minutes)
        transcript = Transcript.model_validate_json(artifacts.read(scope, transcript_ref))
        heads = [artifacts.head(scope, ref) for ref in (minutes_ref, transcript_ref)]
    except (ArtifactError, ValidationError, ValueError):
        raise Refusal(409, "minutes_unavailable") from None
    if any(head is None for head in heads):
        raise Refusal(409, "minutes_unavailable")
    if (
        minutes["meeting_id"] != meeting_id
        or transcript.meeting_id != meeting_id
        or minutes["transcript"] != transcript_ref
    ):
        raise Refusal(409, "minutes_unavailable")
    utterances = {row.id for row in transcript.utterances}
    action_ids = [row["id"] for row in minutes["action_items"]]
    if len(set(action_ids)) != len(action_ids):
        raise Refusal(409, "invalid_minutes")
    directory = w.org_directory()
    items = []
    flagged = minutes["flagged"] or any(head.doc["screening"] != "clean" for head in heads if head is not None)
    for action in minutes["action_items"]:
        if action["state"] != "verified" or action["owner"] is None or action["work_item_id"] is not None:
            continue
        if not action["evidence"] or not set(action["evidence"]) <= utterances:
            raise Refusal(409, "invalid_evidence")
        if match_name(action["owner_text"], directory, viewer=w.actor, now=w.now).user != action["owner"]:
            continue  # an identity no longer uniquely visible must be resolved again by the owner
        source = {"kind": "meeting", "ref": f"{meeting_id}#{action['id']}", "evidence": action["evidence"]}
        pin_key = json.dumps([w.org, meeting_id, minutes_ref, transcript_ref, action["id"]], sort_keys=True)
        record = {
            "id": "wi_" + hashlib.sha256(pin_key.encode()).hexdigest()[:24],
            "org_id": w.org,
            "owner": action["owner"],
            "title": action["text"],
            "due": action["due"],
            "due_text": action["due_text"],
            "status": "proposed",
            "source": source,
            "created_by": {"by": "tilo", "ref": "A_meeting_minutes", "at": w.now},
            "assigned_by": w.stamp(),
            "confirmed_by": None,
            "snoozed_until": None,
            "flagged": flagged,
            "history": [{"at": w.now, "by": "A_meeting_minutes", "change": "created", "status": "proposed"}],
            "created_at": w.now,
            "updated_at": w.now,
        }
        if conforms("work_item.schema.json", record):
            items.append(record)  # no truncation of titles or supporting evidence to fit a smaller schema
    _, current_version, _ = _mine(w, meeting_id, "read_full", GONE)
    if current_version != version:
        raise Refusal(409, "version_conflict")
    world = store.load_world(world_id, settle=False)
    if world is None or world.owner != w.actor:
        raise Refusal(404, "not_found")
    return ProposedItems(version, dict(minutes_ref), dict(transcript_ref), tuple(items))


def persist_proposed_items(
    w: Writer, store: deps.Store, artifacts: ArtifactStore, meeting_id: str, batch: ProposedItems
) -> dict[str, Any]:
    """Internal owner-only seam. Per-call CAS and compensation, never a cross-store transaction.

    Rebuild the batch rather than accepting its mutable dictionaries as authority. New records stay proposed;
    existing confirmation remains separate. A concurrent confirmed/edited record is never undone. Events already
    acknowledged remain historical facts even if a later boundary fails. No card, recipient or outbox is made.
    """

    def guard() -> dict[str, Any]:
        current = prepare_proposed_items(w, store, artifacts, meeting_id, expected_version=batch.meeting_version)
        if current != batch:
            raise Refusal(409, "proposal_conflict")
        meeting, version, _ = _mine(w, meeting_id, "read_full", GONE)
        if (
            version != batch.meeting_version
            or meeting["minutes"] != batch.minutes
            or meeting["transcript"] != batch.transcript
        ):
            raise Refusal(409, "version_conflict")
        if meeting["minutes_confirmed_by"] is not None:
            raise Refusal(409, "minutes_confirmed")
        return meeting

    meeting = guard()
    if not batch.items:
        return meeting
    if w.events is None:
        raise Refusal(503, "not_configured")
    scope = Scope(w.org, meeting["world_id"], w.actor)
    world = store.load_world(scope.world_id, settle=False)
    if world is None or world.owner != w.actor:
        raise Refusal(404, "not_found")
    made = None
    committed = None
    created = []
    try:
        doc = json.loads(artifacts.read(scope, batch.minutes))
        links = {item["source"]["ref"].partition("#")[2]: item["id"] for item in batch.items}
        for action in doc["action_items"]:
            if action["id"] in links:
                action["work_item_id"] = links[action["id"]]
        made = artifacts.put(
            scope,
            NewVersion(
                "application/json",
                json.dumps(doc).encode(),
                world.run_id,
                Origin(kind="upload"),
                screening_hint="flagged" if doc["flagged"] else None,
            ),
        )
        if json.loads(artifacts.read(scope, made.ref)) != doc or (
            made.doc["screening"] != "clean" and not doc["flagged"]
        ):
            raise Refusal(409, "minutes_changed")
        for item in batch.items:
            current = guard()
            agent = "A_meeting_minutes"
            after = item
            request = AccessRequest(agent, "create", "work_item", after, w.now, meeting=current)
            if check_write(request, after, w.org_directory()):
                raise Refusal(409, "write_refused")
            stored = w.stores.work_items.create(after)
            created.append(stored)
            w.events.record(w.org, agent, after)
            guard()  # deletion/confirmation during the item/event call must prevent linking
        guard()
        committed = w.stores.meetings.replace({**meeting, "minutes": made.ref}, expected_version=batch.meeting_version)
        current, version, _ = _mine(w, meeting_id, "read_full", GONE)
        world = store.load_world(scope.world_id, settle=False)
        if version != committed.version or world is None or world.owner != w.actor:
            raise Refusal(409, "version_conflict")
        return current
    except BaseException as exc:
        purge = committed is None
        retain_items = False
        if committed is None and made is not None:
            current = w.stores.meetings.get(w.org, meeting_id)
            retain_items = current is not None and current.record["minutes"] == made.ref
            purge = not retain_items  # replace may have landed before its acknowledgement was lost
        if committed is not None and made is not None:
            try:
                w.stores.meetings.replace(meeting, expected_version=committed.version)
                purge = True
            except (NotFound, VersionConflict):
                current = w.stores.meetings.get(w.org, meeting_id)
                retain_items = current is not None and current.record["minutes"] == made.ref
                purge = not retain_items  # preserve every link a concurrent meeting write has consumed
        for row in reversed(created) if not retain_items else ():
            try:
                w.stores.work_items.delete(w.org, row.record["id"], expected_version=row.version)
            except (NotFound, VersionConflict):
                pass  # preserve racing confirmations/edits; deletion's own cleanup handles gone meetings
        if purge and made is not None:
            _purge(artifacts, scope, made.artifact_id)
        if isinstance(exc, Refusal):
            raise
        if isinstance(exc, (AlreadyExists, VersionConflict)):
            raise Refusal(409, "version_conflict") from None
        if isinstance(exc, Exception):
            raise Refusal(503, "unavailable") from None
        raise
