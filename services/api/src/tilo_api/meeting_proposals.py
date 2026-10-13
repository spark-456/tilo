"""Prepare owner-only proposed records from pinned minutes; persistence is a separate guarded step."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from tilo_contracts import Minutes, Transcript
from tilo_memory.artifacts import ArtifactError, ArtifactStore, Scope
from tilo_people.names import match_name
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.people_meetings import _mine
from tilo_api.people_quotes import GONE
from tilo_api.people_writes import Refusal, Writer


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
            "created_by": {"by": "tilo", "ref": "system", "at": w.now},
            "assigned_by": w.stamp(),
            "confirmed_by": None,
            "snoozed_until": None,
            "flagged": flagged,
            "history": [{"at": w.now, "by": "system", "change": "created", "status": "proposed"}],
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
