"""CL-LIVE-2: the typed-approval gate for real connector writes (API_CL_LIVE_2.md).

A write reaches Google only when a PERSON typed `yes` at an interactive terminal for exactly the payload the outbox
then executes. `WriteGate.review(card)` turns a gate card into the payload (recipients, destination, subject, a bounded
redacted preview) and its digest; `approve` records a typed yes against that digest; `authorise` is called by the write
door the outbox reaches: it re-reads the content, recomputes the digest and refuses unless that digest was approved,
once, for this entry. Nothing here models authorisation: it checks a recorded human act. No logging; messages are fixed
text (no mail text, token or config value).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .errors import SideEffectRefused

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"  # requested only behind --allow-send
STAND_IN_DESTINATION = "thread-dev-1"  # the run's dev destination (tilo_api.dev_run): no real thread, no real folder
WRITE_ACTIONS: Mapping[str, tuple[str, ...]] = {
    "gmail": ("create_draft",),
    "google_drive": ("save_file", "save_as_google_file"),
}
SEND_ACTIONS: Mapping[str, tuple[str, ...]] = {"gmail": ("send_email",)}
KINDS: Mapping[str, str] = {"gmail": "email", "google_drive": "file"}  # the artifact kind each adapter reads
SUBJECT_CHARS, PREVIEW_CHARS = 120, 300
_REFUSALS = {
    "not_bound": "real writes are not bound to this run's content",
    "action_off": "this write is not enabled for this run",
    "not_a_person": "a real write needs a person's approval",
    "content_unavailable": "the content to write cannot be read",
    "no_approval": "no typed terminal approval for exactly this payload",
    "approval_spent": "the typed approval was already used for another entry",
    "attachments_off": "attachments are not enabled for real writes",
}


class WriteRefused(SideEffectRefused):
    """Final for the outbox: the entry fails and nothing was sent. `.code` says why; the text is fixed."""

    def __init__(self, code: str) -> None:
        super().__init__(_REFUSALS[code])
        self.code = code


@dataclass(frozen=True)
class WriteFlags:
    allow_writes: bool = False
    allow_send: bool = False

    def __post_init__(self) -> None:
        if self.allow_send and not self.allow_writes:
            raise ValueError("send needs writes")

    @property
    def mode(self) -> str:  # what the report says
        return (
            "real_write_gated_send"
            if self.allow_send
            else "real_write_gated"
            if self.allow_writes
            else "real_read_only"
        )

    def actions(self, connector: str) -> tuple[str, ...]:
        if not self.allow_writes:
            return ()
        return (*WRITE_ACTIONS.get(connector, ()), *(SEND_ACTIONS.get(connector, ()) if self.allow_send else ()))


@dataclass(frozen=True)
class Review:
    """What the person is shown: from the send itself, never from a model. `allowed` False: the gate holds it."""

    allowed: bool
    why: str
    connector: str
    action: str
    recipients: tuple[str, ...]
    destination: str
    title: str
    preview: str
    size: int
    digest: str


@dataclass
class _Approval:
    key: str | None = None  # the idempotency key it was spent on
    result: dict[str, Any] | None = None


@dataclass(frozen=True)
class Authorised:
    content: Mapping[str, Any]
    entry: dict[str, Any]  # what the adapter gets: the stand-in destination means "no thread / the Tilo folder"
    done: dict[str, Any] | None  # the result of an earlier success of this entry: no second request


def effective_destination(destination: Any) -> Any:
    return None if destination == STAND_IN_DESTINATION else destination


def _digest(world_id: Any, connector: Any, action: Any, recipients: Any, destination: Any, ref: Mapping[str, Any],
            content: Mapping[str, Any]) -> str:  # fmt: skip
    body = {k: v for k, v in content.items() if k != "content"}
    if "content" in content:
        body["sha256"] = hashlib.sha256(bytes(content["content"])).hexdigest()
    payload = [world_id, connector, action, list(recipients), effective_destination(destination),
               ref.get("artifact_id"), ref.get("version"), body]  # fmt: skip
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _ref(item: Any) -> dict[str, Any]:
    return {"artifact_id": item["artifact_id"], "version": item["version"]}


class WriteGate:
    def __init__(self, flags: WriteFlags) -> None:
        self.flags = flags
        self._resolve: Callable[[str, Mapping[str, Any], str], Mapping[str, Any]] | None = None
        self._redact: Callable[[str], str] | None = None
        self._approved: dict[str, _Approval] = {}
        self._lock = threading.RLock()
        self.executed: list[str] = []  # the action of each write that went out: counts, never content

    def bind(
        self, resolve: Callable[[str, Mapping[str, Any], str], Mapping[str, Any]], redact: Callable[[str], str]
    ) -> None:
        """The run supplies how to read an item (world_id, {artifact_id, version}, kind) and the secret redactor."""
        self._resolve, self._redact = resolve, redact

    def review(self, card: Mapping[str, Any]) -> Review | None:
        """None: not a connector write this gate covers. Otherwise the payload and its digest (or why it is held)."""
        gate = card.get("gate") or {}
        action = gate.get("action") or {}
        connector, kind = str(action.get("connector")), str(action.get("type"))
        if kind not in (*WRITE_ACTIONS.get(connector, ()), *SEND_ACTIONS.get(connector, ())):
            return None
        recipients = tuple(str(r) for r in gate.get("recipients") or ())
        destination = str(action.get("destination"))
        blank = Review(False, "", connector, kind, recipients, destination, "", "", 0, "")
        if kind not in self.flags.actions(connector):
            return _held(blank, "action_off")
        try:
            if self._resolve is None or self._redact is None:
                raise WriteRefused("not_bound")
            ref = _ref(action["item"])
            content = self._resolve(str(card["world_id"]), ref, KINDS[connector])
            digest = _digest(card["world_id"], connector, kind, recipients, destination, ref, content)
        except WriteRefused as refusal:
            return _held(blank, refusal.code)
        except Exception:  # noqa: BLE001 - fixed text only
            return _held(blank, "content_unavailable")
        title, text = _shown(content)
        redact = self._redact
        where = effective_destination(destination) or (
            "no thread: a new message" if connector == "gmail" else "the Tilo folder"
        )
        return Review(True, "", connector, kind, recipients, str(where),
                      redact(title)[:SUBJECT_CHARS], redact(text)[:PREVIEW_CHARS], len(text), digest)  # fmt: skip

    def approve(self, review: Review, *, said: str, interactive: bool) -> bool:
        """Records a typed `yes` from an interactive terminal against the payload's digest; anything else is a no."""
        if not (review.allowed and interactive and said.strip().lower() == "yes"):
            return False
        with self._lock:
            if (current := self._approved.get(review.digest)) is None or current.result is not None:
                self._approved[review.digest] = _Approval()  # a spent approval never covers a second send
        return True

    def authorise(self, entry: Mapping[str, Any], connector: str) -> Authorised:
        """Called by a write door the outbox reached: re-reads the content, checks it is exactly what was approved."""
        action = str(entry.get("action_type"))
        if action not in self.flags.actions(connector):
            raise WriteRefused("action_off")
        if (entry.get("authz") or {}).get("by") != "person":
            raise WriteRefused("not_a_person")
        if entry.get("attachments"):
            raise WriteRefused("attachments_off")  # the digest would not cover them: v1 writes carry none
        if self._resolve is None:
            raise WriteRefused("not_bound")
        try:
            ref = _ref(entry["item"])
            content = self._resolve(str(entry["world_id"]), ref, KINDS[connector])
            digest = _digest(entry["world_id"], connector, action, entry.get("recipients") or (),
                             entry.get("destination"), ref, content)  # fmt: skip
        except Exception:  # noqa: BLE001 - fixed text only
            raise WriteRefused("content_unavailable") from None
        with self._lock:
            approval = self._approved.get(digest)
            if approval is None:
                raise WriteRefused("no_approval")
            key = str(entry.get("idempotency_key"))
            if approval.key not in (None, key):
                raise WriteRefused("approval_spent")
            approval.key = key
            adapter_entry = deepcopy(dict(entry))
            adapter_entry["destination"] = effective_destination(adapter_entry.get("destination"))
            return Authorised(deepcopy(dict(content)), adapter_entry, deepcopy(approval.result))

    def complete(self, entry: Mapping[str, Any], connector: str, result: dict[str, Any]) -> None:
        """The write went out: later calls for this entry return `result` and send nothing."""
        action = str(entry.get("action_type"))
        with self._lock:
            for approval in self._approved.values():
                if approval.key == str(entry.get("idempotency_key")) and approval.result is None:
                    approval.result = deepcopy(dict(result))
            self.executed.append(f"{connector}.{action}")

    @property
    def lock(self) -> threading.RLock:
        return self._lock


