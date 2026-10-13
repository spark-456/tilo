"""COST-AUDIT: when a Lead reviews a district, in one place so no caller can drift from another.

PRD 8.2: supervisors review "at milestones, not every step, to bound cost". A district with one unit has nothing to
review beyond that unit (its own Verifier and the artifact review already look at it), so only a district with at
least `MIN_DISTRICT_UNITS` units is reviewed, once, at the last of its units in plan order. The review is a model
call on the cheap `REVIEW_ROLE` (lite tier in `config/models*.yaml`), not on the thinking `lead` role.

Today only the e2e driver (`tilo_evals.live_e2e`) makes this model call; the production executor's `review` is the
Verifier's artifact review and does not use it. Any future production Lead review must call this helper.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MIN_DISTRICT_UNITS = 2
REVIEW_ROLE = "lead_review"


def review_milestones(units: Sequence[Mapping[str, Any]]) -> frozenset[str]:
    """Ids of the units after which their district gets its one Lead review."""
    by_district: dict[str, list[str]] = {}
    for unit in units:
        by_district.setdefault(str(unit["district"]), []).append(str(unit["id"]))
    return frozenset(ids[-1] for ids in by_district.values() if len(ids) >= MIN_DISTRICT_UNITS)
