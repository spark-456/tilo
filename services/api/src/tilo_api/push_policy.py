"""The owner's standing L3 `send_push` policy (FR-CHN-17e; PRD 10.1, 10.4; BQ-CHN17-1, BQ-CHN17e-1).

Made only by the signed-in owner pressing confirm on the Profile control (`POST /v1/push/policy`), never by a model
or any other route, through the paths every policy uses: a `policy.schema.json` record kept with `Store.save` (one per
owner, so a second confirm is the same record) and one `policy.changed` part in the owner's Desk world
(`events.policy_changed_part`). It covers one action on one adapter (`send_push`, T1: a notice with a fixed title on
the owner's own devices), with no undo window and a per-day cap from `config/web_push.yaml`. Turning push off ends it
the way the kill switch does (`events.apply_level_change`: history entry, level L1), so delivery stops at once.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

from tilo_channels.web_push import CONNECTOR, load_config

from tilo_api import deps, desk, events

ACTION = "send_push"


def policy_id(owner: str) -> str:
    return "pol_push_" + hashlib.sha256(f"{deps.ORG_ID}:{owner}".encode()).hexdigest()[:24]


def _record(owner: str, at: str) -> dict[str, Any]:
    stamp = {"by": owner, "at": at}
    return {
        "id": policy_id(owner),
        "owner": owner,
        "action_type": ACTION,
        "scope": {"connectors": [CONNECTOR], "recipients": [], "domains": [], "districts": []},
        "limits": {"per_day": load_config().per_day, "credits": None},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": "L3",
        "undo_window_s": 0,
        "expiry": None,
        "notify_channel": "web",
        "team_lead_domains": [],
        "created_by": stamp,
        "changed_by": None,
        "history": [{**stamp, "change": "push notifications turned on by the owner", "level": "L3"}],
    }


def current(store: Any, owner: str) -> dict[str, Any] | None:
    """The owner's push policy record while it is at L3, else None. Never raises (cannot tell = off)."""
    try:
        store.load_owner(owner)
        found = store.policies.get(policy_id(owner))
    except Exception:  # noqa: BLE001
        return None
    ok = isinstance(found, dict) and found.get("owner") == owner and found.get("level") == "L3"
    return found if ok and found.get("action_type") == ACTION else None


def set_on(store: Any, writer: Any, owner: str, at: str, on: bool) -> None:
    """Creates (or raises again) the policy, or ends it. The event goes through the single writer first."""
    ref = desk.ensure_desk(store, org_id=deps.ORG_ID, user=owner)
    with desk.lock(store, owner):
        store.load_owner(owner)
        held = store.policies.get(policy_id(owner))
        if on and current(store, owner) is not None:
            return
        if not on and current(store, owner) is None:
            return
        if held is None:
            record, change = _record(owner, at), "created"
        else:
            record, change = copy.deepcopy(held), "push notifications turned " + ("on" if on else "off")
            if on:
                record["history"] = [
                    *record.get("history", []),
                    {"by": owner, "at": at, "change": change, "level": "L3"},
                ]
                record["level"], record["changed_by"] = "L3", {"by": owner, "at": at}
            else:
                events.apply_level_change(record, owner=owner, change=change, at=at)
        level = "L3" if on else "L1"
        part = events.policy_changed_part(
            part_id=events.new_part_id(), policy_id=record["id"], change=change, owner=owner, at=at, vis="all",
            level=level,
        )  # fmt: skip
        store.save(
            writer,
            parts={ref.world_id: [part]},
            worlds={ref.world_id: store.worlds[ref.world_id]},
            policies={record["id"]: record},
            policy_worlds={record["id"]: ref.world_id},
        )
