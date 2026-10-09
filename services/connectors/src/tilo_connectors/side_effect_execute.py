"""tilo_connectors.side_effect_execute — `/internal/side-effects/execute` for gmail, google_drive, google_calendar
(ADR-0035 decision 5, LC-07 to LC-10; `meeting_host` keeps its own route).

The same shape as the meeting-host `send`: the items are hash-checked first (HB-03), the entry goes through an
`Outbox` built for this request over a fresh in-memory store, whose `dispatch_due()` mints the Grant (HB-04, SEC-03),
the broker refuses a grant newer than the approval (HB-06) and `owner_of` answers `evidence.world_owner`. The answer is
one of four outcomes with `result = {resource_id, marker}` only; no mail text, title or address is ever in it or in a
log line (a failure logs its exception type).

Item documents (BQ-ADR35L5-1): the decoded bytes of the entry's item and of each attachment are UTF-8 JSON with a
`kind`: `email` {subject, body_text, in_reply_to?, references?}, `file` {name, mime_type, content_b64, origin?},
`calendar_event` {title, start, end, time_zone, attendees?}. The adapters read them through `_Documents`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from typing import Any

from ._schema import host_rpc_validator
from .adapters import DriveAdapter, GmailAdapter, InMemoryPicks, side_effect_marker
from .adapters._google import RESOURCE_ID
from .adapters.calendar_write import CalendarWriteAdapter
from .adapters.meeting_host import ApprovalBoundBroker
from .errors import OutboxRefused
from .outbox import Outbox
from .store import InMemoryOutboxStore

_log = logging.getLogger(__name__)
_KINDS = frozenset({"email", "file", "calendar_event"})


class Reach:
    """Counts requests that went out to Google: after a failure, `possibly_sent` is whether any did."""

    def __init__(self, transport: Any) -> None:
        self._transport, self.sent = transport, 0

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.sent += 1
        return self._transport.request(*args, **kwargs)


class _Documents:
    """The adapters' `ArtifactSource`: the documents this request carried, already hash-checked (HB-03)."""

    def __init__(self, documents: dict[tuple[str, int], dict[str, Any]]) -> None:
        self._documents = documents

    def get(self, artifact_id: str, version: int) -> dict[str, Any]:
        try:
            return self._documents[(artifact_id, version)]
        except KeyError:
            raise KeyError("not this request's item") from None


def checked_documents(entry: Mapping[str, Any], items: list[Mapping[str, Any]]) -> _Documents | None:
    """HB-03: the entry's item then its attachments, in order; each one's ids equal the entry's, its bytes match their
    hash and parse as a document of a known kind. Anything else is None (the caller answers `refused`, nothing sent)."""
    refs = [entry["item"], *entry["attachments"]]
    if len(items) != len(refs):
        return None
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for ref, item in zip(refs, items, strict=True):
        key = (ref["artifact_id"], ref["version"])
        try:
            raw = base64.b64decode(item["content_b64"], validate=True)
            if (item["artifact_id"], item["version"]) != key or hashlib.sha256(raw).hexdigest() != item[
                "content_sha256"
            ]:
                return None
            document = json.loads(raw)
            if not isinstance(document, dict) or document.get("kind") not in _KINDS:
                return None
            if document["kind"] == "file":  # the bytes travel inside the document, so name and type are pinned too
                document = {**document, "content": base64.b64decode(document.pop("content_b64"), validate=True)}
        except (binascii.Error, ValueError, KeyError, AttributeError, TypeError, RecursionError):
            return None
        out[key] = document
    return _Documents(out)


def execute(
    body: Mapping[str, Any],
    documents: _Documents,
    *,
    declaration: Mapping[str, Any],
    broker: Any,
    transport: Any,
    stopped: Callable[[str], bool],
    emit: Callable[[dict[str, Any]], None],
    clock: Callable[[], str],
) -> dict[str, Any]:
    """Runs the entry. The caller has captured the parts (`emit` feeds them) and checked the items."""
    entry, evidence = body["entry"], body["evidence"]
    owner, reach = evidence["world_owner"], Reach(transport)
    results: list[Mapping[str, Any]] = []
    alerted: list[dict[str, Any]] = []
    common: dict[str, Any] = {
        "declaration": declaration,
        "broker": ApprovalBoundBroker(broker, approved_at=entry["authz"]["at"], stopped=stopped),
        "transport": reach,
        "artifacts": documents,
        "owner_of": lambda world_id: owner,  # the grant used is the world owner's
        "clock": clock,
        "emit": emit,
        "sleep": lambda seconds: None,
    }
    adapters: dict[str, Callable[[], Any]] = {
        "gmail": lambda: GmailAdapter(**common),
        "google_drive": lambda: DriveAdapter(picks=InMemoryPicks(), **common),
        "google_calendar": lambda: CalendarWriteAdapter(**common),
    }
    adapter = adapters[entry["connector"]]()
    adapter.on_result = results.append
    store = InMemoryOutboxStore()  # HB-04: nothing outlives the request; a retry reads Google's earlier effect
    outbox = Outbox(store, {entry["connector"]: adapter}, emit=lambda part: None, clock=clock,
                    world_id=entry["world_id"], alert=alerted.append)  # fmt: skip
    try:
        outbox.enqueue(dict(entry), dict(evidence))
    except OutboxRefused:
        return answer("refused")
    try:  # from here on Google may have been reached: no exit may say "not configured" (a final refusal)
        outbox.dispatch_due()
        settled = outbox.get(entry["id"]) or {}
        ambiguous = bool(store.retry_state(entry["id"])["ambiguous"])
        done = _outcome(settled, results, bool(alerted), ambiguous, entry)
        if not host_rpc_validator("execute_answer").is_valid(done):
            raise ValueError("the answer breaks its contract")
        return done
    except Exception as exc:  # noqa: BLE001 - the type only
        _log.error("an execute failed after dispatch began (%s)", type(exc).__name__)
        return answer("possibly_sent") if reach.sent else answer("retry", may_have_sent=False)


def _outcome(
    settled: Mapping[str, Any],
    results: list[Mapping[str, Any]],
    alerted: bool,
    ambiguous: bool,
    entry: Mapping[str, Any],
) -> dict[str, Any]:
    state = settled.get("state")
    if (
        state == "sent"
    ):  # LC-08: result is Google's own id and Tilo's marker; no id Google can use means a person checks
        resource_id = results[0].get("id") if results else None
        if isinstance(resource_id, str) and RESOURCE_ID.fullmatch(resource_id):
            return answer("sent", result={"resource_id": resource_id, "marker": side_effect_marker(entry)})
        return answer("possibly_sent")
    if state == "failed":
        return answer("possibly_sent" if alerted else "refused")
    return answer("retry", may_have_sent=ambiguous)  # the outbox's own record: only a refusal proves nothing went out


def answer(outcome: str, *, result: dict[str, str] | None = None, may_have_sent: bool | None = None) -> dict[str, Any]:
    return {"outcome": outcome, "result": result, "may_have_sent": may_have_sent, "parts": []}
