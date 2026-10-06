"""tilo_providers.router — role -> ModelProvider router (PL-03, EFF-02, EFF-03; PRD 6.4, 6.6). Business code
calls `Router.generate(role, request, budget=...)` (also `stream`, `embed`), never a model; every attempt is
recorded for the PRD 9.3 trace. Error policy and stream rules: packages/providers/CLAUDE.md."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from tilo_providers.config import ProvidersConfig
from tilo_providers.errors import ProviderError, RequestError, SafetyError
from tilo_providers.factory import build_provider
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.schema_guard import first_error, short

ProviderFor = Callable[[str], ModelProvider]


class RouterError(Exception):
    """Router-level error; `attempts` holds every attempt made before it was raised."""

    def __init__(self, message: str, attempts: list[RouterAttempt] | None = None) -> None:
        super().__init__(message)
        self.attempts = list(attempts or [])


class BudgetExceededError(RouterError): ...  # PL-03: no candidate left fits the budget; nothing over it is sent


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
    result is iterated for its chunks. `request` is the request as sent, `budget` what is left of it.
    `raw_prompt`/`tool_outputs` are the pre-compaction inputs (EFF-03): each candidate compacts them with
    its own `count_tokens`. `last_error` is the last candidate's own error, the `__cause__` of an
    exhausted run."""

    role_id: str
    request: GenerateRequest
    candidates: list[str]
    budget: float | None
    raw_prompt: str = ""
    tool_outputs: list[str] = field(default_factory=list)
    attempts: list[RouterAttempt] = field(default_factory=list)
    outcome: Literal["ok", "safety_blocked"] = "ok"
    response: GenerateResponse | None = None
    embedding: Any = None  # embed()'s result (the adapter's raw {"vectors": [...]} shape), attempts alongside it
    chunks: Iterator[GenerateResponse] = field(default_factory=lambda: iter(()))
    last_error: Exception | None = field(default=None, repr=False)

    def __iter__(self) -> Iterator[GenerateResponse]:
        return self.chunks


def schema_error(response: GenerateResponse, schema: dict[str, Any]) -> str | None:
    """The validation error for `response` against `schema` (capped length), or None if it is valid.
    `uniqueItems` is linear (`schema_guard`, #124); a fed-back error never echoes a value whole."""
    try:
        instance = json.loads(response.text or "")
    except (ValueError, RecursionError) as error:  # RecursionError: nested too deeply to parse
        return short(f"not valid JSON ({error})")
    try:
        return first_error(instance, schema)
    except (ValueError, RecursionError):  # too deep to walk, or a number too long to print
        return "/: the output could not be validated"


def _usage(attempt: RouterAttempt, response: GenerateResponse) -> None:
    if response.usage:
        attempt.tokens_in, attempt.tokens_out = response.usage.get("input_tokens"), response.usage.get("output_tokens")


def _fail(run: RouterResult, attempt: RouterAttempt, error: Exception, *, output_started: bool = False) -> None:
    """Records a failed candidate. Returns (the router falls back) for quota, retryable, base ProviderError,
    EFF-03 cap refusals and any unexpected exception (NotImplementedError, an adapter bug); raises a
    RouterError carrying every attempt, the adapter's error as `__cause__`, for everything with no fallback."""
    attempt.outcome = "safety_blocked" if isinstance(error, SafetyError) else "error"
    attempt.error_type, run.last_error = type(error).__name__, error
    where = f"PL-03: role {run.role_id!r} profile {attempt.profile_id!r}"
    if isinstance(error, RequestError):  # the request itself is bad: no fallback
        raise RouterRequestError(f"{where} rejected the request: {error}", run.attempts) from error
    if isinstance(error, SafetyError):  # stream/embed; generate() turns this into a safety_blocked result
        raise RouterSafetyError(f"{where} blocked on safety grounds: {error}", run.attempts) from error
    if output_started:  # answers are never spliced
        raise StreamInterruptedError(f"{where} failed after output started", run.attempts) from error


def _exhausted(run: RouterResult) -> RouterError:
    if run.attempts and run.attempts[-1].error_type == "BudgetExceededError":  # the budget ended the run
        message = f"PL-03: role {run.role_id!r} has no candidate left that fits the remaining budget"
        return BudgetExceededError(message, run.attempts)
    if run.attempts and all(a.error_type == "TokenCapExceededError" for a in run.attempts):
        message = f"EFF-03: role {run.role_id!r} is over max_input_tokens for every candidate"
        return TokenCapExceededError(message, run.attempts)
    return RouterExhaustedError(f"PL-03: role {run.role_id!r} exhausted every candidate", run.attempts)


