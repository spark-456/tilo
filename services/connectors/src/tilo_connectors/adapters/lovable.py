"""LovableLinkAdapter: the Lovable "Build with URL" route (FR-CON-17, PRD supplement 2026-10-05 s6).

The prompt rides in the link's fragment, percent-encoded; the person opens the link and presses send in Lovable.
No key, no Tilo token, and no call to Lovable from here: this module takes no transport and imports no network
module (the tests check it by AST and with blocked sockets). The one side effect is storing the link, from the
outbox only (SEC-03). The URL lives in the stored link record and nowhere else: never in an event, an error or a
log line. Pinned API: services/connectors/tests/API_FR_CON_16_17_20.md.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import quote, unquote

from ..errors import HandoffRefused, MissingGrant, SideEffectRefused
from ..outbox import Grant

if TYPE_CHECKING:
    from ..grants import GrantStore, TextArtifacts
    from ..handoff import BuildPartnerConfig, HandoffStore

LOVABLE_LINK_PREFIX = "https://lovable.dev/#prompt="
# What `quote(..., safe="")` emits, plus the other printable ASCII a value may hold; never "#", "&", "?" or a bare "%".
_VALUE = re.compile(r"(?:%[0-9A-Fa-f]{2}|[\x21\x22\x24\x27-\x3e\x40-\x7e])*")


def link_length(prompt: str) -> int:
    return len(LOVABLE_LINK_PREFIX) + len(quote(prompt, safe=""))


def decode_link(url: str) -> str:
    """The prompt a link carries. ValueError unless `url` is the prefix plus one percent-encoded value."""
    if not url.startswith(LOVABLE_LINK_PREFIX):
        raise ValueError("not a Lovable build link")
    value = url[len(LOVABLE_LINK_PREFIX) :]
    if not _VALUE.fullmatch(value):
        raise ValueError("the link value is not one percent-encoded value")
    return unquote(value, errors="strict")


def _link(prompt: str) -> str:  # the only place a link is made
    return LOVABLE_LINK_PREFIX + quote(prompt, safe="")


@dataclass(frozen=True)
class LinkArtifact:
    world_id: str
    run_id: str
    unit_id: str
    agent_id: str
    idempotency_key: str  # the handoff record's link_idempotency_key (AR-05)
    media_type: str
    content: bytes


class LinkStore(Protocol):  # production: the artifact store bound to the world's scope, origin unit
    def put(self, link: LinkArtifact) -> dict[str, Any]: ...  # the same idempotency_key returns the same ref


class InMemoryLinkStore:
    """Dev and tests: one stored link per idempotency key."""

    def __init__(self) -> None:
        self._by_key: dict[str, tuple[LinkArtifact, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    @property
    def links(self) -> list[LinkArtifact]:
        with self._lock:
            return [link for link, _ in self._by_key.values()]

    def put(self, link: LinkArtifact) -> dict[str, Any]:
        with self._lock:
            if link.idempotency_key not in self._by_key:
                ref = {"artifact_id": f"art_link_{len(self._by_key) + 1}", "version": 1}
                self._by_key[link.idempotency_key] = (link, ref)
            return dict(self._by_key[link.idempotency_key][1])


class LovableLinkAdapter:
    def __init__(
        self,
        *,
        declaration: Mapping[str, Any],
        partner: BuildPartnerConfig,
        handoffs: HandoffStore,
        grants: GrantStore,
        artifacts: TextArtifacts,
        links: LinkStore,
    ) -> None:
        self._id = str(declaration["id"])
        self._partner = partner
        self._handoffs = handoffs
        self._grants = grants
        self._artifacts = artifacts
        self._links = links

    @property
    def id(self) -> str:
        return self._id

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        if not isinstance(grant, Grant):
            raise MissingGrant("grant not minted by Outbox.dispatch_due()")
        grant.verify(entry["idempotency_key"])
        record = self._checked_record(entry)
        if record.grant_id is not None:  # DG-03: a revoked or expired grant stops a handoff made under it
            try:
                self._grants.require_active(
                    record.grant_id, world_id=record.world_id, run_id=record.run_id, connector=self._id
                )
            except HandoffRefused as exc:
                raise SideEffectRefused(str(exc)) from None
        raw = self._artifacts.read(record.world_id, record.prompt)
        if hashlib.sha256(raw).hexdigest() != record.prompt_sha256:  # BH-07: sent = shown, byte for byte
            raise SideEffectRefused("BH-07: the stored prompt is not the prompt that was shown")
        try:
            prompt = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise SideEffectRefused("BH-07: the stored prompt is not UTF-8") from None
        url = _link(prompt)
        if len(prompt) > self._partner.max_prompt_chars or len(url) > self._partner.max_url_length:
            raise SideEffectRefused("BH-06: the prompt or its link is over the limit now in force")  # never cut
        content = json.dumps(
            {
                "v": "1.0",
                "partner": self._id,
                "route": "link",
                "url": url,
                "prompt": {"artifact_id": record.prompt["artifact_id"], "version": record.prompt["version"]},
                "outbox_id": entry["id"],
                "project_id": None,
                "status": "link_ready",
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        ref = self._links.put(
            LinkArtifact(
                world_id=record.world_id,
                run_id=record.run_id,
                unit_id=record.unit_id,
                agent_id=record.agent_id,
                idempotency_key=record.link_idempotency_key,
                media_type="application/json",
                content=content,
            )
        )
        return {"link": ref, "status": "link_ready"}

    def _checked_record(self, entry: Mapping[str, Any]) -> Any:  # BH-09: exactly a gated, recipientless handoff
        shaped = (
            entry.get("action_type") == self._partner.action
            and entry.get("connector") == self._id
            and entry.get("recipients") == []
            and entry.get("attachments") == []
            and entry.get("destination") is None
            and isinstance(entry.get("item"), Mapping)
            and entry.get("risk_tier") == "T3"
            and "external_sharing" in (entry.get("modifiers") or [])
        )
        if not shaped:
            raise SideEffectRefused("BH-09: the entry is not a recipientless, destinationless T3 build handoff")
        record = self._handoffs.get(entry["world_id"], entry["item"])
        if record is None or record.connector != self._id or record.run_id != entry.get("run_id"):
            raise SideEffectRefused("BH-09: the prompt did not go through prepare_handoff and record")
        return record
