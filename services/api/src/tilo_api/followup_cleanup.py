"""FR-MEM-09: the authenticated Scheduler tick purges expired meeting follow-up state."""

import logging
import os
from collections.abc import Callable
from datetime import datetime

from tilo_api import deps, store_door
from tilo_api.followup_draft_retention import followup_retention

logger = logging.getLogger(__name__)


def sweep(clock: Callable[[], datetime]) -> None:
    if os.environ.get(store_door.ENV_STORE) != "firestore":
        return  # no durable follow-up state in the offline store
    try:
        opened = store_door.open_api_store()
        for policy in followup_retention(opened.client, deps.ORG_ID, lambda: clock().timestamp()):
            policy.purge_expired()  # bounded pass; stale content is already denied at the read boundary
    except Exception as exc:
        logger.error("follow-up expiry sweep failed (%s)", type(exc).__name__)