def _held(blank: Review, code: str) -> Review:
    return dataclasses.replace(blank, why=_REFUSALS[code])


def _shown(content: Mapping[str, Any]) -> tuple[str, str]:
    """(title, text) of an item for the card: an email's subject and body, a file's name and its text if it is text."""
    if "body_text" in content:
        return str(content.get("subject", "")), str(content["body_text"])
    data = bytes(content.get("content") or b"")
    mime = str(content.get("mime_type", ""))
    text = (
        data.decode("utf-8", "replace")
        if mime.startswith("text/") or mime == "application/json"
        else f"(binary, {len(data)} bytes)"
    )
    return str(content.get("name", "")), text


def write_plan(rows: list[dict[str, Any]], flags: WriteFlags) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """The dry-run plan: the read plan's rows with write modes (and the send scope), and each gated write."""
    out = []
    for row in rows:
        gated = flags.actions(row["connector"])
        scopes = (*row["scopes"], *((SEND_SCOPE,) if row["connector"] == "gmail" and flags.allow_send else ()))
        mode = "read_only" if not gated else "write_gated_send" if "send_email" in gated else "write_gated"
        out.append({**row, "scopes": scopes, "mode": mode})
    return out, [(c, a) for c in WRITE_ACTIONS for a in flags.actions(c)]
