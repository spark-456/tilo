"""`team_rule.changed` (ADR-0027 decision 2; FR-TEAM-04 "every change is logged", FR-ACC-01): the one event of a
changed stop-and-ask switch or tool level, handed to the single event writer as an unstamped part, in the Desk world of
the signed-in person who made the change (the same pattern as `people_events`). Enums and the connector id only: no
email, no free text. Roles, limits, invites and removals are not team rules (BQ-ADR27-3). No model, no clock read."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends

from tilo_api import deps, events

_DESK_WORLD = re.compile(r"w_desk_[0-9A-Za-z_]{1,43}")  # a world id (common.schema.json: w_ + 1..48) of the Desk kind


@dataclass(frozen=True)
class TeamEvents:
    """The two seams a rule change needs, resolved before anything is committed."""

    writer: deps.EventWriter
    desks: deps.DeskWorlds

    def record(self, actor: str, rule: str, key: str, before: str, after: str) -> None:
        """Append the one event of the change that just committed; any failure raises (the caller undoes the change).
        The world must be a Desk world owned by `actor`, else nothing is written (fail closed, answer never echoed)."""
        part: dict[str, Any] = {
            "id": events.new_part_id(),
            "type": "team_rule.changed",
            "actor": actor,
            "target": actor,
            "summary": f"A team rule changed: {key} is now {after}.",
            "vis": [],
            "authz": None,
            "data": {"rule": rule, "key": key, "from": before, "to": after},
        }
        world = self.desks.desk_world(deps.ORG_ID, actor)
        if type(world) is not str or _DESK_WORLD.fullmatch(world) is None or self.desks.desk_owner(world) != actor:
            raise ValueError("not the signed-in person's Desk world")
        self.writer.append(world, part)


def get_team_events(
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    desks: Annotated[deps.DeskWorlds, Depends(deps.get_desk_worlds)],
) -> TeamEvents:
    """Unwired in production: 503 `not_configured` before the route commits anything."""
    return TeamEvents(writer, desks)
