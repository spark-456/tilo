"""MN-01, MN-02, MN-09 (mentions.rules.md): the `refs` field of `POST /intake`, a JSON array of mention refs.

Each ref is resolved again as the signed-in person; one that fails any check gets exactly the 422 `ref_error` body of a
ref that does not exist, so no answer says what exists (`{"error": "ref_unavailable", "index": n}`). SKILL-TAG resolves
the skill kinds (a library skill, a taught skill the person may use); the other kinds are resolved by their own tickets
(M1, M1b) and until then fail closed with the same body. One skill is tagged at a time. Nothing here calls a model.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.responses import JSONResponse
from tilo_policy.schemas import conforms

from tilo_api.skills_route import SkillContext

_SKILLS = ("skill", "taught_skill")
_MAX_CHARS = 4096


class RefsRefused(Exception):
    """The 422 to send: `ref_unavailable` with the index of the ref, or a plain reason for a refs field that is not a
    list of refs at all."""

    def __init__(self, index: int | None = None, reason: str = "The refs are not valid.") -> None:
        super().__init__(reason)
        self.index, self.reason = index, reason

    def response(self) -> JSONResponse:
        body = {"error": "ref_unavailable", "index": self.index} if self.index is not None else {"error": self.reason}
        return JSONResponse(status_code=422, content=body)


def parse_refs(raw: str | None) -> list[dict[str, Any]]:
    """The refs of the form field, checked against mentions.schema.json: at most 10, none twice, each a closed ref."""
    if raw is None or not raw.strip():
        return []
    if len(raw) > _MAX_CHARS:  # ten refs are well under this; nothing deeper or longer is a list of refs
        raise RefsRefused()
    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001 - bad JSON, a RecursionError from deep nesting, anything: one refusal, never a 500
        raise RefsRefused() from None
    if not isinstance(parsed, list) or len(parsed) > 10 or any(parsed.count(r) > 1 for r in parsed):
        raise RefsRefused()
    for index, ref in enumerate(parsed):
        if not conforms("mentions.schema.json#/$defs/ref", ref):
            raise RefsRefused(index)
    return parsed


def tagged_skill(refs: list[dict[str, Any]], skills: SkillContext) -> dict[str, Any] | None:
    """The one skill the refs tag, in the match shape with source `tagged`, or None when they tag none."""
    chosen = None
    for index, ref in enumerate(refs):
        found = skills.resolve_tag(ref["kind"], ref["id"]) if ref["kind"] in _SKILLS else None
        if found is None:
            raise RefsRefused(index)
        if chosen is not None:
            raise RefsRefused(reason="Tag one skill at a time.")
        chosen = found
    return chosen
