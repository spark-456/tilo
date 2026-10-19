"""FR-MTG-13: replies from recorded meeting data only, never outside knowledge."""

import re
from typing import Any

from .people import _names

DECLINE = "I can only cover this meeting's agenda, minutes so far, or your own recorded meeting items."


def scoped_answer(text: str, bot_name: str, speaker: str, state: Any) -> str:
    words = re.findall(r"[a-z']+", text.lower())
    names = _names(bot_name)
    while words and words[0] in names | {"hey", "hello", "hi", "please"}:
        words.pop(0)
    while words and words[-1] in names | {"please"}:
        words.pop()
    request = " ".join(words)
    request = re.sub(
        r"^(?:what is|what are|what's|show|list|read|summarize|summarise|recap|tell me|give me)\s+(?:me\s+)?(?:the\s+)?",
        "",
        request,
    )
    if request in {"agenda", "meeting agenda", "agenda today", "next", "next agenda item"}:
        items = [i.title for i in state.items if request not in {"next", "next agenda item"} or i.status != "covered"]
        return "Agenda: " + "; ".join(items[:3])[:300] + "." if items else "No agenda items remain."
    if request in {"minutes", "meeting minutes", "minutes so far", "meeting so far", "meeting summary"}:
        summary = " ".join(state.context_summary.split())
        return f"Minutes so far: {summary[:300]}" if summary else "No minutes have been recorded yet."
    if request in {"my items", "my tasks", "my action items", "items assigned to me"}:
        owner = speaker.removesuffix(" (chat)").strip()
        if not owner or owner == "?":
            return DECLINE
        items = [a.text for a in state.action_items if a.owner == owner]
        return (
            "Your recorded meeting items: " + "; ".join(items[:3])[:300] + "."
            if items
            else "No meeting items are recorded for you."
        )
    return DECLINE
