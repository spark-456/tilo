"""`config/meeting_room.yaml`, loaded strictly (ADR-0028 decision 9, MROOM-A1): every key required and no other, whole
numbers only (a bool or float is refused), each within the schema's ceiling. Errors name the key, never a value."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[4] / "config" / "meeting_room.yaml"
_RANGES = {  # key -> (min, max); max_agents counts the lead (schema: lead + 7 = 8); max_turns is the schema's ceiling
    "max_agents": (2, 8),
    "max_turns": (1, 50),
    "credit_cap": (1, 10_000),
    "max_changes": (0, 10),
    "idle_timeout_s": (1, 86_400),
    "open_rooms_per_world": (1, 5),
}
ROLES = ("Owner", "Approver", "Member")  # a Viewer never convenes (MR-03)


class RoomConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RoomConfig:
    max_agents: int
    max_turns: int
    credit_cap: int
    max_changes: int
    idle_timeout_s: int
    open_rooms_per_world: int
    convene_roles: tuple[str, ...]


def load_room_config(path: str | Path | None = None) -> RoomConfig:
    try:
        doc = yaml.safe_load(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RoomConfigError("meeting_room.yaml is unreadable") from exc
    if not isinstance(doc, dict) or set(doc) != {*_RANGES, "convene_roles"}:
        raise RoomConfigError("meeting_room.yaml must hold exactly the documented keys")
    for key, (low, high) in _RANGES.items():
        if type(doc[key]) is not int or not low <= doc[key] <= high:
            raise RoomConfigError(f"meeting_room.yaml: {key} must be a whole number from {low} to {high}")
    roles = doc["convene_roles"]
    if not isinstance(roles, list) or not roles or len(set(roles)) != len(roles) or not set(roles) <= set(ROLES):
        raise RoomConfigError(f"meeting_room.yaml: convene_roles must be a non-empty list from {list(ROLES)}")
    return RoomConfig(**{k: doc[k] for k in _RANGES}, convene_roles=tuple(roles))
