"""Teach Tilo never ends on an error page (P0-SKILLS-TEACH): a model reply is read leniently, and when it still
cannot be used the person gets an editable draft built by code from their own words.

Three things live here, all pure functions:
- `parse_json`: the reply as data, tolerating code fences and words around one JSON object.
- `tidy_capture` / `tidy_version`: reshape a reply the way a model really writes it (steps as plain strings, a long or
  multi-line step, a missing verb, a tool written `tool.action`, a question with the wrong number of options) into the
  closed shape the routes check. Nothing a model adds survives: unknown keys are dropped here, and `must_ask`,
  `ask_first` and the estimates are code's alone (the routes never read them from a reply).
- `split_steps` / `fallback_plan`: the draft when the model gave nothing usable. The steps are the person's own words
  split into lines; each is bound to a read pair of a connected tool by the words in `config/skills.yaml`
  `capture.fallback`, else it is a text step (`writer.compose`). Never invented text, never a send.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^\s*```[a-zA-Z0-9]*\s*|\s*```\s*$")
_SPACE = re.compile(r"\s+")
_LIST_MARK = re.compile(r"^\s*(?:[-*•–]+|\(?\d{1,2}[.)])\s+")
_SPLIT = re.compile(r"(?<=[.!?;])\s+|\s*;\s*|,\s*then\s+|\s+(?:and\s+)?then\s+|\s+after that\s+", re.I)
# a leading "Every Monday,"
_WHEN = re.compile(r"^(?:every|each|on|at|daily|weekly|monthly|when|whenever)\b[^,]*,\s*", re.I)
_CLAUSE = re.compile(r",\s*(?:and\s+)?|\s+and\s+", re.I)
_VERBS = ("read", "draft", "write", "send", "post", "pay", "delete", "share", "book")
STEP_CHARS = 200
MAX_STEPS = 12
NO_EXAMPLE_WORDS = "Repeat the work shown in the example"


def parse_json(text: str) -> Any:
    """The reply as data: plain JSON, JSON in a code fence, or the outermost braces inside other words."""
    cleaned = _FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def line(value: Any, limit: int = STEP_CHARS) -> str | None:
    """One plain line of at most `limit` characters (cut at a word), or None when nothing is left."""
    if not isinstance(value, str):
        return None
    text = _SPACE.sub(" ", _LIST_MARK.sub("", value.replace("\r", "\n"))).strip()
    if len(text) > limit:
        cut = text[: limit - 1].rsplit(" ", 1)[0] if " " in text[: limit - 1] else text[: limit - 1]
        text = cut.rstrip(" ,;:-") + "…"
    return text or None


def _step_text(item: Any) -> str | None:
    if isinstance(item, dict):
        for key in ("text", "step", "description", "title", "name"):
            if isinstance(item.get(key), str):
                return line(item[key])
        return None
    return line(item)


def _items(doc: Any) -> list[Any]:
    if isinstance(doc, dict):
        for key in ("steps", "plan", "plan_steps", "captured_steps"):
            if isinstance(doc.get(key), list):
                return doc[key]
        return []
    return doc if isinstance(doc, list) else []


def tidy_capture(doc: Any) -> dict[str, Any]:
    texts = [t for t in (_step_text(i) for i in _items(doc)) if t]
    return {"steps": [{"text": t} for t in dict.fromkeys(texts)][:MAX_STEPS]}


def _verb(value: Any, tool: str) -> str:
    folded = value.strip().lower() if isinstance(value, str) else ""
    return folded if folded in _VERBS else ("draft" if tool == "none" else "read")


def _question(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = line(raw.get("text"))
    options = raw.get("options")
    if text is None or not isinstance(options, list):
        return None
    kept = [o for o in (line(o, 60) for o in options) if o]
    kept = list(dict.fromkeys(kept))[:4]
    return {"text": text, "options": kept} if len(kept) >= 2 else None


def tidy_version(doc: Any) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    for item in _items(doc):
        text = _step_text(item)
        if text is None:
            continue
        data = item if isinstance(item, dict) else {}
        tool = data.get("tool") if isinstance(data.get("tool"), str) else "none"
        action = data.get("action") if isinstance(data.get("action"), str) else "none"
        tool, action = tool.strip()[:64] or "none", action.strip()[:64] or "none"
        rows.append({"text": text, "tool": tool, "action": action, "verb": _verb(data.get("verb"), tool.lower())})
    body = doc if isinstance(doc, dict) else {}
    out: dict[str, Any] = {"steps": rows[:MAX_STEPS], "question": _question(body.get("question"))}
    if isinstance(body.get("inputs"), list):
        out["inputs"] = [i for i in body["inputs"] if isinstance(i, dict)][:8]
    if isinstance(body.get("hosts"), list):
        out["hosts"] = [h for h in body["hosts"] if isinstance(h, str)][:10]
    return out


def split_steps(text: str, *, example: bool = False) -> list[str]:
    """The person's own words as steps: one per line, list item or sentence (and per "then"); at most 12. An example
    with no words has one honest placeholder to edit."""
    found: list[str] = []
    for raw in text.replace("\r", "\n").split("\n"):
        for part in _SPLIT.split(raw):
            step = line(part.strip().rstrip(".;,"))
            if step and len(step) >= 3:
                found.append(step)
    found = list(dict.fromkeys(found))[:MAX_STEPS]
    if len(found) == 1:  # one long sentence: its commas and "and" are the natural parts, a lone clause is not a step
        parts = [line(p.strip().rstrip(".;,")) for p in _CLAUSE.split(_WHEN.sub("", found[0]))]
        clauses = [p for p in parts if p and len(p.split()) >= 2]
        if len(clauses) >= 2:
            found = list(dict.fromkeys(clauses))[:MAX_STEPS]
    if not found and example:
        return [NO_EXAMPLE_WORDS]
    return found


def fallback_plan(
    steps: list[str], hints: dict[str, dict[str, Any]], usable: list[str], allow: dict[str, frozenset[str]]
) -> list[dict[str, str]]:
    """One plan row per captured step: a read pair of a usable tool when the step's words name it, else a text step."""
    rows: list[dict[str, str]] = []
    for text in steps:
        words = set(re.findall(r"[a-z]+", text.lower()))
        row = {"text": text, "tool": "writer", "action": "compose", "verb": "draft"}
        for tool, hint in hints.items():
            action = hint.get("action")
            if tool in usable and action in allow.get(tool, frozenset()) and words & set(hint.get("words", ())):
                row = {"text": text, "tool": tool, "action": action, "verb": "read"}
                break
        rows.append(row)
    return rows
