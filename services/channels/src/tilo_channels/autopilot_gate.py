"""tilo_channels.autopilot_gate: the gate of an L1 or T3 Autopilot card (CHN-WIRE-1, FR-CHN-11; OB-01, OB-04, OB-05).

The ids a gate needs derive from the autopilot card id alone (no clock, no store, no randomness), so `tilo-api` and the
Autopilot agree without a contract change. `requested_part` is the `approval.requested` the card stores at preview;
`evidence_for` is the gate path of `tilo_policy.check_entry`: the stored part, the person's approval as given, the
card's owner as world owner and nothing else (a policy part never opens an L1 or T3 gate). `opens` runs the real
`check_entry` before a card's decision slot is claimed, so a refused approval never uses the card up.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import tilo_policy

from tilo_channels.autopilot_state import _CROCKFORD, ACTION_TYPE

_PREFIX = b"tilo-gate-card-v1\n"


def _digest(autopilot_card_id: str) -> bytes:
    return hashlib.sha256(_PREFIX + autopilot_card_id.encode()).digest()


def gate_card_id(autopilot_card_id: str) -> str:
    """The gate's `card_id`: 128 hash bits as a 26-character Crockford ULID (its time bits are hash bits)."""
    value = int.from_bytes(_digest(autopilot_card_id)[:16], "big")
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def gate_id_for(autopilot_card_id: str) -> str:
    """The gate's `gate_id`, "G1" to "G9999"; it may repeat across cards (OB-01 matches all three ids together)."""
    return f"G{1 + int.from_bytes(_digest(autopilot_card_id)[16:20], 'big') % 9999}"


def requested_part(doc: dict[str, Any], outbox_id: str) -> dict[str, Any]:
    """The `approval.requested` part of a card with a ready, sendable T2 or T3 draft; the owner alone may answer."""
    return {
        "type": "approval.requested",
        "authz": None,
        "data": {
            "gate_id": gate_id_for(doc["card_id"]),
            "card_id": gate_card_id(doc["card_id"]),
            "outbox_id": outbox_id,
            "action_type": ACTION_TYPE,
            "risk_tier": doc["tier"],
            "irreversible": True,
            "item": doc["item"],
            "approver": None,
            "team_lead": None,
        },
    }


def evidence_for(doc: dict[str, Any], approval: Any, world_owner: str | None) -> dict[str, Any] | None:
    """The OB-01 evidence for `doc` answered by `approval`; None without a stored part, a dict approval or a trusted
    world owner. The owner comes from the Autopilot's world, never from the card or the approval."""
    requested = doc.get("approval_requested")
    if not isinstance(requested, dict) or not isinstance(approval, dict) or not isinstance(approval.get("authz"), dict):
        return None
    if not world_owner or doc.get("user_id") != world_owner:
        return None
    return {
        "reserved_by": copy.deepcopy(requested),
        "authorised_by": copy.deepcopy(approval),
        "world_owner": world_owner,
        "policy": None,
        "team_lead": None,
        "instruction": None,
        "earlier_applied": [],
    }


def opens(entry: dict[str, Any], evidence: dict[str, Any]) -> bool:
    """True only when the real OB-01 / OB-05 check accepts the entry with this evidence (fail closed)."""
    try:
        return tilo_policy.check_entry({**evidence, "entry": entry, "transfer": None, "rule": None}) is None
    except Exception:
        return False
