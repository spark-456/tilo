"""World shares (ADR-0040, people.rules.md PE-31): the derived id and the in-force rule.

A `world_share` links one world to one team. It is a record, not a role: it carries no scope and adds no Approver or
Team Lead. Whether it still means what it said depends on the directory, which a schema cannot see, so `in_force`
is the one place that decides it. It is `permits`-parity code: the reference oracle of the contract lane
(`tests/contracts/_people_lib.py`, `share_in_force`) reaches the same verdict on every crossref case.

Deterministic code only: no model, store, clock or randomness (`now` is an argument). It never raises and answers a
plain bool; a share that is not in force is "no share", never an error.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from ._schema import is_timestamp, is_user_id, valid
from .directory import Directory

_SCHEMA = "world_share.schema.json"


def share_id(world_id: str, team: str) -> str:
    """`ws_` and the first 32 hex characters of the SHA-256 of `<world_id>/<team>` (PE-31): one record per pair."""
    return "ws_" + hashlib.sha256(f"{world_id}/{team}".encode()).hexdigest()[:32]


def in_force(share: Any, world_owner: Any, directory: Directory, now: Any) -> bool:
    """PE-31: the share is valid and its id is derived, it is not revoked, it was granted by the world's current
    record owner (`world_owner`, from the store, never from the request) no later than `now`, the owner is of the
    share's org and is a member of its team at `now`, and the membership was assigned no later than the grant (so a
    lapse does not revive when the owner returns: they share again)."""
    try:
        return _in_force(share, world_owner, directory, now)
    except Exception:
        return False


def _in_force(share: Any, world_owner: Any, directory: Directory, now: Any) -> bool:
    if not isinstance(share, Mapping) or not isinstance(directory, Directory) or not is_timestamp(now):
        return False
    if not is_user_id(world_owner) or not valid(_SCHEMA, share):
        return False
    granted: Mapping[str, Any] = share["granted_by"]
    owner = directory.record(world_owner)
    if owner is None or share["id"] != share_id(share["world_id"], share["team"]):
        return False
    team = share["team"]
    return (
        share["revoked"] is None
        and granted["by"] == world_owner
        and granted["at"] <= now
        and owner["org_id"] == share["org_id"]
        and directory.is_member(world_owner, team, now)
        and any(m["team"] == team and m["assigned_by"]["at"] <= granted["at"] for m in owner["memberships"])
    )
