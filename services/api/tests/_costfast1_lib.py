"""Helpers for the COST-FAST-1 acceptance tests (Quick / Thinking mode of `POST /intake`; see API_COST_FAST_1.md).

Named `_costfast1_lib` for the same global-bare-module-name reason as `_clint1_lib.py`.

Nothing here is business logic. `QuickRig` wires the real `tilo_api.app` (through `_clint1_lib.Flow`) to: a real
`tilo_providers.router.Router` over the shipped `config/models.yaml` and `config/prices.yaml`, whose every profile is
one scripted provider (no network, no live mode); a recording wrapper around that router (which role was called, with
what request and budget); a safety spy that shares one timeline with the router; a fresh artifact store, flag store
and FR-PA-19 allowance ledger. The scripted provider answers by what the request asks for:

* a response schema with `ambiguous_fields` is the Director's brief, one with `approaches` the approaches;
* any other request in JSON mode is the Quick classifier fallback (`classifier_reply`);
* anything else is the Quick answer (`answer`, plain text).
"""

from __future__ import annotations

import json
import pathlib
import threading
from dataclasses import dataclass
from typing import Any

from _api_contracts_lib import INJECTION_PHRASE
from _clint1_lib import APPROACHES_REPLY, brief_reply

SIMPLE_TEXT = "What is the capital of France?"
ANSWER = "The capital of France is Paris."

# The closed set of reasons a switch offer may carry (API_COST_FAST_1.md, "Reasons").
REASONS = frozenset(
    {"attachments", "side_effect", "deliverable", "needs_tools", "multi_step", "too_long", "scenario", "unclear"}
)
OFFER_KEYS = {"mode", "outcome", "reason"}
ANSWER_KEYS = {"mode", "outcome", "text", "cost"}
COST_KEYS = {"model_calls", "credits", "saved_credits"}


@dataclass
class Call:
    role: str
    request: Any
    budget: float | None

    @property
    def schema_props(self) -> dict[str, Any]:
        return (self.request.response_schema or {}).get("properties", {})

    @property
    def is_director(self) -> bool:
        return self.role == "director"

    @property
    def is_approaches(self) -> bool:
        return "approaches" in self.schema_props

    @property
    def is_classifier(self) -> bool:
        return self.role == "assistant" and bool(self.request.json_mode or self.request.response_schema)

    @property
    def is_answer(self) -> bool:
        return self.role == "assistant" and not self.is_classifier

    @property
    def sent_text(self) -> str:
        return f"{self.request.system or ''}\n{self.request.prompt}"


