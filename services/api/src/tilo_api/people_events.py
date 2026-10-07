"""The PE-12 events of the work-item writes (PPL-11c S5, API_PPL_11c.md section 5): `work_item.created` and
`work_item.changed`, handed to the single event writer as unstamped parts, in the Desk world of the person who may
read the record in full. The part names what the write itself recorded (the new record's last history entry), never
what the request asked for, and carries ids and enums only: no title, due phrase, quote, address or link (PE-12).
No model call, no log, no clock read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends

from tilo_api import deps, events

_PHRASE = {  # what the one-line summary says (fixed words only)
    "created": "added",
    "edited": "edited",
    "snoozed": "snoozed",
    "done": "marked done",
    "reopened": "reopened",
    "reassign_requested": "sent back for reassignment",
    "confirmed": "confirmed",
}


@dataclass(frozen=True)
class WorkEvents:
    """The two seams a work-item write needs, resolved before anything is committed."""

    writer: deps.EventWriter
    desks: deps.DeskWorlds

    def record(self, org: str, actor: str, after: dict[str, Any]) -> None:
        """Append the one event of the write that just committed `after`; any failure raises (the caller undoes the
        write). The Desk world is the owner's: the assignee's for a confirm (PE-12 "confirmed for P")."""
        owner, entry = after["owner"], after["history"][-1]
        change, status = entry["change"], after["status"]
        if change == "created":
            kind, data = "work_item.created", {"owner": owner, "status": status, "source_kind": after["source"]["kind"]}
        else:
            kind, data = "work_item.changed", {"change": change, "status": status}
        part = {
            "id": events.new_part_id(),
            "type": kind,
            "actor": actor,
            "target": owner,
            "summary": f"A work item was {_PHRASE.get(change, 'changed')}.",
            "vis": [],
            "authz": None,
            "data": {"work_item_id": after["id"], **data},
        }
        self.writer.append(self.desks.desk_world(org, owner), part)


def get_work_events(
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    desks: Annotated[deps.DeskWorlds, Depends(deps.get_desk_worlds)],
) -> WorkEvents:
    """Unwired in production: 503 `not_configured` before the route commits anything."""
    return WorkEvents(writer, desks)
