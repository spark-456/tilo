"""Explicit owner attendance and scoped transcript ingestion. A join read never calls this."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Protocol

from fastapi import Depends, Request
from pydantic import ValidationError
from tilo_contracts import MeetingJoin, Transcript
from tilo_memory.artifacts import ArtifactStore, NewVersion, Origin, Scope
from tilo_metering.flags import FlagStore
from tilo_people.errors import VersionConflict

from tilo_api import deps
from tilo_api.meeting_host_rpc import HostRpcError, MeetingHostRpc
from tilo_api.meeting_join import owned_receipt
from tilo_api.meeting_voice_claims import AttendClaims
from tilo_api.people_limits import limits_of
from tilo_api.people_meetings import _mine
from tilo_api.people_writes import Refusal, Writer, _purge

logger = logging.getLogger("tilo_api.meeting_bot")


@dataclass(frozen=True)
class BotCapture:
    transcript: Transcript
    reason: str


class BotClient(Protocol):
    async def attend(self, meeting_id: str, join: MeetingJoin, claim: str | None = None) -> BotCapture: ...


def attend_artifacts(
    request: Request,
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    mode: Annotated[deps.Mode, Depends(deps.get_work_mode)],
    switches: Annotated[FlagStore, Depends(deps.get_switches)],
) -> ArtifactStore:
    """MINUTES-SCREEN: the store an attend request keeps its transcript in. The shared store's own screen has no meter
    and, deployed, reads recordings, so every transcript stayed `unscreened` and no minutes could be made (20 Oct).
    Live, the transcript is screened by this request's metered screen (SEC-16), as a run screens its outputs; with no
    meter (replay, a demo, unreadable limits) the shared store is used unchanged and the transcript stays unscreened."""
    meter = deps.meter_for(request, mode, switches)
    if mode == "live" and meter is not None:
        return artifacts.with_screener(deps.get_safety(mode, meter=meter))
    return artifacts


async def attend_meeting(
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    host: MeetingHostRpc,
    bot: BotClient,
    meeting_id: str,
    clock: Callable[[], str],
    claims: AttendClaims | None = None,
    join_url: str | None = None,
) -> dict[str, Any]:
    # MEET-GUEST: with `join_url` Tilo's guest bot goes to the person's own Google Meet and the host admits it; no
    # meeting host account is involved. The link is checked like a MeetingJoin, used once and stored nowhere (MJ rules).
    receipt = None if join_url is not None else owned_receipt(w, store, artifacts, meeting_id)
    meeting, version, _ = _mine(w, meeting_id, "read_full", ("deleted",))
    world_id = receipt["world_id"] if receipt is not None else _guest_world(w, store, meeting)
    if meeting["status"] != "scheduled" or meeting["transcript"] is not None:
        raise Refusal(409, "already_attending")
    wake = getattr(bot, "wake", None)
    if wake is not None:  # a cold bot answers before the 60-second join link is made, never after (MEET-SIMPLE)
        await wake()
    if join_url is not None:
        join = _guest_join(w, join_url)
    else:
        try:
            join = await asyncio.to_thread(host.join_link, receipt)
        except HostRpcError as error:
            if error.kind == "rejected" and error.code == "host_not_connected":
                raise Refusal(409, "Tilo's meeting host needs to be signed in") from None
            if error.kind == "rejected" and error.code in ("not_joinable", "no_join_link"):
                raise Refusal(409, error.code) from None
            logger.warning("meeting attend join link unavailable (%s)", error.kind)
            raise Refusal(503, "bot_unavailable") from None
        if owned_receipt(w, store, artifacts, meeting_id) != receipt:
            raise Refusal(409, "not_joinable")
    try:
        claim = w.stores.meetings.replace({**meeting, "status": "joining"}, expected_version=version)
    except VersionConflict:
        raise Refusal(409, "already_attending") from None
    scope = Scope(w.org, world_id, w.actor)
    made = None
    # ADR-0042: the voice meter's claim, from the verified principal and only here; off (None) the call is unchanged.
    nonce = claims.open(meeting_id, uid=w.actor, org_id=w.org) if claims is not None else None
    try:
        capture = await (bot.attend(meeting_id, join) if nonce is None else bot.attend(meeting_id, join, nonce))
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
    finally:
        if claims is not None and nonce is not None:
            claims.end(meeting_id, nonce)


def _guest_world(w: Writer, store: deps.Store, meeting: dict[str, Any]) -> str:
    """The guest path's version of `owned_receipt`'s checks: a bot meeting with the caller's own world."""
    world_id = meeting.get("world_id")
    world = store.load_world(world_id, settle=False) if isinstance(world_id, str) else None
    if world is not None and world.owner != w.actor:
        raise Refusal(404, "not_found")
    if world is None or meeting["source"] != "bot":
        raise Refusal(409, "not_joinable")
    return world_id


def _guest_join(w: Writer, join_url: str) -> MeetingJoin:
    now = datetime.fromisoformat(w.now.replace("Z", "+00:00"))
    limits_of(w.stores).attempt(f"meeting_join:{w.actor}", now.timestamp(), limit=10)
    expires = (now + timedelta(seconds=60)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        return MeetingJoin(join_url=join_url, expires_at=expires)
    except ValidationError:
        raise Refusal(422, "Paste a Google Meet link like https://meet.google.com/abc-defg-hij") from None
