"""FR-PA-10: may the signed-in person do `action` to a stored work item? The assistant panel only proposes a typed
update, so it needs the oracle's verdict and the record as stored now, never a write. The oracle is called through
the module attribute (spies wrap it) and the request is loaded as `people_access.read_as` loads it (PE-19)."""

from __future__ import annotations

from typing import Any

import tilo_people.access as access
from tilo_people.stores import PeopleStores

from tilo_api.people_access import SourceOwners, request_parts


def decide_as(
    people: PeopleStores,
    directory: Any,
    *,
    actor: str,
    org_id: str,
    record_id: str,
    action: str,
    now: str,
    source_owners: SourceOwners,
) -> dict[str, Any] | None:
    """The work item as stored now when `decide` lets `actor` do `action` to it, else None (fail closed)."""
    try:
        parts = request_parts(
            people,
            actor=actor,
            org_id=org_id,
            record_kind="work_item",
            record_id=record_id,
            now=now,
            source_owners=source_owners,
        )
        if parts is None or not access.decide(access.AccessRequest(action=action, **parts), directory).allowed:
            return None
        return dict(parts["record"])
    except Exception:
        return None
