"""tilo_api.connector_rpc: the outbox's live Google connectors in tilo-api (ADR-0035 decision 5, LC-07, LC-08, LC-10).

`ConnectorRpcStub` takes `GmailAdapter`, `DriveAdapter` and `CalendarWriteAdapter`'s place in a run's connector map: the
outbox calls its `execute_side_effect`, which reads the pinned artifacts (hash-checked, AR-01), posts them with the
evidence to tilo-connectors' `/internal/side-effects/execute` over `MeetingHostRpc` (the one boundary, HB-01) and maps
the answer to the outcome `MeetingHostStub` maps (ADR-0032 decision 6): refused is final, possibly_sent is never
failed, retry is retried, and a `sent` answer is stored only when its marker is the entry's own (LC-08). Nothing here
imports `tilo_connectors.tokens`, `.live` or `.adapters` (SEC-02). A stub made by the seam knows no run, so it cannot
execute (it retries without sending); a run binds its own copy (`bound`) with its artifact reader, its part sink and its
owner. `evidence.world_owner` is that bound owner (the signed-in person who started the world), never the caller's
copy; the recipients are the entry's. Items are the artifacts' own bytes, which must already be BQ-ADR35L5-1
documents (UTF-8 JSON with a `kind`): anything else is refused before a call.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from tilo_connectors.errors import PossiblySent, ProviderUnavailable, SideEffectRefused
from tilo_contracts import MeetingHostRpcAlertPart, MeetingHostRpcConnectorPart
from tilo_memory.artifacts import ArtifactCorrupt

from tilo_api.meeting_host_rpc import HostRpcError, MeetingHostRpc, NotSent, side_effect_marker

logger = logging.getLogger("tilo_api.connector_rpc")
PERSON_CONNECTORS = ("gmail", "google_drive", "google_calendar")  # the execute contract's connector enum (CON-D10)
_KINDS = frozenset({"email", "file", "calendar_event"})
NO_DRAFT = "the email has no saved draft of this exact content, so it is not sent"  # LC-10's one fixed reason


class ConnectorRpcStub:
    """One live connector's outbox adapter. `read_item(ref)` is the run's hash-checked artifact read, `sink(part)` the
    run's connection/alert handler (a sink error never fails the call)."""

    needs_run = True  # the Scheduler's sweep skips it: only the run that holds the evidence can send

    def __init__(
        self,
        connector: str,
        rpc: MeetingHostRpc,
        read_item: Callable[[dict[str, Any]], bytes] | None = None,
        sink: Callable[[dict[str, Any]], Any] | None = None,
        owner: str | None = None,
    ) -> None:
        self.connector, self._rpc, self._read, self._sink, self._owner = connector, rpc, read_item, sink, owner
        self._evidence: dict[str, dict[str, Any]] = {}

    def bound(
        self, read_item: Callable[[dict[str, Any]], bytes], sink: Callable[[dict[str, Any]], Any], owner: str
    ) -> ConnectorRpcStub:
        return ConnectorRpcStub(self.connector, self._rpc, read_item, sink, owner)

    def hand_evidence(self, outbox_id: str, evidence: Mapping[str, Any]) -> None:
        self._evidence[outbox_id] = json.loads(json.dumps(evidence))

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Any) -> None:
        grant.verify(entry["idempotency_key"])  # SEC-03: only the outbox's own dispatch, before anything is read
        evidence = self._evidence.get(entry["id"])
        if self._read is None or self._owner is None:
            raise NotSent("no run holds this entry's content here")  # nothing sent; retried by the run that does
        if evidence is None or entry["connector"] != self.connector or entry.get("item") is None:
            raise SideEffectRefused("no evidence was handed for this entry")
        refs = [entry["item"], *entry["attachments"]]
        items = [self._pinned(ref) for ref in refs]
        evidence = {**evidence, "world_owner": self._owner}  # the world's owner is the run's, whatever the copy says
        was = (
            "scheduled" if entry.get("undo_window_s") else "queued"
        )  # the claimed ("sending") entry, as enqueued: OB-02
        try:
            answer = self._rpc.execute_entry({**entry, "state": was}, evidence, items)
        except HostRpcError as exc:
            if exc.kind == "refused":
                raise SideEffectRefused("connectors refused the action") from None
            if exc.kind == "not_sent":
                raise NotSent("the action was not sent") from None
            raise ProviderUnavailable("the action may have reached connectors") from None
        self._deliver(answer.parts, str(self._owner))
        if answer.outcome == "refused":
            raise SideEffectRefused("connectors refused the action")
        if answer.outcome == "possibly_sent":
            raise PossiblySent("connectors cannot tell whether it was done")
        if answer.outcome == "retry":
            if answer.may_have_sent:
                raise ProviderUnavailable("connectors may have done it")
            raise NotSent("connectors had nothing to act with yet")
        if answer.result is None or answer.result.marker != side_effect_marker(entry):  # LC-08
            raise PossiblySent("the answer does not match the entry")  # it is on Google's side, so a person looks

    def _pinned(self, ref: Mapping[str, Any]) -> dict[str, Any]:
        assert self._read is not None
        try:
            raw = self._read({"artifact_id": ref["artifact_id"], "version": ref["version"]})
        except ArtifactCorrupt:  # AR-01: the bytes are not the pinned ones, and will not become so
            raise SideEffectRefused("a pinned item does not match its hash") from None
        except Exception:  # noqa: BLE001 - any other read error may pass: nothing was sent, try again
            raise NotSent("a pinned item cannot be read now") from None
        try:
            document = json.loads(raw)
        except ValueError:
            raise SideEffectRefused("a pinned item is not a document") from None
        if not isinstance(document, dict) or document.get("kind") not in _KINDS:
            raise SideEffectRefused("a pinned item is not a document")
        return {
            "artifact_id": ref["artifact_id"], "version": ref["version"],
            "content_sha256": hashlib.sha256(raw).hexdigest(), "content_b64": base64.b64encode(raw).decode("ascii"),
        }  # fmt: skip

    def _deliver(self, parts: list[Any], user_id: str) -> None:
        """Only this call's own user's connection parts reach the sink (ADR-0032 decision 7)."""
        for part in parts:
            if isinstance(part, MeetingHostRpcAlertPart):  # ids only; the run records it once
                handed: dict[str, Any] = {
                    "type": part.type, "authz": None, "data": {"alert_id": part.alert_id, "card_id": None},
                }  # fmt: skip
            elif isinstance(part, MeetingHostRpcConnectorPart) and part.user_id == user_id:
                handed = {"type": part.type, "authz": None, "data": {"connector": part.connector}, "user_id": user_id}
            else:
                continue
            try:
                if self._sink is not None:
                    self._sink(handed)
            except Exception as exc:  # noqa: BLE001 - a sink error never fails the call
                logger.warning("a connection part was not handled (%s)", type(exc).__name__)
