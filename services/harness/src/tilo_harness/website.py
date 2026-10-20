"""A native website (WEB-1, ADR-0050, contracts/website.rules.md WS-01 and WS-09).

The writer's final `deliver` unit of a brief whose first deliverable is a `website` made natively replies with one
complete HTML file. Code, never the model, sets the media type (`text/html`) from the unit's role and the brief, and
`tilo_memory.website_check.check_website` judges the exact bytes. A failing reply raises `DeliverableRefused` with the
FIXED code `website_invalid` and `detail` (the checker's code and line, no file text) for the one repair call; the
runner then degrades to the Markdown output. Nothing here runs or renders the file.

Before the check, `tidy` makes one narrow rewrite the checker would otherwise refuse (WS-07 bans `top` as a word): a
`scrollTo`/`scrollBy`/`scroll` call with an options object of only `top`, `left` and `behavior` becomes the same call
with positions, `scrollTo(left, top)` (a live CLAT questionnaire page degraded on exactly this, 20 Oct). It can only
remove words, never add a URL or a call, and the checker still judges every byte that is kept.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from tilo_memory.website_check import WebsiteCheck, check_website

from tilo_harness.deliverable import DeliverableRefused
from tilo_harness.outputs import WebsiteHtml

WEBSITE_FORMAT = "website"
REPAIR_REPLY_CHARS = 100_000  # how much of the failed reply the repair call is shown (a 48k-char page was cut, 20 Oct)
MAX_HINTS = 10  # checker problems named to the repair (the 20 Oct page had a second one 14 lines below the first)
_SCROLL_CALL = re.compile(r"(?<![\w$])(scroll(?:To|By)?)\s*\(\s*\{([^{}()\[\];]*)\}\s*\)")
_SCROLL_OPTION = re.compile(r"\s*(top|left|behavior)\s*:\s*([^\s,][^,]*?)\s*")


def _positional(call: re.Match[str]) -> str:
    options: dict[str, str] = {}
    for part in call.group(2).split(","):
        if not part.strip():
            continue  # a trailing comma
        found = _SCROLL_OPTION.fullmatch(part)
        if found is None or found.group(1) in options:
            return call.group(0)
        options[found.group(1)] = found.group(2)
    if "top" not in options:
        return call.group(0)
    lines = "\n" * call.group(0).count("\n")  # every later line keeps its number for the checker's hints
    return f"{call.group(1)}({options.get('left', '0')}, {options['top']}){lines}"


def tidy(page: str) -> str:
    """The page (stripped) with each scroll call that takes `{top, left, behavior}` options rewritten to positions:
    the exact text the checker judges and the repair is shown, so a hint's line number points at the same line."""
    return _SCROLL_CALL.sub(_positional, page.strip())


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
    data = tidy(reply).encode("utf-8", "replace")
    result = check_website(data)
    if not result.ok:
        raise DeliverableRefused("website_invalid", _violations(data, result))
    return WebsiteHtml(media_type="text/html", content=data)


def _violations(data: bytes, first: WebsiteCheck) -> str:
    """The checker's code and line for up to MAX_HINTS problems, so the one repair can fix them all (the checker stops
    at the first): each failing line is blanked and the file checked again, while the next problem is further down."""
    found, lines, result = [f"{first.code}, line {first.line}"], data.split(b"\n"), first
    while len(found) < MAX_HINTS and isinstance(result.line, int) and 0 < result.line <= len(lines):
        lines[result.line - 1] = b""
        after = check_website(b"\n".join(lines))
        if after.ok or not isinstance(after.line, int) or after.line <= result.line:
            break
        result = after
        found.append(f"{result.code}, line {result.line}")
    return "; ".join(found)


def degraded(reply: str) -> bytes:
    """The Markdown the person gets when no checked page could be made: prose as written, a page as a code block."""
    if "<" not in reply:
        return reply.encode("utf-8")
    code = reply[:100_000]
    fence = "`" * max(3, _longest_ticks(code) + 1)
    note = "Tilo did not make this page into a website, so it is shown as text and never run."
    return f"{note}\n\n{fence}html\n{code}\n{fence}\n".encode()


def _longest_ticks(text: str) -> int:
    longest = run = 0
    for char in text:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    return longest
