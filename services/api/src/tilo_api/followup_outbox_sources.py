"""X-SEC37-FU4: fresh source authority and erasure of unsent meeting follow-ups."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter
from tilo_connectors.outbox import _alert_part

from tilo_api.followup_autopilot_state import FirestoreCards
from tilo_api.followup_draft_retention import DraftRetention, followup_retention
from tilo_api.outbox_firestore import FirestoreOutboxStore


def source_valid(entry: dict, world: Any, people: Any, client: Any, org: str, now: float) -> bool:
    """A missing world closes every entry; Autopilot entries also require their retained card's source."""
    if world is None:
        return False
    if not entry["idempotency_key"].startswith("autopilot:"):
        return True
    if world.run_id != entry["run_id"]:
        return False
    owner = world.owner
    if people.persons.get(org, owner) is None:
        return False
    card = entry["idempotency_key"].removeprefix("autopilot:")
    cards = FirestoreCards(client, org_id=org, owner=owner, world_id=entry["world_id"], run_id=entry["run_id"])
    path = cards._path(owner, card)
    found = client.document(path).get()
    if not found.exists:
        return False

    def alive(user: str, source: dict) -> bool:
        meeting = people.meetings.get(org, source.get("meeting_id"))
        return (
            user == owner
            and meeting is not None
            and source.get("world_id") == entry["world_id"]
            and source.get("run_id") == entry["run_id"]
            and meeting.record.get("owner") == owner
            and meeting.record.get("org_id") == org
            and meeting.record.get("status") != "deleted"
            and meeting.record.get("world_id") == entry["world_id"]
            and people.persons.get(org, owner) is not None
        )

    policy = DraftRetention(client, org_id=org, clock=lambda: now, source_valid=alive, state_group="cards")
    payload = policy.read(owner, path, found.to_dict())
    return payload is not None and payload.get("card_id") == card and payload.get("world_id") == entry["world_id"]


def cancel_source_entries(
    client: Any,
    org: str,
    owner: str,
    meeting: str | None = None,
    *,
    store: Any = None,
    clock: Callable[[], str] | None = None,
) -> None:
    """Cancel from retained card keys before erasing those records; never cancel another source."""
    clock = clock or (lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")
    store = store if store is not None else FirestoreOutboxStore(client, clock=clock)
    policy = followup_retention(client, org, lambda: 0.0)[1]
    query = policy._query().where(filter=FieldFilter("owner", "==", owner))
    if meeting is not None:
        query = query.where(filter=FieldFilter("source.meeting_id", "==", meeting))
    # Match retention's three 200-row cleanup passes, plus one overflow probe.
    # Refuse before mutating if completeness cannot be established within this bound.
    # Keep retained metadata on refusal; retry after reducing the retained set.
    try:
        rows = list(query.limit(601).stream())
    except Exception:
        raise HTTPException(503, "store_unavailable") from None
    if len(rows) > 600:
        raise HTTPException(503, "store_unavailable")
    for found in rows:
        row = found.to_dict()
        if row.get("org_id") != org or row.get("owner") != owner:
            raise HTTPException(503, "store_unavailable")
        if meeting is not None and row.get("source", {}).get("meeting_id") != meeting:
            raise HTTPException(503, "store_unavailable")
        payload = json.loads(row["payload"])
        # Artifact index rows do not represent an outbox card.
        if "card_id" not in payload or "world_id" not in payload:
            continue
        entry = store.get_by_idempotency_key(payload["world_id"], f"autopilot:{payload['card_id']}")
        if entry is not None and entry["state"] in {"queued", "scheduled", "sending"}:
            if store._cancel_source(entry["id"], clock(), _alert_part(entry)) is None:
                raise HTTPException(503, "store_unavailable")  # live lease: retry erasure, keep source metadata
