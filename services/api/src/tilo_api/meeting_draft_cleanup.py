"""FR-MTG-10: lazy deletion cleanup through the existing API store door, after owner/CAS checks."""

import os
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from tilo_people.stores import PeopleStores

from tilo_api import deps, store_door
from tilo_api.followup_draft_retention import followup_retention
from tilo_api.followup_outbox_sources import cancel_source_entries


def get_meeting_draft_cleanup(
    request: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    stores: Annotated[PeopleStores, Depends(deps.get_people_stores)],
) -> Callable[[str, str], None] | None:
    if principal.demo_session or getattr(request.state, "demo_session", False) is True:
        return None  # demos cannot have durable drafts
    if not os.environ.get("K_SERVICE") and os.environ.get(store_door.ENV_STORE) != "firestore":
        return None  # offline people workflows never open a cloud client

    def check(owner: str, meeting_id: str) -> None:
        current = stores.meetings.get(deps.ORG_ID, meeting_id)
        if (
            owner != principal.user_id
            or current is None
            or current.record.get("owner") != owner
            or current.record.get("org_id") != deps.ORG_ID
            or current.record.get("status") != "deleted"
            or current.record.get("world_id") is None
        ):
            raise HTTPException(409, "version_conflict", headers={"Cache-Control": "no-store"})

    def cleanup(owner: str, meeting_id: str) -> None:
        check(owner, meeting_id)
        try:
            opened = store_door.open_api_store()
        except store_door.ApiStoreNotConfigured:
            raise HTTPException(503, "not_configured", headers={"Cache-Control": "no-store"}) from None
        cancel_source_entries(opened.client, deps.ORG_ID, owner, meeting_id)
        for retention in followup_retention(opened.client, deps.ORG_ID, lambda: 0.0):
            retention.erase_meeting_complete(owner, meeting_id)
        check(owner, meeting_id)

    return cleanup
