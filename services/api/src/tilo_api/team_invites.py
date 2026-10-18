"""A team invitation sent through the existing person-approved T2 Gmail outbox path."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from tilo_connectors import Outbox
from tilo_memory.artifacts import NewVersion, Origin, Scope

from tilo_api import deps, events, item_documents


class InviteNotSent(Exception):
    """The invitation could not be confirmed as sent."""


def _trace() -> dict[str, Any]:
    return {
        "model_role": None,
        "profile": None,
        "tokens_in": None,
        "tokens_out": None,
        "tool": None,
        "latency_ms": None,
        "archive_ref": None,
    }


def _evidence(*, owner: str, world: str, run: str, at: str, item: dict[str, Any], outbox_id: str) -> dict[str, Any]:
    gate_id, card_id = "G1", events.new_part_id()
    authz = {"by": "person", "ref": owner, "at": at}
    requested = {
        "v": "1.0",
        "id": events.new_part_id(),
        "seq": 1,
        "ts": at,
        "world_id": world,
        "run_id": run,
        "type": "approval.requested",
        "actor": "A_team",
        "target": gate_id,
        "level": "L1",
        "district": "D1",
        "item": {"kind": "document", "artifact_id": item["artifact_id"], "label": "Team invitation"},
        "severity": "gate",
        "credits": 0,
        "summary": "Sending the team invitation needs your approval.",
        "cause": events.new_part_id(),
        "vis": "all",
        "authz": None,
        "data": {
            "gate_id": gate_id,
            "card_id": card_id,
            "outbox_id": outbox_id,
            "action_type": "send_email",
            "risk_tier": "T2",
            "irreversible": True,
            "item": item,
            "approver": None,
            "team_lead": None,
        },
        "trace": _trace(),
    }
    resolved = {
        **copy.deepcopy(requested),
        "id": events.new_part_id(),
        "seq": 2,
        "type": "approval.resolved",
        "actor": owner,
        "item": None,
        "severity": "info",
        "summary": "You approved sending the team invitation.",
        "cause": requested["id"],
        "authz": authz,
        "data": {
            "gate_id": gate_id,
            "card_id": card_id,
            "outbox_id": outbox_id,
            "option": "approve",
            "channel": "web",
            "pin_verified": False,
        },
    }
    return {
        "reserved_by": requested,
        "authorised_by": resolved,
        "world_owner": owner,
        "policy": None,
        "team_lead": None,
        "instruction": None,
        "earlier_applied": [],
    }


def send_team_invite(
    *,
    owner: str,
    email: str,
    role: str,
    team_name: str,
    invite_id: str,
    at: str,
    artifacts: Any,
    outbox_store: Any,
    adapters: Mapping[str, Any],
    desks: Any,
    writer: Any,
) -> str:
    """Store the approved mail, enqueue it with person authz, and confirm the one outbox dispatch."""
    adapter = adapters.get("gmail")
    if adapter is None:
        raise InviteNotSent("gmail is not connected")
    world = desks.desk_world(deps.ORG_ID, owner)
    if not isinstance(world, str) or not world:
        raise InviteNotSent("the owner's Desk is unavailable")
    run = f"r_team_invite_{invite_id.removeprefix('inv_')}"
    scope = Scope(deps.ORG_ID, world, owner)
    body = (
        f"You've been invited to {team_name} on Tilo as {role}.\n\n"
        "Sign in to Tilo with this email address to join the team."
    ).encode()
    document = item_documents.build_document(
        "send_email", {"subject": f"You're invited to {team_name} on Tilo"}, body=body, media_type="text/plain"
    )
    if not isinstance(document, bytes):
        raise InviteNotSent("the invitation document is incomplete")
    stored = artifacts.put(
        scope,
        NewVersion(
            "application/json",
            document,
            run,
            Origin(kind="unit", unit="U1", agent="A_team"),
            idempotency_key=f"{run}:U1:0:0",
            label="Team invitation",
        ),
    )
    item, outbox_id = stored.ref, events.new_part_id()
    evidence = _evidence(owner=owner, world=world, run=run, at=at, item=item, outbox_id=outbox_id)
    authz = copy.deepcopy(evidence["authorised_by"]["authz"])
    entry = {
        "id": outbox_id,
        "idempotency_key": f"{run}:U1:send_email:1",
        "world_id": world,
        "run_id": run,
        "action_type": "send_email",
        "connector": "gmail",
        "recipients": [email],
        "attachments": [],
        "item": item,
        "destination": None,
        "modifiers": [],
        "risk_tier": "T2",
        "authz": authz,
        "undo_window_s": 0,
        "scheduled_at": at,
        "state": "queued",
        "created_at": at,
    }

    def emit(part: dict[str, Any]) -> None:
        data = copy.deepcopy(part["data"])
        writer.append(
            world,
            {
                "id": events.stable_part_id(part["type"], outbox_id),
                "type": part["type"],
                "actor": owner,
                "target": world,
                "summary": "The team invitation was sent.",
                "vis": [],
                "authz": copy.deepcopy(part.get("authz")),
                "data": data,
            },
        )

    bound = (
        adapter.bound(lambda ref: bytes(artifacts.read(scope, ref)), lambda _part: None, owner)
        if callable(getattr(adapter, "bound", None))
        else adapter
    )
    hand = getattr(bound, "hand_evidence", None)
    if callable(hand):
        hand(outbox_id, evidence)
    outbox = Outbox(outbox_store, {"gmail": bound}, emit=emit, clock=lambda: at, world_id=world)
    try:
        outbox.enqueue(entry, evidence)
        outbox.dispatch_due()
    except Exception as exc:
        raise InviteNotSent("the approved invitation was not sent") from exc
    sent = outbox_store.get(outbox_id)
    if sent is None or sent.get("state") != "sent":
        raise InviteNotSent("the approved invitation was not confirmed")
    return outbox_id


def production_sender(
    *,
    artifacts: Any,
    outbox_store: Any,
    adapters: Mapping[str, Any],
    desks: Any,
    writer: Any,
) -> Callable[..., str]:
    return lambda **fields: send_team_invite(
        artifacts=artifacts,
        outbox_store=outbox_store,
        adapters=adapters,
        desks=desks,
        writer=writer,
        **fields,
    )