class QuickProvider:
    """One scripted provider shared by every profile of the router."""

    def __init__(self, profile_id: str, rig: QuickRig) -> None:
        self.profile_id, self._rig = profile_id, rig

    def generate(self, request: Any) -> Any:
        from tilo_providers.interfaces import GenerateResponse  # noqa: PLC0415

        rig = self._rig
        props = (request.response_schema or {}).get("properties", {})
        usage = None
        with rig.lock:
            rig.provider_requests.append(request)
            if "ambiguous_fields" in props:
                text = json.dumps(rig.brief)
            elif "approaches" in props:
                text = json.dumps(rig.approaches)
            elif request.json_mode or request.response_schema is not None:
                text, usage = rig.classifier_reply, rig.classifier_usage
            else:
                rig.answers_made += 1
                if rig.fail is not None and (rig.fail_times is None or rig.fail_times > 0):
                    if rig.fail_times is not None:
                        rig.fail_times -= 1
                    raise rig.fail
                text = rig.answer(rig.answers_made) if callable(rig.answer) else rig.answer
                usage = rig.answer_usage
        reported = (
            None if usage is None else {"input_tokens": usage[0], "output_tokens": usage[1], "total_tokens": sum(usage)}
        )
        return GenerateResponse(text=text, profile_id=self.profile_id, usage=reported)

    def stream(self, request: Any):
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        fixed = self._rig.fixed_tokens
        return fixed if fixed is not None else max(1, len(text) // 4)

    def capabilities(self) -> set[Any]:
        from tilo_providers.interfaces import Capability  # noqa: PLC0415

        return {Capability.JSON}

    def price(self) -> Any:
        from tilo_providers.interfaces import PriceQuote  # noqa: PLC0415

        return PriceQuote(input=0.0, output=0.0)


class SpyRouter:
    """Wraps a real Router and records the role, request and budget of every call."""

    def __init__(self, inner: Any, rig: QuickRig) -> None:
        self._inner, self._rig = inner, rig

    def generate(self, role_id: str, request: Any, **kwargs: Any) -> Any:
        self._rig.record(role_id, request, kwargs.get("budget"))
        return self._inner.generate(role_id, request, **kwargs)

    def stream(self, role_id: str, request: Any, **kwargs: Any) -> Any:
        self._rig.record(role_id, request, kwargs.get("budget"))
        return self._inner.stream(role_id, request, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def make_timeline_safety(rig: QuickRig) -> Any:
    from tilo_providers.errors import ProviderError  # noqa: PLC0415
    from tilo_providers.interfaces import SafetyProvider  # noqa: PLC0415

    class TimelineSafety(SafetyProvider):
        def _check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> Any:
            rig.timeline.append(("safety", text))
            rig.safety_texts.append(text)
            if rig.safety_down:
                raise ProviderError("the safety screen is down (fake)")
            flagged = INJECTION_PHRASE in text.upper()
            return {"flagged": flagged, "reason": "instruction aimed at the assistant" if flagged else None}

    return TimelineSafety()


class QuickRig:
    def __init__(self, flow: Any, repo_root: pathlib.Path, *, own_flags: bool = True, own_safety: bool = True) -> None:
        from tilo_api import app, deps  # noqa: PLC0415
        from tilo_api import intake as intake_module  # noqa: PLC0415
        from tilo_api.assistant.metering import InMemorySpendLedger  # noqa: PLC0415
        from tilo_metering.flags import InMemoryFlagStore  # noqa: PLC0415
        from tilo_planning.artifacts import InMemoryArtifactStore  # noqa: PLC0415
        from tilo_providers.config import load_providers_config  # noqa: PLC0415
        from tilo_providers.router import Router  # noqa: PLC0415

        self.flow, self.repo_root = flow, repo_root
        self.lock = threading.RLock()
        self.brief, self.approaches = brief_reply([]), APPROACHES_REPLY
        self.answer: Any = ANSWER
        self.answer_usage: tuple[int, int] | None = (400, 80)
        self.classifier_reply = json.dumps({"kind": "simple"})
        self.classifier_usage: tuple[int, int] | None = (300, 20)
        self.fail: Exception | None = None
        self.fail_times: int | None = None
        self.answers_made = 0
        self.fixed_tokens: int | None = None  # every count_tokens answers this: a pessimistic estimate
        self.calls: list[Call] = []
        self.provider_requests: list[Any] = []
        self.timeline: list[tuple[str, Any]] = []
        self.safety_texts: list[str] = []
        self.safety_down = False
        self.providers = load_providers_config(
            repo_root / "config" / "models.yaml", repo_root / "config" / "prices.yaml"
        )
        self.router = SpyRouter(
            Router(self.providers, provider_for_profile=lambda profile_id: QuickProvider(profile_id, self)), self
        )
        flow.router = self.router
        self.artifacts = InMemoryArtifactStore()
        self.allowance = InMemorySpendLedger()
        app.dependency_overrides[intake_module.get_store] = lambda: self.artifacts
        app.dependency_overrides[deps.get_spend_ledger] = lambda: self.allowance
        self.flags = InMemoryFlagStore() if own_flags else flow.flags
        self.safety = make_timeline_safety(self) if own_safety else flow.safety
        if own_flags:
            app.dependency_overrides[deps.get_flag_store] = lambda: self.flags
        if own_safety:
            app.dependency_overrides[intake_module.get_safety] = lambda: self.safety
        self.client = flow.client
        self.store = flow.store

    # --- what the router saw ---------------------------------------------------------------------

    def record(self, role: str, request: Any, budget: float | None) -> None:
        with self.lock:
            self.calls.append(Call(role, request, budget))
            self.timeline.append(("model", role))

    @property
    def roles(self) -> list[str]:
        return [c.role for c in self.calls]

    @property
    def answer_calls(self) -> list[Call]:
        return [c for c in self.calls if c.is_answer]

    @property
    def classifier_calls(self) -> list[Call]:
        return [c for c in self.calls if c.is_classifier]

    def reset(self) -> None:
        with self.lock:
            self.calls.clear()
            self.provider_requests.clear()
            self.timeline.clear()
            self.safety_texts.clear()
            self.answers_made = 0

    # --- requests ---------------------------------------------------------------------------------

    def ask(
        self,
        text: str,
        mode: str | None = "quick",
        *,
        files: list[tuple[str, bytes]] | None = None,
        scenario: str | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        extra: list[tuple[str, str]] | None = None,
    ) -> Any:
        data: dict[str, Any] = {"text": text}
        if mode is not None:
            data["mode"] = mode
        if scenario is not None:
            data["scenario"] = scenario
        for key, value in extra or []:  # a repeated field: httpx sends a list as several fields of one name
            data[key] = [*([data[key]] if isinstance(data.get(key), str) else data.get(key, [])), value]
        parts = [("files", (name, content, "application/octet-stream")) for name, content in files or []]
        return self.client.post("/intake", data=data, files=parts or None, headers=headers, params=params)

    # --- what a refusal or an offer must not have touched -----------------------------------------

    def stored(self) -> dict[str, int]:
        s = self.store
        return {
            "tasks": len(s.tasks),
            "worlds": len(s.worlds),
            "events": sum(len(v) for v in s.events.values()),
            "pending_events": sum(len(v) for v in s.pending_events.values()),
            "policies": len(s.policies),
            "event_writes": len(getattr(getattr(self.flow, "writer", None), "calls", [])),
            "artifacts": len(self.artifacts.list_ids()),
        }

    def assert_nothing_stored(self) -> None:
        assert self.stored() == dict.fromkeys(self.stored(), 0), self.stored()

    # --- what a Quick answer costs, from the shipped price sheet ----------------------------------

    def credits_for(self, tokens_in: int, tokens_out: int, role: str = "assistant") -> float:
        profile = self.providers.roles[role].primary
        quote = self.providers.price(profile)
        return self.providers.credits((tokens_in * quote.input + tokens_out * quote.output) / 1e6)


def sec16_rig(h: Any, monkeypatch: Any, repo_root: pathlib.Path) -> QuickRig:
    """A `QuickRig` over the SEC-16 harness (deployed-style app, fake access store, spy over the real in-memory ledger):
    its router replaces the scripted one behind `deps.router_for_mode`, which still records each request's mode."""
    import types  # noqa: PLC0415

    from tilo_api import deps  # noqa: PLC0415

    flow = types.SimpleNamespace(
        router=None, client=h.client, store=h.store, flags=h.flags, safety=h.safety, writer=None
    )
    rig = QuickRig(flow, repo_root, own_flags=False, own_safety=False)

    def router_for_mode(mode: str) -> Any:
        h.router_modes.append(mode)
        return rig.router

    monkeypatch.setattr(deps, "router_for_mode", router_for_mode)
    return rig


def assert_answer_shape(body: dict[str, Any]) -> None:
    assert set(body) == ANSWER_KEYS, sorted(body)
    assert body["mode"] == "quick" and body["outcome"] == "answered"
    assert type(body["text"]) is str and body["text"].strip()
    assert set(body["cost"]) == COST_KEYS, sorted(body["cost"])


def assert_offer_shape(body: dict[str, Any], reason: str | None = None) -> None:
    assert set(body) == OFFER_KEYS, sorted(body)
    assert body["mode"] == "quick" and body["outcome"] == "switch_to_thinking"
    assert body["reason"] in REASONS, body["reason"]
    if reason is not None:
        assert body["reason"] == reason


def is_typed_quick_response(response: Any) -> bool:
    """True for a 200 whose body is exactly the Quick answer or the switch offer."""
    if response.status_code != 200:
        return False
    body = response.json()
    return (set(body) == ANSWER_KEYS and body.get("outcome") == "answered") or (
        set(body) == OFFER_KEYS and body.get("outcome") == "switch_to_thinking"
    )


__all__ = [
    "ANSWER",
    "ANSWER_KEYS",
    "COST_KEYS",
    "OFFER_KEYS",
    "REASONS",
    "SIMPLE_TEXT",
    "Call",
    "QuickRig",
    "assert_answer_shape",
    "assert_offer_shape",
    "is_typed_quick_response",
    "sec16_rig",
]
