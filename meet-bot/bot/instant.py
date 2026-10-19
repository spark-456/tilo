"""Instant answers: questions about the meeting's own state are answered from the notes, with no model call.

"What's on the agenda?", "what action items do we have?", "how much time is left?", "who's here?", "what did we decide?"
are asked constantly and the answer is already in the tracked state, so waiting on a language model is pure delay.
Matching is deliberately strict: anything that does not clearly fit falls through to the model.
"""

from __future__ import annotations

import re
from typing import Any

_WORDS = re.compile(r"[a-z']+")


def _has(text: str, *phrases: str) -> bool:
    return any(p in text for p in phrases)


def _short(s: str, n: int = 70) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def instant_answer(question: str, state: Any, elapsed_s: float, duration_s: float, present: list[str]) -> str | None:
    q = " ".join(_WORDS.findall(question.lower()))
    if not q or len(q.split()) > 16:
        return None
    ask = q.split()[0] in {
        "what",
        "whats",
        "what's",
        "which",
        "how",
        "who",
        "whos",
        "where",
        "any",
        "are",
        "is",
        "do",
        "does",
        "can",
        "tell",
        "list",
        "give",
    }
    if not ask:
        return None

    if _has(
        q,
        "how much time",
        "time left",
        "minutes left",
        "time remaining",
        "how long is left",
        "how long do we have",
        "how long left",
    ):
        left = max(0.0, duration_s - elapsed_s)
        return (
            f"About {max(1, round(left / 60))} minutes left of {round(duration_s / 60)}."
            if left > 30
            else "We are at the end of the planned time."
        )

    if _has(
        q,
        "who is here",
        "who's here",
        "whos here",
        "who is in the meeting",
        "who is in the call",
        "who is on the call",
        "who is attending",
        "who else is here",
    ):
        return f"In the meeting: {_join(present)}." if present else "I don't see anyone else in the meeting yet."

    if "agenda" in q and not _has(q, "add ", "change", "update", "remove"):
        items = state.items
        covered = [i for i in items if i.status == "covered"]
        current = [i for i in items if i.status == "in_progress"]
        todo = [i for i in items if i.status == "not_started"]
        if _has(q, "left", "remaining", "still to", "not covered", "next", "yet"):
            return (
                f"Still to cover: {_join([_short(i.title, 40) for i in items if i.status != 'covered'])}."
                if todo or current
                else "Everything on the agenda has been covered."
            )
        parts = []
        if current:
            parts.append(f"we're on {_join([_short(i.title, 40) for i in current])}")
        parts.append(f"{len(covered)} of {len(items)} items covered")
        if todo:
            parts.append(f"still to come: {_join([_short(i.title, 40) for i in todo])}")
        return f"Today's agenda has {len(items)} items: " + ", ".join(parts) + "."

    if _has(q, "action item", "action items", "to do", "todo", "tasks", "follow up", "follow ups", "next steps"):
        acts = state.action_items
        if not acts:
            return "No action items recorded yet."
        shown = [f"{_short(a.text, 50)} ({a.owner or 'no owner yet'})" for a in acts[:3]]
        more = f", and {len(acts) - 3} more" if len(acts) > 3 else ""
        return f"{len(acts)} action item{'s' if len(acts) != 1 else ''}: {'; '.join(shown)}{more}."

    if _has(q, "decision", "decide", "decided", "agreed"):
        d = state.decisions
        if not d:
            return "No decisions recorded yet."
        return f"{len(d)} decision{'s' if len(d) != 1 else ''} so far: {'; '.join(_short(x, 70) for x in d[:3])}."

    return None
