"""Plain data factories for packages/policy acceptance tests (ticket P4-01, PRD 10.4).

Kept out of conftest.py under a package-unique module name: every test directory in the
repo has its own conftest.py, so `from conftest import ...` resolves to whichever one was
imported first when the whole suite runs together. No business logic lives here.
"""

from __future__ import annotations

import copy
from typing import Any

# ---------------------------------------------------------------------------
# Plain data factories (PRD 10.4 shapes). Every function returns a fresh, independent
# structure; callers mutate their own copy. Timestamps stay inside 2026-09-29, the same day
# used throughout contracts/fixtures/outbox/crossref, so "same UTC day" daily-cap tests need no
# date gymnastics.

OWNER = "u_owner"
WORLD = "w_village_basic"


def stamp(at: str, by: str = OWNER) -> dict:
    return {"by": by, "at": at}


def base_policy(
    *,
    id_: str = "pol_test",
    action_type: str = "send_email",
    level: str = "L2",
    owner: str = OWNER,
    connectors: tuple[str, ...] = ("gmail",),
    recipients: tuple[str, ...] = (),
    domains: tuple[str, ...] = ("example.com",),
    districts: tuple[str, ...] = (),
    per_day: int | None = 20,
    credits: float | None = 50,
    undo_window_s: int = 60,
    expiry: str | None = None,
    team_lead_domains: tuple[str, ...] = (),
    history: list[dict] | None = None,
    created_at: str = "2026-09-29T09:30:00.000Z",
) -> dict:
    """A policy.schema.json record with every dimension defaulted for the L2 email-reply
    scenario used across FR-HIL-05 tests; override individual fields per test."""
    hist = history if history is not None else [{"by": owner, "at": created_at, "change": "Created", "level": level}]
    return {
        "id": id_,
        "owner": owner,
        "action_type": action_type,
        "scope": {
            "connectors": list(connectors),
            "recipients": list(recipients),
            "domains": list(domains),
            "districts": list(districts),
        },
        "limits": {"per_day": per_day, "credits": credits},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": level,
        "undo_window_s": undo_window_s,
        "expiry": expiry,
        "notify_channel": "whatsapp",
        "team_lead_domains": list(team_lead_domains),
        "created_by": stamp(created_at, owner),
        "changed_by": None,
        "history": hist,
    }


def base_facts(**overrides: Any) -> dict:
    """Kwargs matching tilo_policy.SideEffectFacts's fields; tests pass this as **kwargs to the
    real dataclass once it exists (importing it is the point of these tests failing today)."""
    base = {
        "recipients": ("riya@example.com",),
        "known_recipients": ("riya@example.com",),
        "attachments": (),
        "external_share": False,
        "deletion": False,
        "money_or_legal": False,
        "safety_flags": False,
    }
    base.update(overrides)
    return base


def base_instruction(
    *,
    id_: str = "01JB5VQ0000000000000000131",
    type_: str = "channel.message_in",
    channel: str = "whatsapp",
    actor: str = OWNER,
    ts: str = "2026-09-29T09:41:50.000Z",
    destination: str = "thread-supplier-1",
    world_id: str = WORLD,
) -> dict:
    return {
        "id": id_,
        "type": type_,
        "actor": actor,
        "ts": ts,
        "world_id": world_id,
        # ADR-0007: a channel.message_in instruction is typed words answering no card.
        "data": {"channel": channel, "destination": destination}
        | ({"card_kind": None, "option": None} if type_ == "channel.message_in" else {}),
    }


def applied_entry(
    *,
    policy_id: str,
    at: str,
    instruction_id: str | None = None,
    credits: float = 0,
    outbox_id: str = "01JB5VQ0000000000000009999",
) -> dict:
    """One earlier `policy.applied` part, in the shape `decide`'s `applied` parameter takes
    (API.md "applied shape")."""
    return {
        "type": "policy.applied",
        "authz": {"by": "policy", "ref": policy_id, "at": at},
        "data": {
            "policy_id": policy_id,
            "gate_id": "G1",
            "outbox_id": outbox_id,
            "action_type": "post_status_update",
            "connector": "gmail",
            "destination": None,
            "district": "D1",
            "risk_tier": "T2",
            "level": "L3",
            "instruction_id": instruction_id,
            "undo_window_s": 60,
            "item": None,
            "credits": credits,
        },
    }


def deep_copy(value: Any) -> Any:
    return copy.deepcopy(value)
