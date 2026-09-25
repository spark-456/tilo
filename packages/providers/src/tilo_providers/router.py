"""tilo_providers.router — role -> ModelProvider router (PL-03, EFF-02, EFF-03; PRD 6.4, 6.6).
Business code calls `Router.generate(role, request, budget=...)` (also `stream`, `embed`), never
a model. Error policy and stream rules: packages/providers/CLAUDE.md. Every attempt is recorded
(PRD 9.3 trace material)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import jsonschema

from tilo_providers.config import ProvidersConfig
from tilo_providers.errors import ProviderError, QuotaError, RequestError, RetryableError, SafetyError
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider
from tilo_providers.prompts import load_prompt

_MARKER = "[truncated]"
_ERROR_CHARS = 300  # a validation error fed back in a repair prompt is capped at this length


class RouterError(Exception):
    """Router-level error; `attempts` holds every attempt made before it was raised."""

    def __init__(self, message: str, attempts: list[RouterAttempt] | None = None) -> None:
        super().__init__(message)
        self.attempts = list(attempts or [])


class BudgetExceededError(RouterError):
    """PL-03: the next call's estimated cost exceeds the remaining budget; never sent."""


class TokenCapExceededError(RouterError):
    """EFF-03: over max_input_tokens and cannot be compacted enough to fit."""


class RouterExhaustedError(RouterError):
    """Every candidate profile failed, or none had the required capability."""


class StreamInterruptedError(ProviderError):
    """PL-03: a stream failed after output started; no fallback, so answers are never spliced."""


@dataclass
class RouterAttempt:
    profile_id: str
    provider: str
    outcome: Literal["ok", "error", "safety_blocked", "schema_invalid", "verifier_rejected", "low_confidence"]
    latency_ms: float = 0.0
    tokens_in: int | None = None
    tokens_out: int | None = None
    error_type: str | None = None
    reason: str | None = None  # why this attempt was made (the escalation or fallback reason)


@dataclass
class RouterResult:
    role_id: str
    outcome: Literal["ok", "safety_blocked"]
    response: GenerateResponse | None
    attempts: list[RouterAttempt] = field(default_factory=list)


@dataclass
class RouterStream:
    """One router call's working state. Iterating it streams chunks; `attempts` fills in as it runs."""

    role_id: str
    request: GenerateRequest
    candidates: list[str]
    budget: float | None
    attempts: list[RouterAttempt] = field(default_factory=list)
    chunks: Iterator[GenerateResponse] = field(default_factory=lambda: iter(()))

    def __iter__(self) -> Iterator[GenerateResponse]:
        return self.chunks


def schema_error(response: GenerateResponse, schema: dict[str, Any]) -> str | None:
    """The validation error for `response` against `schema` (capped length), or None if it is valid."""
    try:
        jsonschema.validate(json.loads(response.text or ""), schema)
    except (ValueError, jsonschema.ValidationError) as error:
        message = error.message if isinstance(error, jsonschema.ValidationError) else f"not valid JSON ({error})"
        return message[:_ERROR_CHARS]
    return None


def validate_json_schema(response: GenerateResponse, schema: dict[str, Any]) -> bool:
    return schema_error(response, schema) is None


def _finish(attempt: RouterAttempt, start: float, response: Any = None, error: Exception | None = None) -> None:
    attempt.latency_ms = (time.perf_counter() - start) * 1000
    if isinstance(response, GenerateResponse) and response.usage:
        attempt.tokens_in, attempt.tokens_out = response.usage.get("input_tokens"), response.usage.get("output_tokens")
    if error is not None:
        attempt.outcome = "safety_blocked" if isinstance(error, SafetyError) else "error"
        attempt.error_type = type(error).__name__


