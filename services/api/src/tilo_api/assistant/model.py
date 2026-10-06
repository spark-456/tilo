"""The model fallback (section 8, FR-PA-14, FR-PA-17): asked only when no rule read the question, once, with no repair
call. The model is shown the question and the person's own plate rows as delimited data and may only reply with a
fact intent id, a `navigate` action or `decline`. This module screens, asks and parses; it decides nothing: the core
vets every action against the oracle, so a reply is never trusted. No person id is ever put in a request."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.interfaces import GenerateRequest, SafetyProvider
from tilo_providers.prompts import DEFAULT_PROMPTS_ROOT, load_prompt, neutralise_marker
from tilo_providers.router import BudgetExceededError, Router, RouterAttempt, RouterError

from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.core import Choice, MenuRow, ModelAsk, ModelDecision

_TEMPLATES = ("route_system.md", "route_task.md")
_NOT_SENT = {"BudgetExceededError", "TokenCapExceededError"}  # attempts the router refused before sending


class AssistantModelUnavailable(Exception):
    """The role is missing, uncapped or unpriced, so the panel answers by rules only."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found = dict(pairs)
    if len(found) != len(pairs):
        raise ValueError("duplicate key")
    return found


def _no_constant(name: str) -> Any:
    raise ValueError("not JSON")


def parse_decision(text: object, *, intents: frozenset[str]) -> tuple[Choice, str | None, Mapping[str, Any] | None]:
    """Exactly three reply shapes with exact key sets and exact JSON types; anything else is `dropped`."""
    dropped: tuple[Choice, None, None] = ("dropped", None, None)
    if type(text) is not str:
        return dropped
    try:
        doc = json.loads(text, object_pairs_hook=_pairs, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        return dropped
    if type(doc) is not dict:
        return dropped
    choice, keys = doc.get("choice"), set(doc)
    if keys == {"choice", "intent"} and choice == "intent" and type(doc["intent"]) is str and doc["intent"] in intents:
        return "intent", doc["intent"], None
    if keys == {"choice", "action"} and choice == "navigate" and type(doc["action"]) is dict:
        return "navigate", None, doc["action"]
    if keys == {"choice"} and choice == "decline":
        return "decline", None, None
    return dropped


def _data(text: str) -> str:
    """Untrusted text closes neither of the two blocks of one request, whichever it was written for."""
    return neutralise_marker(neutralise_marker(text, "QUESTION"), "ROWS")


def _row_line(row: MenuRow) -> str:
    title = " ".join(row.title.split()) if row.title else "(no title)"
    due = row.due or "-"
    return f"{row.ref.kind} {row.ref.id} | {row.reason} | {row.group} | {due} | {_data(title)}"


class ModelDecider:
    def __init__(
        self, *, router: Router, providers: ProvidersConfig, safety: SafetyProvider, config: AssistantConfig
    ) -> None:
        role = providers.roles.get(config.model["role"])
        if role is None or role.max_input_tokens is None or role.max_output_tokens is None:
            raise AssistantModelUnavailable("the assistant role is missing or has no token caps")
        candidates = list(role.cascade or dict.fromkeys(p for p in (role.primary, role.fallback) if p))
        try:
            worst = [
                providers.credits((role.max_input_tokens * quote.input + role.max_output_tokens * quote.output) / 1e6)
                for quote in (providers.price(p) for p in candidates)
            ]
        except ProviderConfigError:
            raise AssistantModelUnavailable("a candidate of the assistant role has no price") from None
        self._router, self._safety, self._config, self._role = router, safety, config, config.model["role"]
        self._worst = max(worst)
        texts = [(DEFAULT_PROMPTS_ROOT / "assistant" / name).read_text(encoding="utf-8") for name in _TEMPLATES]
        pinned = {"templates": texts, "candidates": candidates, "caps": [role.max_input_tokens, role.max_output_tokens]}
        self.version = hashlib.sha256(json.dumps(pinned, sort_keys=True).encode("utf-8")).hexdigest()
        self._intents = frozenset(f.id for f in config.facts)

    def worst_case_credits(self) -> float:
        """The dearest candidate of the role at both token caps: what one call may cost at most."""
        return self._worst

    def _request(self, ask: ModelAsk) -> tuple[GenerateRequest, str]:
        facts = "\n".join(f"{f.id}: {f.describe}" for f in self._config.facts)
        screens = [f"{r.route}: {r.describe}" for r in self._config.navigate]
        screens += [f"{route}: {text}" for route, text in self._config.answer["target_screens"].items()]
        context = "none" if ask.context is None else f"{ask.context.kind} {ask.context.id}"
        system = load_prompt("assistant", "route_system.md", {"intents": facts, "routes": "\n".join(screens)})
        task = load_prompt(
            "assistant",
            "route_task.md",
            {
                "question": _data(ask.question),
                "screen": ask.screen or "none",
                "context": context,
            },
        )
        lines = [_row_line(row) for row in ask.menu.rows]
        if ask.menu.context is not None:
            lines.append(f"selected: {ask.menu.context.ref.kind} {ask.menu.context.ref.id}")
        block = "\n".join(["<<<ROWS", *lines, "ROWS>>>"])
        return GenerateRequest(system=system, prompt=task, json_mode=True), block

    @staticmethod
    def _sent(attempts: list[RouterAttempt]) -> list[RouterAttempt]:
        return [a for a in attempts if a.error_type not in _NOT_SENT]

    def _decision(
        self, choice: Choice, attempts: list[RouterAttempt], prompt: str | None, credits: float = 0.0, **more: Any
    ) -> ModelDecision:
        sent, last = self._sent(attempts), attempts[-1] if attempts else None
        return ModelDecision(
            choice,
            model_calls=len(sent),
            credits=credits,
            profile=last.profile_id if sent and last else None,
            tokens_in=last.tokens_in if sent and last else None,
            tokens_out=last.tokens_out if sent and last else None,
            latency_ms=int(round(last.latency_ms)) if sent and last else None,
            prompt=prompt if sent else None,
            **more,
        )

    def decide(self, ask: ModelAsk, *, budget: float | None) -> ModelDecision:
        try:
            flagged = bool(self._safety.check(ask.question)["flagged"])
        except Exception:
            return ModelDecision("unavailable")  # an outage is never "not flagged" (fail closed)
        if flagged:
            return ModelDecision("flagged")
        request, block = self._request(ask)
        shown = f"{request.system}\n\n{request.prompt}\n\n{block}"
        try:
            result = self._router.generate(self._role, request, budget=budget, tool_outputs=[block])
        except BudgetExceededError as error:
            return self._decision("budget", error.attempts, shown)
        except RouterError as error:  # a cap the fixed text alone exceeds, every candidate failing, a bad request
            return self._decision("unavailable", error.attempts, shown)
        sent = f"{request.system}\n\n{result.request.prompt}"
        if result.outcome != "ok" or result.response is None:
            return self._decision("unavailable", result.attempts, sent)
        credits = 0.0 if budget is None or result.budget is None else max(0.0, budget - result.budget)
        text = result.response.text
        cap = self._config.model["max_output_chars"]
        raw = text[:cap] if isinstance(text, str) else None
        if not isinstance(text, str) or len(text) > cap:
            return self._decision("dropped", result.attempts, sent, credits, raw=raw)
        choice, intent, action = parse_decision(text, intents=self._intents)
        return self._decision(choice, result.attempts, sent, credits, intent=intent, action=action, raw=raw)
