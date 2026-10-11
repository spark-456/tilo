"""The one conversion of a committed cost event to its Treasury ledger entry (FR-MTR-10, COST-FAST-1b, PROD-WIRE 5a).

Dev mode's `DevLedger.record` and the deployed `WorldWriterAdapter` both call this, so the two cannot drift on any
field. An event that records no positive credits is not a cost and gives no entry. An event records no token usage, so
`usage` is whatever the caller states (dev mode passes its fixed fake profile; the deployed writer passes nothing and
none is invented)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage

from tilo_api import deps


def entry_from_cost_event(
    event: Mapping[str, Any], owner: str, *, org: str = deps.ORG_ID, usage: Usage | None = None
) -> LedgerEntry | None:
    """The `commit` entry of `event` for `owner`, or None when its `credits` are not a positive number."""
    credits = event.get("credits")
    if isinstance(credits, bool) or not isinstance(credits, int | float) or credits <= 0:
        return None
    item = event.get("item")
    return LedgerEntry(
        kind="commit", run=event["run_id"], user=owner, org=org, at=datetime.fromisoformat(event["ts"]),
        step=item if isinstance(item, str) else None, credits=float(credits), usage=usage,
    )  # fmt: skip