def _compact(role_id: str, cap: int | None, prompt: str, outputs: list[str], count: Callable[[str], int]) -> str:
    """EFF-03: drop the oldest tool outputs, then truncate the one left with a marker, or refuse."""

    def fold() -> str:
        return "\n\n".join([prompt, *outputs])

    if cap is None:
        return fold()
    while len(outputs) > 1 and count(fold()) > cap:
        outputs.pop(0)
    if outputs and count(fold()) > cap:
        words, low, high = outputs[0].split(), 0, len(outputs[0].split())
        while low < high:  # longest word prefix (plus marker) that fits
            mid = (low + high + 1) // 2
            outputs[0] = " ".join([*words[:mid], _MARKER])
            low, high = (mid, high) if count(fold()) <= cap else (low, mid - 1)
        outputs[0] = " ".join([*words[:low], _MARKER])
    if count(fold()) > cap:
        raise TokenCapExceededError(f"EFF-03: role {role_id!r} input is over its max_input_tokens cap of {cap}")
    return fold()


class Router:
    """`provider_for_profile` (profile_id -> ModelProvider) is the test/production seam; without
    it, providers come from `factory.provider_for_role_profile` (replay unless `LIVE=1`)."""

    def __init__(
        self,
        config: ProvidersConfig,
        *,
        provider_for_profile: Callable[[str], ModelProvider] | None = None,
        fixtures_dir: Any = None,
    ) -> None:
        if provider_for_profile is None and fixtures_dir is None:
            raise RouterError("Router needs either provider_for_profile or fixtures_dir")
        self._config, self._provider_for_profile, self._fixtures_dir = config, provider_for_profile, fixtures_dir

    def _provider(self, role_id: str, profile_id: str) -> ModelProvider:
        if self._provider_for_profile is not None:
            return self._provider_for_profile(profile_id)
        from tilo_providers.factory import provider_for_role_profile  # noqa: PLC0415

        return provider_for_role_profile(role_id, profile_id, self._config, fixtures_dir=self._fixtures_dir)

    def _candidates(self, role_id: str, capability: Capability | None) -> list[str]:
        role = self._config.roles[role_id]
        ids = list(role.cascade or dict.fromkeys(p for p in (role.primary, role.fallback) if p))
        ids = [p for p in ids if capability in {None, *map(Capability, self._config.profiles[p].caps)}]
        if not ids:
            raise RouterExhaustedError(f"PL-03: role {role_id!r} has no candidate with capability {capability!r}")
        return ids

    def _start(self, role_id: str, req: GenerateRequest, outs: list[str] | None, cap: Any, budget: Any) -> RouterStream:
        role, candidates = self._config.roles[role_id], self._candidates(role_id, cap)
        count = self._provider(role_id, candidates[0]).count_tokens
        prompt = _compact(role_id, role.max_input_tokens, req.prompt, list(outs or []), count)
        limits = (req.max_output_tokens, role.max_output_tokens, 1024)  # 1024: neither sets one (BQ-54)
        max_output = next(limit for limit in limits if limit is not None)
        req = req.model_copy(update={"prompt": prompt, "max_output_tokens": max_output})
        return RouterStream(role_id, req, candidates, budget)

    def _repair(self, role_id: str, request: GenerateRequest, error: str, count: Callable[[str], int]) -> Any:
        """EFF-02 repair: the request plus its validation error, or None if that would exceed the cap."""
        prompt = load_prompt("router", "schema_repair.md", {"prompt": request.prompt, "error": error})
        cap = self._config.roles[role_id].max_input_tokens
        return None if cap is not None and count(prompt) > cap else request.model_copy(update={"prompt": prompt})

    def _attempt(
        self, run: RouterStream, profile_id: str, provider: ModelProvider, reason: str | None, request: Any = None
    ) -> RouterAttempt:
        """PL-03: every call (first, repair, fallback, escalation) is priced before it is made (BQ-52)."""
        if run.budget is not None:
            quote, request = self._config.price(profile_id), request or run.request
            usd = provider.count_tokens(request.prompt) * quote.input + (request.max_output_tokens or 0) * quote.output
            credits = self._config.credits(usd / 1_000_000)
            if credits > run.budget:
                message = f"PL-03: a call on {profile_id!r} costs ~{credits:.4f} credits, over {run.budget} left"
                raise BudgetExceededError(message, run.attempts)
            run.budget -= credits
        run.attempts.append(RouterAttempt(profile_id, self._config.profiles[profile_id].provider, "ok", reason=reason))
        return run.attempts[-1]

    def generate(
        self,
        role_id: str,
        request: GenerateRequest,
        *,
        budget: float | None = None,
        required_capability: Capability | None = None,
        verify: Callable[[GenerateResponse], bool] | None = None,
        confidence: Callable[[GenerateResponse], float] | None = None,
        confidence_threshold: float | None = None,
        tool_outputs: list[str] | None = None,
    ) -> RouterResult:
        run = self._start(role_id, request, tool_outputs, required_capability, budget)
        threshold, schema, reason = confidence_threshold or 0.0, run.request.response_schema, None
        for profile_id in run.candidates:  # EFF-02: cheapest first
            provider, request = self._provider(role_id, profile_id), run.request
            for is_repair in (False, True):
                attempt, start = self._attempt(run, profile_id, provider, reason, request), time.perf_counter()
                try:
                    response = provider.generate(request)
                except (RequestError, SafetyError, QuotaError, RetryableError, ProviderError) as error:
                    _finish(attempt, start, error=error)
                    if isinstance(error, RequestError):
                        raise  # the request itself is bad: no fallback
                    if isinstance(error, SafetyError):
                        return RouterResult(role_id, "safety_blocked", None, run.attempts)
                    reason = f"fallback after {attempt.error_type}"
                    break
                _finish(attempt, start, response)
                if schema is not None and (problem := schema_error(response, schema)) is not None:
                    attempt.outcome, reason = "schema_invalid", "escalated after schema validation failed"
                    if not is_repair and (
                        request := self._repair(role_id, run.request, problem, provider.count_tokens)
                    ):
                        reason = "repair attempt after schema validation failed"
                        continue
                elif verify is not None and not verify(response):
                    attempt.outcome, reason = "verifier_rejected", "escalated after verifier rejected the response"
                elif confidence is not None and (score := confidence(response)) < threshold:
                    attempt.outcome = "low_confidence"
                    reason = f"escalated after confidence {score:.2f} below threshold {threshold:.2f}"
                else:
                    return RouterResult(role_id, "ok", response, run.attempts)
                break
        raise RouterExhaustedError(f"PL-03: role {role_id!r} exhausted every candidate", run.attempts)

    def stream(
        self,
        role_id: str,
        request: GenerateRequest,
        *,
        budget: float | None = None,
        required_capability: Capability | None = None,
        tool_outputs: list[str] | None = None,
    ) -> RouterStream:
        """No EFF-02 escalation (it needs a whole response); fallback only before the first chunk."""
        run = self._start(role_id, request, tool_outputs, required_capability, budget)
        run.chunks = self._stream_chunks(run)
        return run

    def _stream_chunks(self, run: RouterStream) -> Iterator[GenerateResponse]:
        reason: str | None = None
        for profile_id in run.candidates:
            provider = self._provider(run.role_id, profile_id)
            attempt, start, chunks = self._attempt(run, profile_id, provider, reason), time.perf_counter(), 0
            try:
                for chunk in provider.stream(run.request):
                    chunks += 1
                    _finish(attempt, start, chunk)
                    yield chunk
                _finish(attempt, start)
                return
            except (RequestError, SafetyError, QuotaError, RetryableError, ProviderError) as error:
                _finish(attempt, start, error=error)
                if isinstance(error, (RequestError, SafetyError)):
                    raise
                if chunks:
                    message = f"PL-03: {profile_id!r} failed after {chunks} chunk(s); no fallback once output started"
                    raise StreamInterruptedError(message) from error
                reason = f"fallback after {attempt.error_type}"
        raise RouterExhaustedError(f"PL-03: role {run.role_id!r} exhausted every candidate", run.attempts)

    def embed(self, role_id: str, request: Any, *, required_capability: Capability | None = None) -> Any:
        last_error: ProviderError | None = None
        for profile_id in self._candidates(role_id, required_capability):
            try:
                return self._provider(role_id, profile_id).embed(request)
            except (RequestError, SafetyError):
                raise
            except (QuotaError, RetryableError, ProviderError) as error:
                last_error = error
        raise RouterExhaustedError(f"PL-03: role {role_id!r} embed exhausted every candidate") from last_error
