"""The production plate mailer: the FR-CHN-18 sender's four adapters and the PlateMailer built from them (FR-CHN-18b,
FR-PA-06c; PE-09, PE-12, PE-20, PE-26 to PE-30; SEC-03, SEC-08; PRD 10.4, 11.6).

One person's plate goes out through `PlateDigestService` and the `DigestService` it wraps, with these seams:

- policy: `StorePolicies` reads the person's own `send_email` policies from the API store and lets the engine see only
  those that are L3, undo 0 and pinned to exactly their own mailbox (`scope.recipients == [address]`); caps count the
  owner's `policy.applied` in every world (PI-11). No such policy: nothing is built, stored or sent.
- artifact: `DeskArtifacts` stores the mail as the L5 `email` document in the person's own Desk world (never a shared
  world: the body holds personal titles and live bearer links, and is stored before the policy decision).
- mailbox: the person's own record's address, resolved here, never from a caller or a plate.
- emit: the person's Desk world, `vis: []` (PE-12), through the single event writer.

A send is dispatched in the same call: the live Gmail stub holds the evidence in memory for one request only (it
`needs_run`, so the Scheduler's outbox sweep skips it), which is why the policy must have no undo window. An entry the
call could not send is abandoned so it never goes out later with no evidence; one that may have gone out stays, with
one `alert.raised`. A mail reply is never read. Nothing here logs a title, an address, a link or an exception text.
"""

from __future__ import annotations

import copy
import hashlib
import logging
from collections.abc import Callable, Mapping
from typing import Any

import tilo_policy
from tilo_channels.autopilot_state import Outbox as OutboxPort
from tilo_channels.digest import DigestService
from tilo_channels.plate_digest import PlateDigestBuilder, PlateDigestService
from tilo_connectors import Outbox, OutboxRefused, RetryPolicy
from tilo_memory.artifacts import ArtifactStore, NewVersion, Origin, Scope
from tilo_policy.schemas import conforms

from tilo_api import deps, events, item_documents

logger = logging.getLogger("tilo_api.plate_mailer")

CONNECTOR = "gmail"
_UNSENT = ("queued", "scheduled", "sending")
_KIND_INDEX = {"digest": 0, "plate_digest": 1, "plate_reminder": 2}  # the key's last digit of one artifact


class NotConfigured(Exception):
    """A seam the send needs is missing: nothing was built or sent."""


# -- policy ----------------------------------------------------------------------------------------------------------


def _pinned(policy: Any, owner: str, address: str) -> bool:
    """A standing rule this mail may run under: the person's own, L3, `send_email`, no undo window (the entry is sent in
    the call that makes it), Gmail only, and scope.recipients exactly their own address."""
    if not isinstance(policy, dict) or policy.get("owner") != owner or policy.get("action_type") != "send_email":
        return False
    scope = policy.get("scope")
    return (
        policy.get("level") == "L3"
        and policy.get("undo_window_s") == 0
        and isinstance(scope, dict)
        and scope.get("recipients") == [address]
        and scope.get("connectors") == [CONNECTOR]
        and scope.get("domains") == []
    )


class StorePolicies:
    """`DigestPolicyPort` over the API store's policies and the owner's own `policy.applied` events."""

    def __init__(self, store: deps.Store, table: tilo_policy.RiskTable, *, owner: str, address: str, now: str) -> None:
        self._store, self._table, self._owner, self._address, self._now = store, table, owner, address, now

    def eligible(self) -> list[dict[str, Any]]:
        self._store.load_owner(self._owner)
        return [
            copy.deepcopy(p)
            for p in list(self._store.policies.values())
            if _pinned(p, self._owner, self._address) and conforms("policy.schema.json", p)
        ]

    def _applied(self) -> list[dict[str, Any]]:
        worlds = [w for w, record in list(self._store.worlds.items()) if record.owner == self._owner]
        return [e for w in worlds for e in self._store.events.get(w, []) if e.get("type") == "policy.applied"]

    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
        if user_id != self._owner:
            raise PermissionError("not the owner")
        return tilo_policy.decide(
            proposal, table=self._table, policies=self.eligible(), world_owner=user_id, applied=self._applied(),
            now=self._now,
        )  # fmt: skip

    def policy_for(self, user_id: str, policy_id: str) -> Mapping[str, Any] | None:
        if user_id != self._owner:
            return None
        return next((p for p in self.eligible() if p["id"] == policy_id), None)


# -- artifact --------------------------------------------------------------------------------------------------------


