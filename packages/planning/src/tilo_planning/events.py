"""TiloEvent builder shared by intake and planning. Events are built and validated here, never written:
the harness is the single writer per world and owns `seq` order."""

from __future__ import annotations

from typing import Any

from tilo_contracts import EVENT_DATA_MODELS, Event

from tilo_planning.artifacts import new_ulid


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_event(
    base: dict[str, Any],
    *,
    tool: str | None,
    summary: str,
    authz: dict[str, Any] | None = None,
    archive_ref: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """`base` holds v/ts/world_id/run_id/actor; `fields` the rest of the envelope (type, seq, target, ...).
    `authz` is set only on side-effect types, from a person or the policy engine's decision (BQ-01)."""
    data_model = EVENT_DATA_MODELS[fields["type"]]
    data = data_model.model_validate(fields["data"])
    fields["data"] = data.model_dump(mode="json", by_alias=True, exclude_unset=True)
    trace = dict.fromkeys(("model_role", "profile", "tokens_in", "tokens_out", "latency_ms", "archive_ref"))
    raw = {
        **base,
        **fields,
        "id": new_ulid(),
        "level": None,
        "district": None,
        "credits": 0,
        "summary": clip(summary, 140),
        "vis": "all",
        "authz": authz,
        "trace": {**trace, "tool": tool, "archive_ref": archive_ref},
    }
    return Event.model_validate(raw).model_dump(mode="json", exclude_unset=True)
