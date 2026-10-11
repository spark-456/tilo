"""FR-PB-01: indexed read-only pins, vetted by the existing PE-01/02 oracle."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tilo_people.access import AccessRequest, read

from tilo_api import deps
from tilo_api.people_access import request_parts
from tilo_api.people_writes import Refusal, Writer


@dataclass(frozen=True)
class _Owners:
    seam: deps.SourceOwners

    def owner_of(self, org_id: str, record_kind: str, record: Mapping[str, Any]) -> str | None:
        source = record["source"]
        return self.seam.owner_of(source["kind"], source["ref"])


def list_pins(w: Writer, owners: deps.SourceOwners) -> dict[str, Any]:
    directory = w.org_directory()
    person = directory.record(w.actor)
    if person is None:
        raise Refusal(404, "not_found")
    indexes = [("scope.user", w.actor), ("set_up_by", w.actor)]
    indexes.extend(
        ("scope.team", m["team"]) for m in person["memberships"] if directory.is_member(w.actor, m["team"], w.now)
    )
    candidates = {s.record["id"] for index, value in indexes for s in w.stores.pins.list(w.org, index, value)}
    rows = []
    for pin_id in sorted(candidates):
        parts = request_parts(
            w.stores,
            actor=w.actor,
            org_id=w.org,
            record_kind="pinboard_item",
            record_id=pin_id,
            now=w.now,
            source_owners=_Owners(owners),
        )
        if parts is not None:
            got = read(AccessRequest(action="read_full", **parts), directory)
            if got is not None:
                rows.append(got)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return {"items": rows[:200], "truncated": len(rows) > 200}
