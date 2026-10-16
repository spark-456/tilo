"""A native website (WEB-1, ADR-0050, contracts/website.rules.md WS-01 and WS-09).

The writer's final `deliver` unit of a brief whose first deliverable is a `website` made natively replies with one
complete HTML file. Code, never the model, sets the media type (`text/html`) from the unit's role and the brief, and
`tilo_memory.website_check.check_website` judges the exact bytes. A failing reply raises `DeliverableRefused` with the
FIXED code `website_invalid` and `detail` (the checker's code and line, no file text) for the one repair call; the
runner then degrades to the Markdown output. Nothing here runs or renders the file.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tilo_memory.website_check import check_website

from tilo_harness.deliverable import DeliverableRefused
from tilo_harness.outputs import WebsiteHtml

WEBSITE_FORMAT = "website"
REPAIR_REPLY_CHARS = 40_000  # how much of the failed reply the repair call is shown


def wants_website(unit: Mapping[str, Any], brief: Mapping[str, Any] | None) -> bool:
    """WS-01: a writer's `deliver` unit whose brief's first deliverable is a website made natively (`make_with` absent
    until WEB-4a, or `native`). Decided by code from the plan and the brief, never a model."""
    items = brief.get("deliverables") if isinstance(brief, Mapping) else None
    first = items[0] if isinstance(items, list) and items else None
    return (
        unit.get("role") == "writer"
        and unit.get("unit_type") == "deliver"
        and isinstance(first, Mapping)
        and first.get("format") == WEBSITE_FORMAT
        and first.get("make_with", "native") == "native"
    )


def website_output(reply: Any) -> WebsiteHtml:
    """The reply as the checked HTML `keep` stores, or DeliverableRefused("website_invalid")."""
    if not isinstance(reply, str):
        raise DeliverableRefused("website_invalid", "ws_encoding, line 1")
    data = reply.strip().encode("utf-8", "replace")
    result = check_website(data)
    if not result.ok:
        raise DeliverableRefused("website_invalid", f"{result.code}, line {result.line}")
    return WebsiteHtml(media_type="text/html", content=data)


def degraded(reply: str) -> bytes:
    """The Markdown the person gets when no checked page could be made: prose as written, a page as a code block."""
    if "<" not in reply:
        return reply.encode("utf-8")
    code = reply[:100_000]
    fence = "`" * max(3, _longest_ticks(code) + 1)
    note = "The page below did not pass Tilo's safety checks, so it is shown as text, not as a website."
    return f"{note}\n\n{fence}html\n{code}\n{fence}\n".encode()


def _longest_ticks(text: str) -> int:
    longest = run = 0
    for char in text:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    return longest
