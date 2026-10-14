"""A Writer's PDF deliverable (LW-10, ADR-0029 decision on the report): the model writes a DeliverableSpec as JSON only;
fixed code validates it and `tilo_render.pdf.render_pdf` renders it in process. No model call, no network.

The reply must be exactly one JSON object (no fence, no text around it), at most `MAX_REPLY` characters, with no
duplicate key and no NaN or Infinity, and it must pass `tilo_render.spec.DeliverableSpec` (unknown fields, dangling
table or chart links, and over-size tables are refused there). Nothing in the reply is run or evaluated, and the
renderer escapes every string, so script-like text is printed, never executed. Any failure raises `DeliverableRefused`
with a FIXED code: the reply is model text and may echo a secret, so it is never copied into the message. A refused
reply makes no PDF; the unit fails and the runner does not ask again.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from tilo_render.pdf import render_pdf
from tilo_render.spec import DeliverableSpec

from tilo_harness.outputs import MAX_PDF, RenderedPdf

MAX_REPLY = 500_000  # characters of the writer's reply (the spec's own limits keep a real report far below this)
PDF_FORMAT = "pdf"
_REASONS = {
    "too_large": "the reply is too long",
    "not_json": "the reply is not one JSON object",
    "invalid_spec": "the reply is not a valid report specification",
    "render_failed": "the report could not be laid out",
}


class DeliverableRefused(Exception):
    """The reply cannot become a PDF. `code` is one of a fixed few; `str()` is a plain sentence without the reply."""

    def __init__(self, code: str) -> None:
        super().__init__(_REASONS[code])
        self.code = code


def wants_pdf(unit: Mapping[str, Any], brief: Mapping[str, Any] | None) -> bool:
    """True for the writer's `deliver` unit (the final unit the plan compiler adds, BQ-218) when the brief's first
    deliverable, which that unit stands for, is a PDF. Decided by code from the plan and the brief, never a model."""
    items = brief.get("deliverables") if isinstance(brief, Mapping) else None
    first = items[0] if isinstance(items, list) and items else None
    return (
        unit.get("role") == "writer"
        and unit.get("unit_type") == "deliver"
        and isinstance(first, Mapping)
        and first.get("format") == PDF_FORMAT
    )


def render_format(unit: Mapping[str, Any], brief: Mapping[str, Any] | None) -> str | None:
    """The final writer's requested file format, chosen only from the approved brief."""
    items = brief.get("deliverables") if isinstance(brief, Mapping) else None
    first = items[0] if isinstance(items, list) and items else None
    fmt = first.get("format") if isinstance(first, Mapping) else None
    return (
        fmt
        if unit.get("role") == "writer" and unit.get("unit_type") == "deliver" and fmt in ("pdf", "pptx", "docx")
        else None
    )


def wants_rendered(unit: Mapping[str, Any], brief: Mapping[str, Any] | None) -> bool:
    return render_format(unit, brief) is not None


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _constant(_name: str) -> Any:
    raise ValueError("NaN and Infinity are not JSON")


def parse_spec(reply: Any) -> DeliverableSpec:
    """The reply as a validated DeliverableSpec, or DeliverableRefused."""
    if not isinstance(reply, str) or len(reply) > MAX_REPLY:
        raise DeliverableRefused("too_large")
    text = reply.strip()
    if not (text.startswith("{") and text.endswith("}")):  # a fence or any text around the object is refused
        raise DeliverableRefused("not_json")
    try:
        data = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
    except (ValueError, RecursionError):  # includes JSONDecodeError and the int-digits limit
        raise DeliverableRefused("not_json") from None
    try:
        return DeliverableSpec.model_validate(data)
    except Exception:  # noqa: BLE001 - pydantic's message echoes the input
        raise DeliverableRefused("invalid_spec") from None


def render_output(reply: Any) -> RenderedPdf:
    """The reply as the PDF `keep` stores with origin `render`, or DeliverableRefused (no partial PDF)."""
    spec = parse_spec(reply)
    try:
        pdf = render_pdf(spec)
    except Exception:  # noqa: BLE001 - the error text may echo the spec
        raise DeliverableRefused("render_failed") from None
    if len(pdf) > MAX_PDF:
        raise DeliverableRefused("too_large")
    return RenderedPdf(media_type="application/pdf", content=pdf, spec_text=spec.model_dump_json())
