"""Server-side redaction views (PRD 10.1, 15.3, ticket brief item 7). "shared" holds only
`vis: "all"` events; a per-district scope holds `vis: "all"` events plus events whose `vis`
list names that district (`event.schema.json`'s vis def, EV-13). `WorldWriter` calls these for
every event it writes, once per scope, to build the redacted per-scope streams."""

from __future__ import annotations

from typing import Any


def scopes_for(layout: dict[str, Any]) -> list[str]:
    """ "shared" plus every district id in the layout, in level then district order."""
    scopes = ["shared"]
    for level in layout["semantic"]["levels"]:
        scopes.extend(district["id"] for district in level["districts"])
    return scopes


def redact(event: dict[str, Any], scope: str, vseq: int, view_ids: set[str]) -> dict[str, Any] | None:
    """The view copy of `event` for `scope`, or None when `scope` may not see it. `view_ids` is
    the set of event ids already written to this scope's view, so `cause` is kept only when the
    cause event is itself in this view (it never reveals a hidden event); every other field is
    unchanged, so the copy still validates against event.schema.json, and `seq` is set to
    `vseq`, this view's own dense counter, so no gap reveals a hidden event either."""
    vis = event["vis"]
    visible = vis == "all" if scope == "shared" else vis == "all" or scope in vis
    if not visible:
        return None
    copy = dict(event)
    copy["seq"] = vseq
    copy["cause"] = event["cause"] if event["cause"] in view_ids else None
    return copy
