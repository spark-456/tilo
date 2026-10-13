"""Explicit owner attendance and scoped transcript ingestion. A join read never calls this."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from tilo_contracts import MeetingJoin, Transcript
from tilo_memory.artifacts import ArtifactStore, NewVersion, Origin, Scope
from tilo_people.errors import VersionConflict

from tilo_api import deps
from tilo_api.meeting_host_rpc import MeetingHostRpc
from tilo_api.meeting_join import owned_receipt
from tilo_api.people_meetings import _mine
from tilo_api.people_writes import Refusal, Writer, _purge


@dataclass(frozen=True)
class BotCapture:
    transcript: Transcript
    reason: str


class BotClient(Protocol):
    async def attend(self, meeting_id: str, join: MeetingJoin) -> BotCapture: ...


async def attend_meeting(
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    host: MeetingHostRpc,
    bot: BotClient,
    meeting_id: str,
    clock: Callable[[], str],
) -> dict[str, Any]:
    receipt = owned_receipt(w, store, artifacts, meeting_id)
    meeting, version, _ = _mine(w, meeting_id, "read_full", ("deleted",))
    if meeting["status"] != "scheduled" or meeting["transcript"] is not None:
        raise Refusal(409, "already_attending")
    join = await asyncio.to_thread(host.join_link, receipt)
    if owned_receipt(w, store, artifacts, meeting_id) != receipt:
        raise Refusal(409, "not_joinable")
    try:
        claim = w.stores.meetings.replace({**meeting, "status": "joining"}, expected_version=version)
    except VersionConflict:
        raise Refusal(409, "already_attending") from None
    scope = Scope(w.org, receipt["world_id"], w.actor)
    made = None
    try:
        capture = await bot.attend(meeting_id, join)
        if capture.transcript.meeting_id != meeting_id or capture.reason not in (
            "completed",
            "left_on_request",
            "removed",
            "timeout",
            "failed",
        ):
            raise Refusal(502, "invalid_capture")
        current, current_version, _ = _mine(w, meeting_id, "read_full", ("deleted", "discarded"))
        if current["status"] != "joining" or current.get("world_id") != scope.world_id:
            raise Refusal(409, "capture_changed")
        document = capture.transcript.model_dump(mode="json")
        for utterance in document["utterances"]:
            for field in ("text", "speaker"):
                utterance[field] = re.sub(
                    r"(?:https?://)?meet\.google\.com/[^\s<>\"']+",
                    "[Meet link removed]",
                    utterance[field],
                    flags=re.I,
                )
        transcript = Transcript.model_validate(document)
        world = store.load_world(scope.world_id, settle=False)
        if world is None or world.owner != w.actor:
            raise Refusal(404, "not_found")
        # Incoming bot data is ingested as an upload; the store screens/redacts it and owns hash/ids.
        made = artifacts.put(
            scope,
            NewVersion(
                "application/json",
                transcript.model_dump_json().encode(),
                world.run_id,
                Origin(kind="upload"),
            ),
        )
        stored_transcript = Transcript.model_validate_json(artifacts.read(scope, made.ref))
        if stored_transcript.meeting_id != meeting_id:
            raise Refusal(502, "invalid_capture")
        ended = datetime.fromisoformat(clock().replace("Z", "+00:00"))
        retain_until = (ended + timedelta(days=30)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        after = {
            **current,
            "status": "ended",
            "ended_reason": capture.reason,
            "transcript": made.ref,
            "delete_transcript_after": retain_until,
        }
        w.stores.meetings.replace(after, expected_version=current_version)
        return after
    except BaseException:
        if made is not None:
            _purge(artifacts, scope, made.ref["artifact_id"])
        # A failed attempt releases only its own claim; never resurrect a deleted or concurrently changed record.
        latest = w.stores.meetings.get(w.org, meeting_id)
        if latest is not None and latest.version == claim.version and latest.record["status"] == "joining":
            try:
                w.stores.meetings.replace(meeting, expected_version=claim.version)
            except VersionConflict:
                pass
        raise
