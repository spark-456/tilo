"""tilo_policy.crossref — does an outbox entry send exactly what was authorised? (OB-01, OB-05,
contracts/outbox.rules.md). Uses the same predicates as `decide` and `open_gate`; every part is
checked against its contract first, and a case that fails is rejected ("OB-01")."""

from __future__ import annotations

from typing import Any

from .coverage import Target, add_seconds, covering_level, instruction_counts, opens_gate
from .decide import over_limit
from .schemas import conforms, event_ok

SLOTS = {
    "reserved_by": ("approval.requested",),
    "authorised_by": ("approval.resolved", "policy.applied"),
    "transfer": ("data.transfer",),
}


def _pinned(item: dict | None) -> tuple[Any, Any] | None:
    return None if item is None else (item["artifact_id"], item["version"])


def _policy_opened(case: dict, applied: dict) -> bool:
    """OB-01 policy path: the named policy covers the entry at authz.at, at the applied level."""
    entry, policy, instruction = case["entry"], case["policy"], case["instruction"]
    at, authz = entry["authz"]["at"], entry["authz"]
    if entry["risk_tier"] == "T3" or entry["modifiers"] or entry["attachments"]:
        return False  # a policy never authorises T3 (PI-07)
    if (authz["by"], authz["ref"]) != ("policy", applied["policy_id"]):
        return False  # PI-16: a policy send is stamped by that policy
    if over_limit(policy, case["earlier_applied"], 0, at) is not None:
        return False  # PI-11; the entry carries no credits, so only earlier sends count them
    target = Target(applied["action_type"], applied["connector"], applied["district"], entry["recipients"])
    level = covering_level(policy, target, case["world_owner"], at)
    named = (policy["id"], level, policy["undo_window_s"])
    if named != (applied["policy_id"], applied["level"], applied["undo_window_s"]):
        return False
    if level == "L3":
        return applied["instruction_id"] is None and instruction is None
    return (
        level == "L2"
        and instruction is not None
        and instruction["id"] == applied["instruction_id"]
        and instruction_counts(
            instruction, entry["world_id"], policy["owner"], applied["destination"], at, case["earlier_applied"]
        )
    )


def _breaks_ob01(case: dict) -> bool:
    entry, reserved, auth, transfer = case["entry"], case["reserved_by"], case["authorised_by"], case["transfer"]
    if auth is None or auth["authz"] != entry["authz"] or auth["data"]["outbox_id"] != entry["id"]:
        return True
    if transfer is not None and transfer["authz"] != entry["authz"]:
        return True
    if reserved is not None:
        return not opens_gate(reserved, auth, case["world_owner"], case["team_lead"], case["policy"])
    return auth["type"] != "policy.applied" or not _policy_opened(case, auth["data"])


def _breaks_ob05(case: dict) -> bool:
    entry, reserved, auth, transfer = case["entry"], case["reserved_by"], case["authorised_by"], case["transfer"]
    fields = (entry["action_type"], entry["risk_tier"], _pinned(entry["item"]))
    by = (reserved or auth or {}).get("data")
    if by is not None and (by["action_type"], by["risk_tier"], _pinned(by["item"])) != fields:
        return True
    if auth is not None and auth["type"] == "policy.applied":
        if any(auth["data"][f] != entry[f] for f in ("connector", "destination", "undo_window_s")):
            return True
    if (transfer is not None) != (entry["state"] == "sent"):
        return True
    window, waiting = entry["undo_window_s"], ("scheduled" if entry["undo_window_s"] > 0 else "queued")
    if entry["scheduled_at"] != add_seconds(entry["created_at"], window):
        return True  # OB-02: the undo window is kept
    if entry["state"] in ("queued", "scheduled") and entry["state"] != waiting:
        return True
    sent = (transfer or {}).get("data")
    return sent is not None and (
        (sent["direction"], sent["outbox_id"], sent["connector"], sent["action_type"], _pinned(sent["artifact"]))
        != ("out", entry["id"], entry["connector"], entry["action_type"], _pinned(entry["item"]))
    )


def _parts_ok(case: dict) -> bool:
    return (
        conforms("outbox.schema.json", case["entry"])
        and conforms("common.schema.json#/$defs/user_id", case["world_owner"])
        and all(case[slot] is None or event_ok(case[slot], types) for slot, types in SLOTS.items())
        and all(case[k] is None or conforms(f"{k}.schema.json", case[k]) for k in ("policy", "team_lead"))
    )


def check_entry(case: dict) -> str | None:
    """None when the entry sends what was authorised, else "OB-01" or "OB-05". A case too
    malformed to read is never valid (fail closed: "OB-01")."""
    try:
        return "OB-01" if not _parts_ok(case) or _breaks_ob01(case) else ("OB-05" if _breaks_ob05(case) else None)
    except Exception:
        return "OB-01"
