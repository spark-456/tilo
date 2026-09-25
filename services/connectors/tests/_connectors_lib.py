"""Clock double and plain helpers for services/connectors acceptance tests (ticket ST-2).

Kept out of conftest.py under a package-unique module name: every test directory in the
repo has its own conftest.py, so `from conftest import ...` resolves to whichever one was
imported first when the whole suite runs together. No production code lives here.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Manual clock test double (suggested API's "clock() returns RFC 3339 now; tests drive it").
# Minimal test wiring, not production code: production would wire clock() to the real wall
# clock instead.


def format_ts(dt: datetime) -> str:
    """RFC 3339, millisecond precision, "...Z" — common.schema.json#/$defs/timestamp."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def add_seconds(ts: str, seconds: float) -> str:
    return format_ts(parse_ts(ts) + timedelta(seconds=seconds))


class ManualClock:
    """A clock() test double: __call__ returns the current instant as RFC 3339; advance() moves
    it forward. Starts at `start` (a timestamp string)."""

    def __init__(self, start: str) -> None:
        self._now = parse_ts(start)

    def __call__(self) -> str:
        return format_ts(self._now)

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def set(self, ts: str) -> None:
        self._now = parse_ts(ts)


# ---------------------------------------------------------------------------
# Plain data factories. Every function returns a fresh, independent structure; callers mutate
# their own copy. Timestamps stay inside 2026-09-29, the same day
# contracts/fixtures/outbox/crossref uses, for consistency with those fixtures.

OWNER = "u_owner"
WORLD = "w_village_basic"
RUN = "r_village_basic_1"


def deep_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def evidence_from_case(case: dict) -> dict:
    """A crossref fixture case (or a hand-built equivalent) minus the keys Outbox.enqueue
    supplies itself (API.md: `{**evidence, "entry": entry, "transfer": None, "rule": None}`)."""
    return {k: v for k, v in case.items() if k not in ("rule", "note", "entry", "transfer")}
