"""tilo_providers.router — role -> ModelProvider router (PL-03, EFF-02, EFF-03; PRD 6.4, 6.6). Business code
calls `Router.generate(role, request, budget=...)` (also `stream`, `embed`), never a model; every attempt is
recorded for the PRD 9.3 trace. Error policy and stream rules: packages/providers/CLAUDE.md."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import jsonschema

from tilo_providers.config import ProvidersConfig
from tilo_providers.errors import ProviderError, QuotaError, RequestError, RetryableError, SafetyError
from tilo_providers.factory import build_provider
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider
from tilo_providers.prompts import load_prompt

ProviderFor = Callable[[str], ModelProvider]


class RouterError(Exception):
    """Router-level error; `attempts` holds every attempt made before it was raised."""

    def __init__(self, message: str, attempts: list[RouterAttempt] | None = None) -> None:
        super().__init__(message)
        self.attempts = list(attempts or [])


class BudgetExceededError(RouterError): ...  # PL-03: the next call costs more than the budget left; never sent


class TokenCapExceededError(RouterError): ...  # EFF-03: over max_input_tokens even after compacting


class RouterExhaustedError(RouterError): ...  # every candidate failed, or none has the required capability


# PL-03, no fallback: a request rejected as such, a stream or embed blocked on safety grounds, a stream that
# failed after its first chunk (answers are never spliced). The adapter's own error is kept as `__cause__`.
class RouterRequestError(RouterError, RequestError): ...


class RouterSafetyError(RouterError, SafetyError): ...


class StreamInterruptedError(RouterError, ProviderError): ...


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
    """One router call. `attempts` fill in as it runs; generate() sets `outcome` and `response`, a stream()
    result is iterated for its chunks. `request` is the request as sent, `budget` what is left of it."""

    role_id: str
    request: GenerateRequest
    candidates: list[str]
    budget: float | None
    attempts: list[RouterAttempt] = field(default_factory=list)
    outcome: Literal["ok", "safety_blocked"] = "ok"
    response: GenerateResponse | None = None
    chunks: Iterator[GenerateResponse] = field(default_factory=lambda: iter(()))

    def __iter__(self) -> Iterator[GenerateResponse]:
        return self.chunks


def schema_error(response: GenerateResponse, schema: dict[str, Any]) -> str | None:
    """The validation error for `response` against `schema` (capped length), or None if it is valid."""
    try:
        jsonschema.validate(json.loads(response.text or ""), schema)
    except (ValueError, jsonschema.ValidationError) as error:
        message = error.message if isinstance(error, jsonschema.ValidationError) else f"not valid JSON ({error})"
        return message[:300]  # a validation error fed back in a repair prompt is capped
    return None


def _finish(attempt: RouterAttempt, start: float, response: Any = None, error: Exception | None = None) -> None:
    attempt.latency_ms = (time.perf_counter() - start) * 1000
    if isinstance(response, GenerateResponse) and response.usage:
        attempt.tokens_in, attempt.tokens_out = response.usage.get("input_tokens"), response.usage.get("output_tokens")
    if error is not None:
        attempt.outcome = "safety_blocked" if isinstance(error, SafetyError) else "error"
        attempt.error_type = type(error).__name__


def _fall_back(run: RouterResult, attempt: RouterAttempt, start: float, error: ProviderError, chunks: int = 0) -> str:
    """Records a failed call; returns the fallback reason or raises a RouterError carrying every attempt."""
    _finish(attempt, start, error=error)
    where = f"PL-03: role {run.role_id!r} profile {attempt.profile_id!r}"
    if isinstance(error, RequestError):  # the request itself is bad: no fallback
        raise RouterRequestError(f"{where} rejected the request: {error}", run.attempts) from error
    if isinstance(error, SafetyError):  # stream only: generate returns a safety_blocked result
        raise RouterSafetyError(f"{where} blocked on safety grounds: {error}", run.attempts) from error
    if chunks:
        raise StreamInterruptedError(f"{where} failed after {chunks} chunk(s); output started", run.attempts) from error
    return f"fallback after {attempt.error_type}"


def _compact(role_id: str, cap: int | None, prompt: str, outputs: list[str], count: Callable[[str], int]) -> str:
    """EFF-03: drop the oldest tool outputs, then truncate the one left with a marker, or refuse."""
    parts, join = [prompt, *outputs], "\n\n".join
    if cap is None:
        return join(parts)
    while len(parts) > 2 and count(join(parts)) > cap:
        parts.pop(1)
    if len(parts) > 1 and count(join(parts)) > cap:
        words, low, high = parts[1].split(), 0, len(parts[1].split())
        while low < high:  # longest word prefix (plus marker) that fits
            mid = (low + high + 1) // 2
            parts[1] = " ".join([*words[:mid], "[truncated]"])
            low, high = (mid, high) if count(join(parts)) <= cap else (low, mid - 1)
        parts[1] = " ".join([*words[:low], "[truncated]"])
    if count(join(parts)) > cap:
        raise TokenCapExceededError(f"EFF-03: role {role_id!r} input is over its max_input_tokens cap of {cap}")
    return join(parts)


class Router:
    def __init__(
        self, config: ProvidersConfig, *, provider_for_profile: ProviderFor | None = None, fixtures_dir: Any = None
    ) -> None:
        if provider_for_profile is None and fixtures_dir is None:
            raise RouterError("Router needs either provider_for_profile or fixtures_dir")
        self._config, self._provider_for_profile, self._fixtures_dir = config, provider_for_profile, fixtures_dir

    def _provider(self, role_id: str, profile_id: str) -> ModelProvider:
        if self._provider_for_profile is not None:
            return self._provider_for_profile(profile_id)
        return build_provider(role_id, self._config, fixtures_dir=self._fixtures_dir, profile_id=profile_id)

    def _candidates(self, role_id: str, capability: Capability | None) -> list[str]:
        role = self._config.roles[role_id]
        ids = list(role.cascade or dict.fromkeys(p for p in (role.primary, role.fallback) if p))
        ids = [p for p in ids if capability in {None, *map(Capability, self._config.profiles[p].caps)}]
        if not ids:
            raise RouterExhaustedError(f"PL-03: role {role_id!r} has no candidate with capability {capability!r}")
        return ids

    def _start(self, role_id: str, req: GenerateRequest, outs: list[str] | None, cap: Any, budget: Any) -> RouterResult:
        role, candidates = self._config.roles[role_id], self._candidates(role_id, cap)
        count = self._provider(role_id, candidates[0]).count_tokens
        prompt = _compact(role_id, role.max_input_tokens, req.prompt, list(outs or []), count)
        max_output = next(n for n in (req.max_output_tokens, role.max_output_tokens, 1024) if n is not None)  # BQ-54
        req = req.model_copy(update={"prompt": prompt, "max_output_tokens": max_output})
        return RouterResult(role_id, req, candidates, budget)

    def _attempt(self, run: RouterResult, profile_id: str, reason: str | None, request: Any = None) -> RouterAttempt:
        """PL-03: every call (first, repair, fallback, escalation) is priced before it is made (BQ-52)."""
        if run.budget is not None:
            quote, request = self._config.price(profile_id), request or run.request
            count = self._provider(run.role_id, profile_id).count_tokens
            usd = count(request.prompt) * quote.input + (request.max_output_tokens or 0) * quote.output
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
        cap = self._config.roles[role_id].max_input_tokens  # EFF-02 repair prompts must fit it too
        for profile_id in run.candidates:  # EFF-02: cheapest first
            provider, request = self._provider(role_id, profile_id), run.request
            for is_repair in (False, True):
                attempt, start = self._attempt(run, profile_id, reason, request), time.perf_counter()
                try:
                    response = provider.generate(request)
                except SafetyError as error:  # a safety outcome, never a silent fallback
                    _finish(attempt, start, error=error)
                    return replace(run, outcome="safety_blocked")
                except (RequestError, QuotaError, RetryableError, ProviderError) as error:
                    reason = _fall_back(run, attempt, start, error)
                    break
                _finish(attempt, start, response)
                if schema is not None and (problem := schema_error(response, schema)) is not None:
                    attempt.outcome, reason = "schema_invalid", "escalated after schema validation failed"
                    prompt = load_prompt("router", "schema_repair.md", {"prompt": run.request.prompt, "error": problem})
                    if not is_repair and (cap is None or provider.count_tokens(prompt) <= cap):  # one repair
                        request = run.request.model_copy(update={"prompt": prompt})
                        reason = "repair attempt after schema validation failed"
                        continue
                elif verify is not None and not verify(response):
                    attempt.outcome, reason = "verifier_rejected", "escalated after verifier rejected the response"
                elif confidence is not None and (score := confidence(response)) < threshold:
                    attempt.outcome = "low_confidence"
                    reason = f"escalated after confidence {score:.2f} below threshold {threshold:.2f}"
                else:
                    return replace(run, response=response)
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
    ) -> RouterResult:  # no EFF-02 escalation (it needs a whole response); fallback only before the first chunk
        run = self._start(role_id, request, tool_outputs, required_capability, budget)
        run.chunks = self._stream_chunks(run)
        return run

    def _stream_chunks(self, run: RouterResult) -> Iterator[GenerateResponse]:
        reason: str | None = None
        for profile_id in run.candidates:
            provider = self._provider(run.role_id, profile_id)
            attempt, start, chunks = self._attempt(run, profile_id, reason), time.perf_counter(), 0
            try:
                for chunk in provider.stream(run.request):
                    chunks += 1
                    _finish(attempt, start, chunk)
                    yield chunk
                _finish(attempt, start)
                return
            except (RequestError, SafetyError, QuotaError, RetryableError, ProviderError) as error:
                reason = _fall_back(run, attempt, start, error, chunks)
        raise RouterExhaustedError(f"PL-03: role {run.role_id!r} exhausted every candidate", run.attempts)

    def embed(self, role_id: str, request: Any, *, required_capability: Capability | None = None) -> Any:
        last_error: ProviderError | None = None
        for profile_id in self._candidates(role_id, required_capability):
            try:
                return self._provider(role_id, profile_id).embed(request)
            except (RequestError, SafetyError) as error:
                wrap = RouterRequestError if isinstance(error, RequestError) else RouterSafetyError
                raise wrap(f"PL-03: role {role_id!r} embed on {profile_id!r} failed: {error}") from error
            except (QuotaError, RetryableError, ProviderError) as error:
                last_error = error
        raise RouterExhaustedError(f"PL-03: role {role_id!r} embed exhausted every candidate") from last_error
