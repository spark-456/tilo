"""tilo_policy.coverage — the one copy of the predicates `decide`, `open_gate` and `check_entry`
share (OB-01; PI-02, PI-04, PI-06, PI-08..PI-10, PI-13). Each checks its inputs against the
contracts and fails closed: a malformed record or event covers nothing and opens no gate."""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, NamedTuple, ParamSpec, TypeVar

from .schemas import conforms, event_ok

P = ParamSpec("P")
R = TypeVar("R")
LEVELS = ("L0", "L1", "L2", "L3")
INSTRUCTION_CHANNELS = {"world.requested": ("web", "mobile_web"), "channel.message_in": ("whatsapp",)}
# The policy fields open_gate reads when a Team Lead answers (PRD 10.1).
LEAD_POLICY_KEYS = ("id", "owner", "action_type", "team_lead_domains", "created_by", "changed_by", "expiry", "history")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")  # common.schema.json email_address, fully matched
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")


class Target(NamedTuple):
    """What a policy must cover: the action and where it goes."""

    action_type: str
    connector: str
    district: str
    recipients: tuple[str, ...] | list[str]


def fail_closed(default: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Any exception in the wrapped predicate returns `default`, the safe answer."""

    def wrap(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def safe(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return fn(*args, **kwargs)
            except Exception:
                return default

        return safe

    return wrap


def ts(value: Any) -> str:
    """A common.schema.json timestamp (UTC, milliseconds, Z) that is a real calendar instant, so
    string order is time order. Anything else raises ValueError."""
    if isinstance(value, str) and _TIMESTAMP.fullmatch(value):
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")  # month 19 or 30 February raise
        return value
    raise ValueError(f"not a UTC millisecond timestamp: {value!r}")


def add_seconds(at: str, seconds: int) -> str:
    moved = datetime.strptime(ts(at), "%Y-%m-%dT%H:%M:%S.%fZ") + timedelta(seconds=seconds)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


def _domain(address: str) -> str:
    """The text after "@", lower-cased only when ASCII: no Unicode folding (a Kelvin sign is not k)."""
    domain = address.rsplit("@", 1)[1]
    return domain.lower() if domain.isascii() else domain


def _within(allowed: list, value: Any) -> bool:
    return not allowed or value in allowed  # an empty scope list does not restrict


@fail_closed(None)
def level_at(policy: dict, at: str) -> str | None:
    """PI-13: the level of the last history entry at or before `at`; None when history is empty,
    out of order, or its last level is not the record's."""
    history = policy["history"]
    times = [ts(h["at"]) for h in history]
    if not history or times != sorted(times) or history[-1]["level"] != policy["level"]:
        return None
    earlier = [h["level"] for h, t in zip(history, times, strict=True) if t <= ts(at)]
    return earlier[-1] if earlier and earlier[-1] in LEVELS else None


def level_since(policy: dict, at: str) -> str:
    """When the level in force at `at` began: the first entry of the last run at that level."""
    since, current = "", None
    for entry in policy["history"]:
        if ts(entry["at"]) > ts(at):
            break
        if entry["level"] != current:
            since, current = entry["at"], entry["level"]
    return ts(since)


@fail_closed(False)
def stamped_by(policy: dict, now: str) -> bool:
    """A live decision reads the record as it is: every stamp is dated at or before `now`, so a
    Stop all or revocation already in the record is never read away (FR-HIL-07, PI-13)."""
    stamps = [policy["created_by"], policy["changed_by"], *policy["history"]]
    return all(ts(stamp["at"]) <= ts(now) for stamp in stamps if stamp is not None)


@fail_closed(False)
def in_force(policy: dict, owner: str, at: str) -> bool:
    """PI-06, PI-13: the world owner's policy, made and changed only by the owner, created by
    `at` and not expired at `at`."""
    stamps = [policy["created_by"], policy["changed_by"], *policy["history"]]
    return (
        policy["owner"] == owner
        and all(stamp["by"] == owner for stamp in stamps if stamp is not None)
        and ts(policy["created_by"]["at"]) <= ts(at)
        and (policy["expiry"] is None or ts(at) < ts(policy["expiry"]))
    )


def _scope_matches(policy: dict, target: Target) -> bool:
    """PI-06: connector, district, every recipient and its domain in scope. Raises when the scope
    cannot be read (not four lists)."""
    scope = policy["scope"]
    if not all(isinstance(scope[k], list) for k in ("connectors", "recipients", "domains", "districts")):
        raise ValueError("unreadable scope")
    return (
        target.connector in scope["connectors"]
        and _within(scope["districts"], target.district)
        and (bool(target.recipients) or not (scope["recipients"] or scope["domains"]))
        and all(
            isinstance(r, str)
            and _EMAIL.fullmatch(r) is not None
            and conforms("common.schema.json#/$defs/email_address", r)
            and _within(scope["recipients"], r)
            and _within(scope["domains"], _domain(r))
            for r in target.recipients
        )
    )


may_cover = fail_closed(True)(_scope_matches)  # for an invalid record: an unreadable scope may cover anything


@fail_closed(None)
def covering_level(policy: dict, target: Target, owner: str, at: str) -> str | None:
    """PI-06: the level at which a contract-valid `policy` covers `target` at `at`, or None."""
    if (policy["action_type"], policy["owner"]) != (target.action_type, owner):
        return None  # cheap filter before the schema check
    if not conforms("policy.schema.json", policy):
        return None
    covered = (
        all(v is None or math.isfinite(v) for v in policy["limits"].values())
        and in_force(policy, owner, at)
        and _scope_matches(policy, target)
    )
    return level_at(policy, at) if covered else None


@fail_closed(False)
def instruction_counts(
    instruction: dict | None, world_id: str, policy: dict, destination: str | None, before: str, applied: list[dict]
) -> bool:
    """PI-08..PI-10: the policy owner's own instruction in this world about this destination,
    signed in or from the bound WhatsApp number (never email), given while the L2 level in force
    at `before` was (no earlier than the entry that set it) and not used by an earlier send."""
    return (
        instruction is not None
        and instruction["data"]["channel"] in INSTRUCTION_CHANNELS.get(instruction["type"], ())
        and conforms("event.schema.json", instruction, "id", "type", "actor", "ts", "world_id")
        and conforms(f"events/data/{instruction['type']}.schema.json", instruction["data"], "channel", "destination")
        and (instruction["world_id"], instruction["actor"]) == (world_id, policy["owner"])
        and level_since(policy, before) <= ts(instruction["ts"]) < ts(before)
        and destination is not None
        and instruction["data"]["destination"] == destination
        and all(used["data"]["instruction_id"] != instruction["id"] for used in applied)
    )


@fail_closed("T3")
def gate_tier(reserved: dict) -> str:
    """The tier of a contract-valid approval.requested, else T3 (fail closed, SEC-06)."""
    return str(reserved["data"]["risk_tier"]) if event_ok(reserved, ("approval.requested",)) else "T3"


@fail_closed(False)
def opens_gate(reserved: dict, resolved: dict, owner: str, lead: dict | None, policy: dict | None) -> bool:
    """PI-02..PI-04, PRD 10.1, SEC-06: approve on the very gate, card and outbox entry, from the
    owner, the named Approver or an allowed Team Lead; a T3 gate on WhatsApp needs its PIN.
    Both events must be contract-valid (so never answered by email, never by a model)."""
    valid = event_ok(reserved, ("approval.requested",)) and event_ok(resolved, ("approval.resolved",))
    if not valid or not conforms("common.schema.json#/$defs/user_id", owner):
        return False
    gate, answer, authz = reserved["data"], resolved["data"], resolved["authz"]
    at, allowed = ts(authz["at"]), gate["team_lead"]
    if answer["option"] != "approve" or any(answer[k] != gate[k] for k in ("gate_id", "card_id", "outbox_id")):
        return False
    if gate_tier(reserved) == "T3" and answer["channel"] == "whatsapp" and answer["pin_verified"] is not True:
        return False
    if authz["by"] == "person":
        return authz["ref"] == owner or (gate["approver"] is not None and authz["ref"] == gate["approver"])
    return (
        authz["by"] == "team_lead"
        and allowed is not None
        and lead is not None
        and policy is not None
        and conforms("team_lead.schema.json", lead)
        and conforms("policy.schema.json", policy, *LEAD_POLICY_KEYS)
        and (lead["id"], lead["domain"]) == (authz["ref"], allowed["domain"])
        and lead["assigned_by"]["by"] == owner
        and ts(lead["assigned_by"]["at"]) <= at
        and (policy["id"], policy["action_type"]) == (allowed["policy_id"], gate["action_type"])
        and allowed["domain"] in policy["team_lead_domains"]
        and in_force(policy, owner, at)
    )
