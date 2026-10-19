"""A team invitation staged as an approval gate in the owner's Desk world, dispatched through Gmail upon approval."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Mapping
from typing import Any

from tilo_connectors import Outbox
from tilo_memory.artifacts import NewVersion, Origin, Scope

from tilo_api import deps, events, item_documents
from tilo_api.cards import CardStore

logger = logging.getLogger("tilo_api.team_invites")

_GATE_TIMEOUT_S = 86_400


class InviteNotSent(Exception):
    """The invitation could not be confirmed or staged."""


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


class _ClockAdapter:
    def __init__(self, clock: Any):
        self._clock = clock

    def now(self) -> str:
        if callable(self._clock):
            return self._clock()
        if hasattr(self._clock, "now"):
            return self._clock.now()
        return events.now()


class DeskRun:
    """A lightweight run state for a Desk world holding cards and wiring approvals to outbox dispatches."""

    def __init__(
        self,
        world_id: str,
        owner: str,
        *,
        clock: Any,
        writer: Any,
        outbox_store: Any,
        adapters: Mapping[str, Any],
        artifacts: Any,
    ):
        self.world_id = world_id
        self.owner = owner
        self.clock = clock
        self.writer = writer
        self.outbox_store = outbox_store
        self.adapters = adapters
        self.artifacts = artifacts
        self.pending_outbox: dict[str, dict[str, Any]] = {}
        self._clock_adapter = _ClockAdapter(clock)
        self.cards = CardStore(clock=self._clock_adapter, writer=self, world_owners={world_id: owner})

    def stage_outbox(self, card_id: str, outbox_id: str, entry: dict[str, Any], requested: dict[str, Any]) -> None:
        self.pending_outbox[card_id] = {
            "outbox_id": outbox_id,
            "entry": entry,
            "requested": requested,
        }

    def write(self, part: dict[str, Any]) -> None:
        if hasattr(self.writer, "append"):
            self.writer.append(self.world_id, part)
        elif hasattr(self.writer, "write"):
            self.writer.write(part)

        if part.get("type") == "approval.resolved":
            data = part.get("data", {})
            if data.get("option") == "approve":
                card_id = data.get("card_id")
                pending = self.pending_outbox.get(card_id)
                if pending is not None:
                    self._dispatch_approved(pending, part)

    def _dispatch_approved(self, pending: dict[str, Any], resolved_part: dict[str, Any]) -> None:
        entry = copy.deepcopy(pending["entry"])
        outbox_id = pending["outbox_id"]
        requested = pending["requested"]
        authz = copy.deepcopy(resolved_part.get("authz"))
        entry["authz"] = authz

        now_ts = self._clock_adapter.now()
        resolved_event = {
            "v": "1.0",
            "id": resolved_part.get("event_id") or events.new_part_id(),
            "seq": 2,
            "ts": now_ts,
            "world_id": self.world_id,
            "run_id": entry["run_id"],
            "type": "approval.resolved",
            "actor": self.owner,
            "target": resolved_part.get("data", {}).get("gate_id", "G1"),
            "level": "L1",
            "district": "D1",
            "item": None,
            "severity": "info",
            "credits": 0,
            "summary": "You approved sending the team invitation.",
            "cause": requested["id"],
            "vis": "all",
            "authz": authz,
            "data": {
                "gate_id": resolved_part.get("data", {}).get("gate_id", "G1"),
                "card_id": resolved_part.get("data", {}).get("card_id"),
                "outbox_id": outbox_id,
                "option": "approve",
                "channel": resolved_part.get("data", {}).get("channel", "web"),
                "pin_verified": False,
            },
            "trace": _trace(),
        }
        if hasattr(self.writer, "append"):
            self.writer.append(self.world_id, resolved_event)

        evidence = {
            "reserved_by": requested,
            "authorised_by": resolved_event,
            "world_owner": self.owner,
            "policy": None,
            "team_lead": None,
            "instruction": None,
            "earlier_applied": [],
        }

        adapter = self.adapters.get(entry["connector"])
        if adapter is None:
            logger.warning("connector %s unavailable on approval", entry["connector"])
            return

        scope = Scope(deps.ORG_ID, self.world_id, self.owner)
        bound = (
            adapter.bound(lambda ref: bytes(self.artifacts.read(scope, ref)), lambda _p: None, self.owner)
            if callable(getattr(adapter, "bound", None))
            else adapter
        )
        hand = getattr(bound, "hand_evidence", None)
        if callable(hand):
            hand(outbox_id, evidence)

        def emit(outbox_part: dict[str, Any]) -> None:
            part_data = copy.deepcopy(outbox_part["data"])
            if hasattr(self.writer, "append"):
                self.writer.append(
                    self.world_id,
                    {
                        "id": events.stable_part_id(outbox_part["type"], outbox_id),
                        "type": outbox_part["type"],
                        "actor": self.owner,
                        "target": self.world_id,
                        "summary": "The team invitation was sent.",
                        "vis": [],
                        "authz": copy.deepcopy(outbox_part.get("authz")),
                        "data": part_data,
                    },
                )

        outbox = Outbox(
            self.outbox_store,
            {entry["connector"]: bound},
            emit=emit,
            clock=lambda: now_ts,
            world_id=self.world_id,
        )
        outbox.enqueue(entry, evidence)
        outbox.dispatch_due()


def ensure_desk_run(
    api_store: Any,
    world: str,
    owner: str,
    *,
    clock: Any,
    writer: Any,
    outbox_store: Any,
    adapters: Mapping[str, Any],
    artifacts: Any,
) -> DeskRun:
    run = api_store.runs.get(world) if api_store is not None and hasattr(api_store, "runs") else None
    if isinstance(run, DeskRun):
        run.clock = clock
        run.writer = writer
        run.outbox_store = outbox_store
        run.adapters = adapters
        run.artifacts = artifacts
        return run
    desk_run = DeskRun(
        world,
        owner,
        clock=clock,
        writer=writer,
        outbox_store=outbox_store,
        adapters=adapters,
        artifacts=artifacts,
    )
    if api_store is not None and hasattr(api_store, "worlds"):
        if world not in api_store.worlds:
            api_store.worlds[world] = deps.WorldRecord(owner=owner, districts={}, run_id=f"r_{world}")
        if hasattr(api_store, "runs"):
            api_store.runs[world] = desk_run
    return desk_run


def stage_team_invite(
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
    api_store: Any = None,
    clock: Any = None,
) -> str:
    """Stage the team invitation as an approval gate in the owner's Desk world."""
    world = desks.desk_world(deps.ORG_ID, owner)
    if not isinstance(world, str) or not world:
        raise InviteNotSent("the owner's Desk is unavailable")

    run_id = f"r_team_invite_{invite_id.removeprefix('inv_')}"
    if api_store is None:
        try:
            api_store = deps.get_store()
        except Exception:
            api_store = None

    desk_run = ensure_desk_run(
        api_store,
        world,
        owner,
        clock=clock or (lambda: at),
        writer=writer,
        outbox_store=outbox_store,
        adapters=adapters,
        artifacts=artifacts,
    )

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
            run_id,
            Origin(kind="unit", unit="U1", agent="A_team"),
            idempotency_key=f"{run_id}:U1:0:0",
            label="Team invitation",
        ),
    )
    item, outbox_id, card_id, gate_id = stored.ref, events.new_part_id(), events.new_part_id(), "G1"

    requested = {
        "v": "1.0",
        "id": events.new_part_id(),
        "seq": 1,
        "ts": at,
        "world_id": world,
        "run_id": run_id,
        "type": "approval.requested",
        "actor": "A_team",
        "target": gate_id,
        "level": "L1",
        "district": "D1",
        "item": {"kind": "document", "artifact_id": item["artifact_id"], "label": "Team invitation"},
        "severity": "gate",
        "credits": 0,
        "summary": f"Sending the team invitation to {email} needs your approval.",
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
    if hasattr(writer, "append"):
        writer.append(world, requested)
    elif hasattr(writer, "write"):
        writer.write(requested)

    entry = {
        "id": outbox_id,
        "idempotency_key": f"{run_id}:U1:send_email:1",
        "world_id": world,
        "run_id": run_id,
        "action_type": "send_email",
        "connector": "gmail",
        "recipients": [email],
        "attachments": [],
        "item": item,
        "destination": None,
        "modifiers": [],
        "risk_tier": "T2",
        "authz": None,
        "undo_window_s": 0,
        "scheduled_at": at,
        "state": "queued",
        "created_at": at,
    }
    desk_run.stage_outbox(card_id, outbox_id, entry, requested)

    card = {
        "id": card_id,
        "world_id": world,
        "run_id": run_id,
        "kind": "gate",
        "rung": "gate",
        "header": {"building": "B1", "agent": "A_team"},
        "what_happened": f"Send team invitation to {email} as {role}."[:140],
        "why_it_matters": "It goes out by Gmail (send_email) and cannot be undone."[:280],
        "options": [
            {"id": "approve", "label": "Approve", "suggested": False, "irreversible": True},
            {
                "id": "edit",
                "label": "Edit first",
                "suggested": True,
                "irreversible": False,
                "reason": "Check the invitation details before it is sent.",
            },
            {"id": "hold", "label": "Hold", "suggested": False, "irreversible": False},
        ],
        "add_context": False,
        "actions": ["show_me"],
        "answer_channels": ["web", "mobile_web"],
        "created_at": at,
        "timeout": _GATE_TIMEOUT_S,
        "safe_default": "hold",
        "gate": {
            "id": gate_id,
            "action": {
                "type": "send_email",
                "connector": "gmail",
                "exact": f"send_email by Gmail to {email}."[:500],
                "item": item,
                "destination": None,
            },
            "irreversible": True,
            "risk_tier": "T2",
            "recipients": [email],
        },
        "consent": None,
    }

    sub_res = desk_run.cards.submit(card, outbox_id=outbox_id, district="D1")
    if sub_res.outcome not in ("accepted", "merged"):
        raise InviteNotSent(f"gate card refused: {sub_res.errors}")

    return outbox_id


def production_sender(
    *,
    artifacts: Any,
    outbox_store: Any,
    adapters: Mapping[str, Any],
    desks: Any,
    writer: Any,
    api_store: Any = None,
    clock: Any = None,
) -> Callable[..., str]:
    return lambda **fields: stage_team_invite(
        artifacts=artifacts,
        outbox_store=outbox_store,
        adapters=adapters,
        desks=desks,
        writer=writer,
        api_store=api_store,
        clock=clock,
        **fields,
    )


# Retain alias for any legacy callers
send_team_invite = stage_team_invite
