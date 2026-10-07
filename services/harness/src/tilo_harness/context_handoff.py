"""Context handoff helpers (FR-AGT-09; PRD 8.5, 8.6): pure checks and the note's storage. The Lead's order of steps
lives in `executor`. No model call: the note is validated against handoff.schema.json and stored by code.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from tilo_memory.artifacts import NewVersion, Origin

from tilo_harness.validator import repo_validator

NOTE_ATTEMPT_BASE = 1000  # the note's AR-05 key `<run>:<unit>:<attempt>:0` counts up from here, clear of unit outputs


def context_pct(share: Any, handoff_at: float) -> int | None:
    """The whole percent of context used, or None unless `share` is a number from `handoff_at` up to 1."""
    if isinstance(share, bool) or not isinstance(share, int | float) or not math.isfinite(share):
        return None
    return int(round(share * 100)) if handoff_at <= share <= 1 else None


def note_is_valid(note: Any) -> bool:
    return isinstance(note, dict) and not repo_validator().contract_problems("handoff", note)


def store_note(store: Mapping[str, Any], run_id: str, unit_id: str, agent: str, note: dict[str, Any], n: int) -> Any:
    """Puts the note as application/json and returns its artifact_ref. `n` (0, 1, ...) counts this unit's handoffs."""
    new = NewVersion(
        media_type="application/json",
        content=json.dumps(note, sort_keys=True).encode("utf-8"),
        run_id=run_id,
        origin=Origin(kind="unit", unit=unit_id, agent=agent),
        idempotency_key=f"{run_id}:{unit_id}:{NOTE_ATTEMPT_BASE + n}:0",
    )
    return store["artifacts"].put(store["scope"], new).ref


def next_spare(ranks: Mapping[str, str], rank: str, used: set[str]) -> str | None:
    """The first agent of `rank`, in layout order, that is not in `used`."""
    return next((agent for agent, r in ranks.items() if r == rank and agent not in used), None)
