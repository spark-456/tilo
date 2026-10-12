"""The PE-12 events of the work-item writes (PPL-11c S5, API_PPL_11c.md section 5): `work_item.created` and
`work_item.changed`, handed to the single event writer as unstamped parts, in the Desk world of the person who may
read the record in full. The part names what the write itself recorded (the new record's last history entry), never
what the request asked for, and carries ids and enums only: no title, due phrase, quote, address or link (PE-12).
No model call, no log, no clock read."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends

from tilo_api import deps, events

_DESK_WORLD = re.compile(r"w_desk_[0-9A-Za-z_]{1,43}")  # a world id (common.schema.json: w_ + 1..48) of the Desk kind

MAX_ATTEMPTS = 3  # `append` calls per write, one part id (BQ-PPL11C-41)

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
        pin = "scope" in after
        owner = (
            after["scope"]["user"]
            if pin and after["scope"]["kind"] == "personal"
            else after["set_up_by"]
            if pin
            else after["owner"]
        )
        entry = after["history"][-1]
        change, status = entry["change"], after["status"]
        if pin:
            kind = "pinboard.item_added" if change == "created" else "pinboard.item_changed"
            data = (
                {
                    "scope_kind": after["scope"]["kind"],
                    "team": after["scope"].get("team"),
                    "status": status,
                    "made_by": after["created_by"]["by"],
                    "source_kind": None if after["source"] is None else after["source"]["kind"],
                }
                if change == "created"
                else {"change": change, "status": status}
            )
        elif change == "created":
            kind, data = "work_item.created", {"owner": owner, "status": status, "source_kind": after["source"]["kind"]}
        else:
            kind, data = "work_item.changed", {"change": change, "status": status}
        part = {
            "id": events.new_part_id(),
            "type": kind,
            "actor": actor,
            "target": owner,
            "summary": f"A {'pin' if pin else 'work item'} was {_PHRASE.get(change, 'changed')}.",
            "vis": [],
            "authz": None,
            "data": {"pin_id" if pin else "work_item_id": after["id"], **data},
        }
        world = self.desks.desk_world(org, owner)
        if type(world) is not str or _DESK_WORLD.fullmatch(world) is None or self.desks.desk_owner(world) != owner:
            raise ValueError("not the owner's Desk world")  # fail closed: write nothing, never echo the answer
        for attempt in range(MAX_ATTEMPTS):  # the writer is idempotent by part id: a resend of an append that landed
            try:  # and lost its answer commits nothing twice (FS-2 (b), EV-10)
                self.writer.append(world, part)
                return
            except Exception as exc:
                # Same optional seam as dispatch.py; tilo-api does not import the harness.
                reopen = getattr(self.writer, "reopen", None)
                if type(exc).__name__ == "WriterBusy" and callable(reopen):
                    try:
                        reopen()
                    except Exception:
                        pass  # preserve the original failure and bounded retries; no library text is exposed
                if attempt == MAX_ATTEMPTS - 1:
                    raise


def get_work_events(
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    desks: Annotated[deps.DeskWorlds, Depends(deps.get_desk_worlds)],
) -> WorkEvents:
    """The writer and Desk seams as wired (503 `not_configured` before the route commits when the store is not)."""
    return WorkEvents(writer, desks)
