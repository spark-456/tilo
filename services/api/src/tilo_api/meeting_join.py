"""Owner-only receipt resolution and ephemeral join read (MJ-01 to MJ-09). No bot launch."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from tilo_contracts import MeetingHostRpcReceipt, MeetingJoin
from tilo_memory.artifacts import ArtifactStore, Scope

from tilo_api import deps
from tilo_api.meeting_host_rpc import HostRpcError, MeetingHostRpc
from tilo_api.people_limits import limits_of
from tilo_api.people_meetings import _mine
from tilo_api.people_quotes import read_doc
from tilo_api.people_writes import Refusal, Writer


def owned_receipt(w: Writer, store: deps.Store, artifacts: ArtifactStore, meeting_id: str) -> dict[str, Any]:
    if re.fullmatch(r"mt_[0-9A-Za-z_]{1,48}", meeting_id) is None:
        raise Refusal(404, "not_found")
    meeting = _mine(w, meeting_id, "read_full", ("deleted",))[0]
    world_id = meeting.get("world_id")
    world = store.load_world(world_id, settle=False) if world_id else None
    if world is not None and world.owner != w.actor:
        raise Refusal(404, "not_found")
    if (
        not isinstance(world_id, str)
        or world is None
        or meeting["source"] != "bot"
        or meeting["status"] not in ("scheduled", "joining", "live")
    ):
        raise Refusal(409, "not_joinable")
    stream = list(store.events.get(world_id, []))
    transfers = {
        e["id"]
        for e in stream
        if e.get("type") == "data.transfer"
        and e.get("data", {}).get("connector") == "meeting_host"
        and e.get("data", {}).get("direction") == "out"
    }
    candidates = sorted(
        (e for e in stream if e.get("type") == "artifact.created" and e.get("cause") in transfers),
        key=lambda e: e.get("seq", 0),
        reverse=True,
    )
    for event in candidates:
        ref = event.get("data", {}).get("artifact")
        if not isinstance(ref, dict):
            continue
        doc = read_doc(artifacts, Scope(w.org, world_id, w.actor), ref)
        if (
            doc is None
            or doc.get("kind") != "meeting_event_receipt"
            or doc.get("meeting_id") != meeting_id
            or doc.get("connector") != "meeting_host"
            or doc.get("calendar") != "primary"
        ):
            continue
        receipt = {key: doc.get(key) for key in ("meeting_id", "outbox_id", "draft", "event_ref", "conference")}
        receipt.update(world_id=world_id, owner=w.actor)
        return MeetingHostRpcReceipt.model_validate(receipt).model_dump(mode="json")
    raise Refusal(409, "not_joinable")


def owner_join(w: Writer, store: deps.Store, artifacts: ArtifactStore, client: MeetingHostRpc, meeting_id: str) -> dict:
    receipt = owned_receipt(w, store, artifacts, meeting_id)
    now = datetime.fromisoformat(w.now.replace("Z", "+00:00"))
    limits_of(w.stores).attempt(f"meeting_join:{w.actor}", now.timestamp(), limit=10)
    try:
        join = client.join_link(receipt)
    except HostRpcError as error:
        if error.kind == "rejected" and error.code in ("not_joinable", "no_join_link", "host_not_connected"):
            raise Refusal(409, error.code) from None
        raise Refusal(503, "try_again") from None
    # Recheck deletion, owner and host provenance after the remote read.
    if owned_receipt(w, store, artifacts, meeting_id) != receipt:
        raise Refusal(409, "not_joinable")
    expires = (now + timedelta(seconds=60)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return MeetingJoin(join_url=join.join_url, expires_at=expires).model_dump(mode="json")