def _embed_inputs(request: Any) -> list[str]:
    """The texts an embed request carries, in the same shape the adapters themselves read (PL-02: `{"input":
    [...]}` or the raw list/string) -- used only to price the call (BQ-61); the request goes to the adapter
    unchanged."""
    raw = request["input"] if isinstance(request, dict) else request
    return [raw] if isinstance(raw, str) else list(raw)


def _input_text(request: GenerateRequest, prompt: str) -> str:
    """EFF-03/PL-03: every input field an adapter serialises for `request` sent with `prompt` -- system,
    prompt, tool definitions and response schema -- as the one text a candidate's `count_tokens` measures
    for its cap and its price. `max_output_tokens` is priced as output; `json_mode` is a flag, not text."""
    parts = [request.system, prompt]
    parts += [json.dumps(part, sort_keys=True) for part in (request.tools, request.response_schema) if part is not None]
    return "\n\n".join(part for part in parts if part)


def _compact(role_id: str, cap: int | None, prompt: str, outputs: list[str], measure: Callable[[str], int]) -> str:
    """EFF-03: drop the oldest tool outputs, then truncate the one left with a marker, or refuse.
    `measure(prompt)` counts the whole request as it would be sent with that prompt (system, tools, ...)."""
    parts, join = [prompt, *outputs], "\n\n".join
    if cap is None:
        return join(parts)
    if measure("") > cap:  # the fixed parts alone: nothing to compact
        raise TokenCapExceededError(f"EFF-03: role {role_id!r} system/tools/schema alone are over its cap of {cap}")
    while len(parts) > 2 and measure(join(parts)) > cap:
        parts.pop(1)
    if len(parts) > 1 and measure(join(parts)) > cap:
        words, low, high = parts[1].split(), 0, len(parts[1].split())
        while low < high:  # longest word prefix (plus marker) that fits
            mid = (low + high + 1) // 2
            parts[1] = " ".join([*words[:mid], "[truncated]"])
            low, high = (mid, high) if measure(join(parts)) <= cap else (low, mid - 1)
        parts[1] = " ".join([*words[:low], "[truncated]"])
    if measure(join(parts)) > cap:
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

    @contextmanager
    def _candidate(self, run: RouterResult, profile_id: str, reason: str | None) -> Iterator[RouterAttempt]:
        """PL-03 choke point: EVERY touch of a candidate (building it, `count_tokens` for its cap and price,
        generate, stream up to its first chunk, embed) runs inside this block. It records exactly one
        attempt and hands any exception to `_fail`: a fallback-worthy one is suppressed (the attempt's
        `error_type` is set and the caller moves on), anything else leaves as a RouterError. A candidate the
        budget cannot cover is recorded like that too (BudgetExceededError, never sent) and the next one tried."""
        attempt = RouterAttempt(profile_id, self._config.profiles[profile_id].provider, "ok", reason=reason)
        start = time.perf_counter()
        try:
            yield attempt
        except Exception as error:
            run.attempts.append(attempt)
            _fail(run, attempt, error)
        else:
            run.attempts.append(attempt)
        finally:
            attempt.latency_ms = (time.perf_counter() - start) * 1000

    def _start(self, role_id: str, req: GenerateRequest, outs: list[str] | None, cap: Any, budget: Any) -> RouterResult:
        role, candidates = self._config.roles[role_id], self._candidates(role_id, cap)
        max_output = next(n for n in (req.max_output_tokens, role.max_output_tokens, 1024) if n is not None)  # BQ-63
        request = req.model_copy(update={"max_output_tokens": max_output})
        return RouterResult(role_id, request, candidates, budget, raw_prompt=req.prompt, tool_outputs=list(outs or []))

    def _prepare(
        self, run: RouterResult, profile_id: str, provider: ModelProvider, prompt: str | None = None
    ) -> tuple[GenerateRequest, float]:
        """EFF-03 with this candidate's own `count_tokens`, on everything sent (`_input_text`): compact the
        role's input to max_input_tokens (or refuse a repair `prompt` over it), then price the call (PL-03).
        Never sends anything over the cap."""
        cap = self._config.roles[run.role_id].max_input_tokens
        measure = lambda text: provider.count_tokens(_input_text(run.request, text))  # noqa: E731
        if prompt is None:
            prompt = _compact(run.role_id, cap, run.raw_prompt, run.tool_outputs, measure)
        elif cap is not None and measure(prompt) > cap:
            raise TokenCapExceededError(f"EFF-03: role {run.role_id!r} repair prompt is over its cap of {cap}")
        sent = run.request.model_copy(update={"prompt": prompt})
        return sent, self._quote(run, profile_id, provider, _input_text(sent, prompt), sent.max_output_tokens or 0)

    def _cost(self, profile_id: str, tokens_in: int, tokens_out: int) -> float:
        quote = self._config.price(profile_id)
        return self._config.credits((tokens_in * quote.input + tokens_out * quote.output) / 1e6)

    def _quote(self, run: RouterResult, profile_id: str, provider: ModelProvider, text: str, out: int) -> float:
        """PL-03: every call (first, repair, fallback, escalation) is priced before it is made (BQ-61) and
        refused if over the budget left. Nothing is taken from the budget until the call returns (`_spend`)."""
        if run.budget is None:
            return 0.0
        credits = self._cost(profile_id, provider.count_tokens(text), out)
        if credits > run.budget:
            message = f"PL-03: a call on {profile_id!r} costs ~{credits:.4f} credits, over {run.budget} left"
            raise BudgetExceededError(message, run.attempts)
        return credits

    def _spend(self, run: RouterResult, profile_id: str, estimate: float, usage: dict[str, Any] | None) -> None:
        """PL-03: a call that returned is charged from its reported usage, else its estimate. A call that
        raised (quota, retryable, ...) is never charged, so it cannot starve the fallback."""
        if run.budget is None:
            return
        tokens_in, tokens_out = (usage or {}).get("input_tokens"), (usage or {}).get("output_tokens")
        if isinstance(tokens_in, int) and isinstance(tokens_out, int):
            estimate = self._cost(profile_id, tokens_in, tokens_out)
        run.budget -= estimate

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
            prompt: str | None = None  # None: the role's own input; else the one schema-repair prompt
            for is_repair in (False, True):
                try:
                    with self._candidate(run, profile_id, reason) as attempt:
                        provider = self._provider(role_id, profile_id)
                        sent, estimate = self._prepare(run, profile_id, provider, prompt)
                        response = provider.generate(sent)
                except RouterSafetyError:  # a safety outcome, never a silent fallback
                    return replace(run, outcome="safety_blocked")
                if attempt.error_type:
                    reason = f"fallback after {attempt.error_type}"
                    break
                self._spend(run, profile_id, estimate, response.usage)
                _usage(attempt, response)
                if schema is not None and (problem := schema_error(response, schema)) is not None:
                    attempt.outcome, reason = "schema_invalid", "escalated after schema validation failed"
                    if not is_repair:  # one repair, on the same candidate
                        prompt = load_prompt(
                            "router",
                            "schema_repair.md",
                            {"prompt": sent.prompt, "error": neutralise_marker(problem, "ERROR")},
                        )
                        reason = "repair attempt after schema validation failed"
                        continue
                elif verify is not None and not verify(response):
                    attempt.outcome, reason = "verifier_rejected", "escalated after verifier rejected the response"
                elif confidence is not None and (score := confidence(response)) < threshold:
                    attempt.outcome = "low_confidence"
                    reason = f"escalated after confidence {score:.2f} below threshold {threshold:.2f}"
                else:
                    return replace(run, request=sent, response=response)
                break
        raise _exhausted(run) from run.last_error

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
            start = time.perf_counter()
            with self._candidate(run, profile_id, reason) as attempt:
                provider = self._provider(run.role_id, profile_id)
                sent, estimate = self._prepare(run, profile_id, provider)
                chunks = iter(provider.stream(sent))
                chunk = next(chunks, None)
            if attempt.error_type:
                reason = f"fallback after {attempt.error_type}"
                continue
            run.request = sent
            self._spend(run, profile_id, estimate, None)  # output started: billed at its estimate
            try:  # output has started: from here on a failure never falls back
                while chunk is not None:
                    _usage(attempt, chunk)
                    yield chunk
                    chunk = next(chunks, None)
            except Exception as error:
                _fail(run, attempt, error, output_started=True)
            finally:
                attempt.latency_ms = (time.perf_counter() - start) * 1000
            return
        raise _exhausted(run) from run.last_error

    def embed(
        self,
        role_id: str,
        request: Any,
        *,
        budget: float | None = None,
        required_capability: Capability | None = None,
    ) -> RouterResult:  # same choke point as generate/stream, so the trace shows every attempt
        run = RouterResult(role_id, request, self._candidates(role_id, required_capability), budget)
        reason: str | None = None
        for profile_id in run.candidates:  # EFF-02: cheapest first
            with self._candidate(run, profile_id, reason) as attempt:
                provider = self._provider(role_id, profile_id)
                # priced like a generate() call with no output tokens (BQ-61), with each candidate's tokenizer
                estimate = self._quote(run, profile_id, provider, "\n\n".join(_embed_inputs(request)), 0)
                embedding = provider.embed(request)
            if not attempt.error_type:
                self._spend(run, profile_id, estimate, None)
                return replace(run, embedding=embedding)
            reason = f"fallback after {attempt.error_type}"
        raise _exhausted(run) from run.last_error
