"""Parsing the Meet chat panel's plain text into (sender, text) messages. Pure, no browser.

Meet's chat shows other people's messages as a "Name  1:50 PM" header line followed by the text, and your own as a
bare time line. Formats can shift, so this is a heuristic; the bot saves the real panel HTML to debug/chat_panel.html
on first use so the parser can be checked against it (see tests/fixtures/README.md).
"""

from __future__ import annotations

import re

_TIME = re.compile(r"\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)?")
_HEADER = re.compile(rf"^(?P<name>.+?)\s+(?P<time>{_TIME.pattern})$")
_ONLY_TIME = re.compile(rf"^{_TIME.pattern}$")
_NOISE = (
    "in-call messages",
    "let participants send messages",
    "continuous chat is turned",
    "messages will not be saved",
    "messages can only be seen",
    "you can pin a message",
    "hover over a message to pin",
    "send a message",
    "pin message",
    "pinned",
    "learn more",
)


def _noise(line: str) -> bool:
    low = line.lower()
    return any(low.startswith(n) or low == n for n in _NOISE)


def parse_chat_panel(panel_text: str) -> list[tuple[str, str]]:
    """[(sender, text)] in order. Own messages (no name in the header) come back with sender "You"."""
    out: list[tuple[str, str]] = []
    sender: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal sender, body
        if sender is not None and body:
            out.append((sender, " ".join(body).strip()))
        sender, body = None, []

    for raw in panel_text.splitlines():
        line = raw.strip()
        if not line or _noise(line):
            continue
        if _ONLY_TIME.match(line):
            flush()
            sender = "You"
        elif (m := _HEADER.match(line)) and len(m.group("name")) <= 60:
            flush()
            sender = m.group("name").strip()
        elif sender is not None:
            body.append(line)
    flush()
    return out
