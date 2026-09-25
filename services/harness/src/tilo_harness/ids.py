"""Id patterns that become part of a Firestore path (PRD 15.3), mirroring
`contracts/common.schema.json`'s `org_id`, `world_id`, `run_id` and `district_id` `$defs`
(`contracts/` is read-only: this is a fresh, hand-kept copy for path safety, not an import of the
schema or of `scripts/`).

Nothing that becomes an `f"orgs/{org_id}/worlds/{world_id}/..."` Firestore path may be accepted
without first matching one of these patterns, because every one of them excludes "/" -- a
`world_id` such as `"w_victim/events/00000001"` can therefore never reach a path-building
f-string. `WorldWriter.__init__` checks `org_id`/`world_id`/`run_id` against these before any
store call; `FirestoreStore` checks them again (plus `scope`, via `is_scope`) at every path it
builds, so the guard holds even for a caller that bypasses `WorldWriter`.
"""

from __future__ import annotations

import re

ORG_ID = re.compile(r"^org_[0-9A-Za-z_]{1,48}$")
WORLD_ID = re.compile(r"^w_[0-9A-Za-z_]{1,48}$")
RUN_ID = re.compile(r"^r_[0-9A-Za-z_]{1,48}$")
DISTRICT_ID = re.compile(r"^D[0-9]{1,4}$")


def is_scope(scope: str) -> bool:
    """A store "scope" is "shared" or a district id -- the only values `views.scopes_for`
    ever produces."""
    return scope == "shared" or bool(DISTRICT_ID.match(scope))


def check_id(value: str, pattern: re.Pattern[str], *, label: str) -> None:
    """Raises ValueError unless `value` matches `pattern` (which never allows "/")."""
    if not pattern.match(value):
        raise ValueError(f"{label} {value!r} does not match common.schema.json's {label} pattern")
