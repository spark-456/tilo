"""Offline stand-ins for the model, used by `run-mock` and the tests. No network, fully deterministic."""

from __future__ import annotations

import json
import re
from typing import Any

_STOP = {"and", "the", "for", "with", "review", "plan", "next", "that", "this", "from"}


def _input(prompt: str) -> dict[str, Any]:
    body = prompt.split("INPUT_JSON:\n", 1)[1].split("\n\nYour previous reply", 1)[0]
    return json.loads(body)


class ScriptedLLM:
    """Returns queued replies (strings or dicts) in order; the last one repeats. Records every call."""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return r if isinstance(r, str) else json.dumps(r)


class KeywordStubLLM:
    """Crude but deterministic 'analyst': keyword hits drive statuses, regexes pull decisions and action items.

    It never writes a chat_message: proving the chat policy in code is what supplies the wording.
    """

    _WILL = re.compile(r"\b(?P<who>[A-Z][a-z]+) will (?P<what>[^.?!]+?)(?: by (?P<due>[A-Za-z0-9 ]+?))?\s*[.?!]?$")
    _ILL = re.compile(r"\bI(?:'ll| will) (?P<what>[^.?!]+?)(?: by (?P<due>[A-Za-z0-9 ]+?))?\s*[.?!]?$")
    _SHOULD = re.compile(r"\bwe should (?P<what>[^.?!]+?)\s*[.?!]?$", re.I)
    _DECIDE = re.compile(r"we decided|decision:|let's go with|^agreed", re.I)

    def generate(self, system: str, prompt: str) -> str:
        data = _input(prompt)
        lines = data["transcript_recent"]
        text = " ".join(f"{u['text']}" for u in lines).lower()
        prev = {i["title"]: i["status"] for i in data["current_state"]["agenda_items"]}
        titles = [a["title"] for a in data["agenda"]]
        hits = []
        for t in titles:
            words = [w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) >= 4 and w not in _STOP]
            hits.append(sum(text.count(w) for w in words))
        out_items = []
        for n, t in enumerate(titles):
            later_active = any(h > 0 for h in hits[n + 1 :])
            status = (
                "covered"
                if hits[n] >= 3 or (hits[n] > 0 and later_active)
                else "in_progress"
                if hits[n] > 0
                else prev[t]
            )
            out_items.append({"title": t, "status": status})
        decisions, actions = [], []
        for u in lines:
            for sent in re.split(r"(?<=[.?!])\s+", u["text"]):
                if self._DECIDE.search(sent):
                    decisions.append(sent.strip())
                elif m := self._WILL.search(sent):
                    actions.append({"text": m["what"], "owner": m["who"], "due": m["due"]})
                elif m := self._ILL.search(sent):
                    actions.append({"text": m["what"], "owner": u["speaker"], "due": m["due"]})
                elif m := self._SHOULD.search(sent):
                    actions.append({"text": m["what"], "owner": None, "due": None})
        return json.dumps(
            {
                "agenda_items": out_items,
                "decisions": decisions,
                "action_items": actions,
                "open_questions": [],
                "drift_note": None,
                "chat_message": None,
            }
        )