class DeskArtifacts:
    """`DigestArtifactPort`: the mail as an `email` document in the person's Desk world (origin unit, so the store
    keeps it with its hash and pinned version). The store keys the version by what the caller asked for, so a retry of
    the same call gets the first bytes back."""

    def __init__(self, artifacts: ArtifactStore, scope: Scope, run_id: str) -> None:
        self._artifacts, self._scope, self._run_id = artifacts, scope, run_id

    def store(self, artifact_id: str, subject: str, body_text: str, version: int = 1) -> dict[str, Any]:
        raw = item_documents.build_document(
            "send_email", {"subject": subject}, body=body_text.encode("utf-8"), media_type="text/plain"
        )
        if not isinstance(raw, bytes):
            raise ValueError("the digest document is incomplete")
        n = int.from_bytes(hashlib.sha256(artifact_id.encode()).digest()[:8], "big")
        kind = next((k for k in _KIND_INDEX if artifact_id.startswith(f"art_{k}_")), "digest")
        unit, attempt = f"U{n % 9999 + 1}", (n // 9999) % 10_000
        key = f"{self._run_id}:{unit}:{attempt}:{_KIND_INDEX[kind]}"
        new = NewVersion(
            "application/json", raw, self._run_id, Origin(kind="unit", unit=unit, agent="A_digest"),
            idempotency_key=key,
        )  # fmt: skip
        return {"artifact_id": (put := self._artifacts.put(self._scope, new)).artifact_id, "version": put.version}

    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        import json  # noqa: PLC0415

        return dict(json.loads(self._artifacts.read(self._scope, {"artifact_id": artifact_id, "version": version})))


# -- events ----------------------------------------------------------------------------------------------------------


class DeskEvents:
    """Parts into the person's Desk world through the single writer: owner-only (`vis: []`, PE-12), ids and enums."""

    def __init__(self, writer: deps.EventWriter, world_id: str) -> None:
        self._writer, self._world = writer, world_id

    def applied(self, part: Mapping[str, Any]) -> None:
        data = part["data"]
        self._writer.append(
            self._world,
            {
                "id": events.stable_part_id("policy.applied", data["outbox_id"]), "type": "policy.applied",
                "actor": data["policy_id"], "target": self._world, "summary": "A standing rule mailed your plate.",
                "vis": [], "authz": copy.deepcopy(part["authz"]), "data": copy.deepcopy(data),
            },
        )  # fmt: skip

    def transfer(self, part: Mapping[str, Any]) -> None:
        data = part["data"]
        self._writer.append(
            self._world,
            {
                "id": events.stable_part_id("data.transfer", str(data["outbox_id"])), "type": "data.transfer",
                "actor": part["authz"]["ref"], "target": self._world, "summary": "Your plate was mailed to you.",
                "vis": [], "authz": copy.deepcopy(part["authz"]), "data": copy.deepcopy(data),
            },
        )  # fmt: skip

    def alert(self, part: Mapping[str, Any]) -> None:
        alert_id = part["data"]["alert_id"]
        self._writer.append(
            self._world,
            {
                "id": events.stable_part_id("alert.raised", alert_id), "type": "alert.raised", "actor": "system",
                "target": self._world, "summary": "A person must check whether the item went out.", "vis": [],
                "severity": "needs_you", "authz": None, "data": {"alert_id": alert_id, "card_id": None},
            },
        )  # fmt: skip


class _EvidenceOutbox:
    """The outbox the sender enqueues through: the live stub is handed the case the enqueue checked first (HB-04)."""

    def __init__(self, inner: OutboxPort, stub: Any) -> None:
        self._inner, self._stub = inner, stub

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        self._stub.hand_evidence(entry["id"], evidence)
        return self._inner.enqueue(entry, evidence)

    def cancel(self, outbox_id: str) -> dict:
        return self._inner.cancel(outbox_id)

    def abandon(self, outbox_id: str) -> dict:
        return self._inner.abandon(outbox_id)

    def get(self, outbox_id: str) -> dict | None:
        return self._inner.get(outbox_id)

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        return self._inner.get_by_idempotency_key(world_id, idempotency_key)

    def revoke(self, world_id: str, idempotency_key: str) -> dict | None:
        return self._inner.revoke(world_id, idempotency_key)


# -- the mailer ------------------------------------------------------------------------------------------------------


class DeskPlateMailer:
    """`plate_links.PlateMailer`: sends one person's plate to their own mailbox once per UTC day."""

    def __init__(
        self,
        *,
        store: deps.Store,
        people: Any,
        desks: deps.DeskWorlds,
        writer: deps.EventWriter,
        artifacts: ArtifactStore,
        outbox_store: Any,
        gmail: Any,
        builder: PlateDigestBuilder,
        table: tilo_policy.RiskTable,
    ) -> None:
        self._store, self._people, self._desks, self._writer = store, people, desks, writer
        self._artifacts, self._outbox_store, self._gmail = artifacts, outbox_store, gmail
        self._builder, self._table = builder, table

    def _address(self, user_id: str) -> str | None:
        found = self._people.persons.get(deps.ORG_ID, user_id)
        email = None if found is None else found.record.get("email")
        return email if isinstance(email, str) and conforms("common.schema.json#/$defs/email_address", email) else None

    def deliver(self, user_id: str, plate: dict[str, Any], *, now: str) -> bool:
        try:
            return self._deliver(user_id, plate, now)
        except Exception as exc:  # whatever fails sends nothing more; the type only (no title, address or link)
            logger.warning("plate mail not sent (%s)", type(exc).__name__)
            return False

    def _deliver(self, user_id: str, plate: dict[str, Any], now: str) -> bool:
        address = self._address(user_id)
        if address is None:
            return False
        policies = StorePolicies(self._store, self._table, owner=user_id, address=address, now=now)
        if not policies.eligible():  # nothing is built, stored or sent for a person with no such standing rule
            return False
        world_id = self._desks.desk_world(deps.ORG_ID, user_id)
        record = self._store.load_world(world_id)
        if record is None or record.owner != user_id or self._desks.desk_owner(world_id) != user_id or record.paused:
            return False
        scope = Scope(org_id=deps.ORG_ID, world_id=world_id, owner=user_id)
        desk = DeskEvents(self._writer, world_id)
        bound = self._gmail.bound(lambda ref: bytes(self._artifacts.read(scope, ref)), lambda part: None, user_id)

        def halted() -> bool:  # asked at each claim: a paused or unreadable world sends nothing (FR-WLD-07)
            held = self._store.load_world(world_id)
            return held is None or held.paused

        outbox = Outbox(
            self._outbox_store, {CONNECTOR: bound}, emit=desk.transfer, clock=lambda: now, world_id=world_id,
            halted=halted, alert=desk.alert, retry=RetryPolicy(),
        )  # fmt: skip
        sender = DigestService(
            builder=self._builder.daily_builder(), outbox=_EvidenceOutbox(outbox, bound), policy=policies,
            artifacts=DeskArtifacts(self._artifacts, scope, record.run_id), emit=desk.applied,
            mailbox=lambda uid: self._address(uid) if uid == user_id else None, world_id=world_id,
            world_owner=user_id, run_id=record.run_id,
        )  # fmt: skip
        entry = PlateDigestService(builder=self._builder, sender=sender).deliver_if_non_empty(
            user_id=user_id, plate=plate, kind="digest", now=now
        )
        if entry is None:
            return False
        outbox.dispatch_due()
        return self._settle(outbox, desk, entry["id"])

    def _settle(self, outbox: Outbox, desk: DeskEvents, outbox_id: str) -> bool:
        """True when it went out. Unsent after this call's one dispatch: abandoned (it never goes out later with no
        evidence), unless it may have gone out, which stays and is told to a person once."""
        now = self._outbox_store.get(outbox_id)
        if now is None or now["state"] == "sent":
            return now is not None
        if now["state"] not in _UNSENT:
            return False
        ambiguous = bool(self._outbox_store.retry_state(outbox_id).get("ambiguous"))
        try:
            outbox.abandon(outbox_id, keep_ambiguous=True)
        except OutboxRefused:
            ambiguous = True  # a lease nobody released, or a send in flight: a person checks
        if ambiguous:
            desk.alert({"data": {"alert_id": outbox_id}})
        return False


def production_mailer(overrides: Mapping[Any, Any]) -> DeskPlateMailer:
    """Resolves every seam the way the tick does (the process's own, never a demo session's) and refuses, as
    `NotConfigured`, when one is missing: no signing key, no store, no Gmail connector."""
    from tilo_api import plate_links  # noqa: PLC0415

    def seam(fn: Callable[..., Any]) -> Any:
        return overrides.get(fn, fn)()

    gmail = seam(deps.get_connector_adapters).get(CONNECTOR)
    if gmail is None or not hasattr(gmail, "bound") or not hasattr(gmail, "hand_evidence"):
        raise NotConfigured("no live Gmail connector")
    return DeskPlateMailer(
        store=seam(deps.get_store), people=seam(deps.get_people_stores), desks=seam(deps.get_desk_worlds),
        writer=seam(deps.get_event_writer), artifacts=seam(deps.get_artifact_store),
        outbox_store=seam(deps.get_outbox_store), gmail=gmail, builder=seam(plate_links.get_link_builder),
        table=tilo_policy.load_risk_table(),
    )  # fmt: skip
