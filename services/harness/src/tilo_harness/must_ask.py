"""Must-ask rules (FR-AGT-05; PRD 8.3, 8.6; BQ-198, BQ-199).

Before a unit's work runs, `MustAsk.assess` decides whether a person must be asked first. Two
layers, in this order, and only the first is authority:

1. Deterministic rules, no model: a unit that has failed `retries.max_attempts` times asks
   (`repeated_failure`), and a unit whose `actions` include a type above T1 in `config/autonomy.yaml`
   (or one the table does not list, which is T3) asks (`sensitive_step`) unless the type is T2 and an
   autonomy policy covers it. A T3 type is never waved through by coverage.
2. The model of the unit's role judges an ambiguous brief, a trade-off, or a sensitive step code cannot
   see. It can add a question and can never remove one a rule requires. A reply that cannot be read, or
   a provider that fails, asks (`ambiguous_brief`): when the harness cannot tell, a person decides.

`raise_question` writes the Specialist -> Lead -> Director chain and the Lead's question to a person
through the one `WorldWriter`, and hands a `needs_you` card to `card_sink` before any of the chain is written.
A question's answer never authorises a side effect: that stays with the outbox and the policy engine.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from tilo_policy.tiers import RiskTable, load_risk_table
from tilo_providers.interfaces import GenerateRequest, ModelProvider
from tilo_providers.prompts import load_prompt

from tilo_harness.config import AgentsConfig
from tilo_harness.untrusted import neutralise
from tilo_harness.writer import format_ts, new_ulid

ROLE = "specialist"  # prompts/specialist/must_ask_*.md
QUESTION_TIMEOUT_S = 3600  # BQ-212: PRD 10.2 gives a card a timeout but no number
_MODEL_REASONS = ("ambiguous_brief", "trade_off", "sensitive_step")
_WHY_IT_MATTERS = {
    "ambiguous_brief": "A wrong guess would waste the run, so a person decides.",
    "trade_off": "It gives up something nobody agreed to give up, so a person decides.",
    "sensitive_step": "It touches money, personal data, legal terms or people outside Tilo.",
    "repeated_failure": "Trying again without a person looking would spend more for the same result.",
}
_SENSITIVE = (  # (question template, options, suggested index, reason for the suggestion)
    "This step acts outside Tilo ({actions}). Prepare it?",
    ("Hold this step", "Prepare it"),
    0,
    "Nothing outside Tilo changes until you decide; sending still needs approval.",
)
_FAILED = (
    "This step failed {count} times. How should it go on?",
    ("Try once more", "Skip this step", "Stop here"),
    2,
    "Three failures in a row; stopping costs nothing and can be undone.",
)
_UNREADABLE = (
    "I could not tell whether this step needs your input. Should it go ahead?",
    ("Hold this step", "Go ahead"),
    0,
    "When Tilo cannot tell, it asks instead of guessing.",
)


@dataclass(frozen=True)
class Ask:
    reason: str
    question: str
    options: tuple[str, ...]
    suggested: int
    why: str


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _canned(reason: str, template: tuple[Any, ...], **fields: Any) -> Ask:
    question, options, suggested, why = template
    return Ask(reason, _clip(question.format(**fields), 140), tuple(options), suggested, why)


def _parse(text: Any) -> Ask | None:
    """None when the reply says no question is needed, an Ask when it asks; ValueError when unreadable."""
    reply = json.loads(text) if isinstance(text, str) else None
    if not isinstance(reply, dict) or not isinstance(reply.get("ask"), bool):
        raise ValueError("reply is not an ask object")
    if reply["ask"] is False:
        return None
    options, suggested = reply.get("options"), reply.get("suggested")
    valid = (
        reply.get("reason") in _MODEL_REASONS
        and isinstance(reply.get("question"), str)
        and bool(reply["question"].strip())
        and isinstance(options, list)
        and 2 <= len(options) <= 3
        and all(isinstance(o, str) and 1 <= len(o) <= 20 for o in options)
        and len(set(options)) == len(options)
        and isinstance(suggested, int)
        and not isinstance(suggested, bool)
        and 0 <= suggested < len(options)
        and isinstance(reply.get("why"), str)
        and 1 <= len(reply["why"]) <= 200
    )
    if not valid:
        raise ValueError("ask reply has the wrong shape")
    question = _clip(reply["question"].strip(), 140)
    return Ask(reply["reason"], question, tuple(cast(list[str], options)), cast(int, suggested), reply["why"])


class MustAsk:
    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        *,
        config: AgentsConfig,
        card_sink: Callable[[dict[str, Any]], None],
        owner: str = "u_owner",
        covered_actions: Iterable[str] = (),
        risk_table: RiskTable | None = None,
    ) -> None:
        self._providers = providers
        self._max_attempts = config.retries.max_attempts
        self._card_sink = card_sink
        self._owner = owner
        self._covered = frozenset(covered_actions)
        self._table = risk_table if risk_table is not None else load_risk_table()
        self._system = load_prompt(ROLE, "must_ask_system.md")

    def _uncovered(self, unit: Mapping[str, Any]) -> list[str]:
        actions = unit.get("actions")
        if not isinstance(actions, list):
            return ["unknown"]  # malformed: fail closed
        out = []
        for action in actions:
            tier = self._table.tier_of(action, []) if isinstance(action, str) else "T3"
            if tier == "T3" or (tier == "T2" and action not in self._covered):
                out.append(str(action))
        return out

    async def assess(self, unit: Mapping[str, Any], *, failures: int = 0) -> Ask | None:
        if failures >= self._max_attempts:
            return _canned("repeated_failure", _FAILED, count=failures)
        uncovered = self._uncovered(unit)
        if uncovered:
            return _canned("sensitive_step", _SENSITIVE, actions=_clip(", ".join(uncovered), 60))
        try:
            reply = await asyncio.to_thread(self._providers[unit["role"]].generate, self._request(unit))
            return _parse(reply.text)
        except Exception:  # unreadable reply, provider outage or missing role: ask rather than guess (BQ-199)
            return _canned("ambiguous_brief", _UNREADABLE)

    def _request(self, unit: Mapping[str, Any]) -> GenerateRequest:
        fields = {
            "unit_type": unit["unit_type"],
            "title": unit["title"],
            "actions": ", ".join(unit["actions"]) or "none",
        }
        prompt = load_prompt(ROLE, "must_ask_task.md", {k: neutralise(v, limit=200) for k, v in fields.items()})
        return GenerateRequest(system=self._system, prompt=prompt, json_mode=True, max_output_tokens=400)

    def raise_question(
        self,
        ask: Ask,
        *,
        writer: Any,
        unit: Mapping[str, Any],
        specialist: str,
        lead: str,
        director: str,
        district: str | None = None,
        cause: str | None = None,
    ) -> dict[str, Any]:
        level, building = _site(writer.layout, unit["id"], district)
        card = self._card(ask, writer, specialist, building)
        self._card_sink(card)  # first: a sink that fails emits no question, so no event names a card nobody holds
        at = {"level": level, "district": district}
        helped = writer.emit(
            type="agent.help_requested",
            actor=specialist,
            target=lead,
            summary="The agent asked its Lead for help.",
            data={"unit": unit["id"]},
            cause=cause,
            **at,
        )
        escalated = writer.emit(
            type="agent.escalated",
            actor=lead,
            target=director,
            summary="The Lead passed a question up to the Director.",
            data={"reason": ask.reason},
            cause=helped["id"],
            **at,
        )
        writer.emit(
            type="question.routed",
            actor=lead,
            target=self._owner,
            summary="The Lead asked the owner a question.",
            data={"card_id": card["id"], "domain": None},  # no Team Lead configured: owner fallback (FR-AGT-06)
            cause=escalated["id"],
            **at,
        )
        return card

    def _card(self, ask: Ask, writer: Any, agent: str, building: str) -> dict[str, Any]:
        now = writer.now()
        options = [
            {
                "id": f"o{i + 1}",
                "label": label,
                "suggested": i == ask.suggested,
                **({"reason": ask.why} if i == ask.suggested else {}),
                "irreversible": False,
            }
            for i, label in enumerate(ask.options)
        ]
        return {
            "id": new_ulid(now),
            "world_id": writer.world_id,
            "run_id": writer.run_id,
            "kind": "needs_you",
            "rung": "needs_you",
            "header": {"building": building, "agent": agent},
            "what_happened": ask.question,
            "why_it_matters": _WHY_IT_MATTERS[ask.reason],
            "options": options,
            "add_context": True,
            "actions": ["show_me", "snooze", "delegate"],
            "answer_channels": ["web", "mobile_web", "whatsapp", "email"],
            "created_at": format_ts(now),
            "timeout": QUESTION_TIMEOUT_S,
            "safe_default": options[ask.suggested]["id"],  # reversible by schema; BQ-212
            "gate": None,
            "consent": None,
        }


def _site(layout: Mapping[str, Any], unit_id: str, district: str | None) -> tuple[str | None, str]:
    """The level and the building the unit works in (its own, else its district's first)."""
    for level in layout["semantic"]["levels"]:
        for found in level["districts"]:
            own = [b["id"] for b in found["buildings"] if unit_id in b.get("plan_units", [])]
            if found["id"] == district or (district is None and own):
                return level["id"], (own or [found["buildings"][0]["id"]])[0]
    raise ValueError(f"unit {unit_id!r} is not in the layout")
