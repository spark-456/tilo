"""FR-SPD-05/07: read-only history from already scoped recorded approval events."""

from datetime import datetime
from typing import Any


def _at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at if at.tzinfo is not None else None
    except ValueError:
        return None


def cost_history(events: list[dict]) -> dict[str, Any]:
    """Pairs never cross worlds/runs/cards. Missing or invalid timestamps yield no duration.
    Holds/edits are recorded answers too; a later request begins a new wait."""
    recorded: dict[str, tuple[datetime, dict]] = {}
    for event in events:
        at = _at(event.get("ts"))
        if event.get("type") not in {"approval.requested", "approval.resolved"} or at is None:
            continue
        if not all(isinstance(event.get(k), str) for k in ("id", "world_id", "run_id", "summary")):
            continue
        recorded.setdefault(event["id"], (at, event))
    pending: dict[tuple[str, str, str], tuple[datetime, str]] = {}
    waits: list[dict] = []
    activity: list[dict] = []
    for at, event in sorted(recorded.values(), key=lambda pair: (pair[0], pair[1]["id"])):
        data = event.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("card_id"), str):
            continue
        world, run, card = event["world_id"], event["run_id"], data["card_id"]
        key = (world, run, card)
        activity.append(
            {k: event[k] for k in ("id", "world_id", "run_id", "type", "ts", "summary")} | {"card_id": card}
        )
        if event["type"] == "approval.requested":
            action = data.get("action_type")
            if isinstance(action, str):
                pending.setdefault(key, (at, action))
        elif (request := pending.pop(key, None)) is not None:
            seconds = (at - request[0]).total_seconds()
            waits.append(
                {"world_id": world, "run_id": run, "card_id": card, "action_type": request[1], "seconds": seconds}
            )
    return {"approval_waits": waits, "activity": list(reversed(activity))}
