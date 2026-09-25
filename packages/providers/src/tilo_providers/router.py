"""tilo_providers.router — role -> ModelProvider router (PL-03, EFF-02,
EFF-03; PRD 6.4, 6.6). Business code calls `Router.generate(role, request,
budget=...)` (also `stream`, `embed`) and never names a model or profile.

Fallback (PL-03): every ProviderError subtype gets its own explicit branch
(P0-05 security hand-over) -- QuotaError/RetryableError, and every other
adapter-raised ProviderError (malformed response, bad stream chunk, missing
api_key_env, ...), move to the next candidate; RequestError and
non-ProviderError bugs propagate unchanged; SafetyError ends the call as
outcome="safety_blocked" (generate()) or re-raises (stream()/embed()).
Cascades (EFF-02): role.cascade (cheapest first) is tried in order;
escalation is logged with a reason on schema failure (one repair attempt),
verifier rejection or low confidence. Token caps (EFF-03): role.max_input_tokens
drops the oldest tool_outputs then truncates the one that remains, or
refuses -- never sent over the cap. Every attempt lands in
RouterResult.attempts -- the TiloEvent.trace field's material (PRD 9.3)."""

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

_DEFAULT_MAX_OUTPUT_TOKENS = 1024  # neither caller nor role sets one (BQ-54)
_TRUNCATION_MARKER = "[truncated]"


class RouterError(Exception):
    """Base for router-level errors (not `tilo_providers.errors.ProviderError`, which an adapter raises)."""


class BudgetExceededError(RouterError):
    """PL-03: even the cheapest candidate's estimated cost exceeds the caller's remaining budget."""


class TokenCapExceededError(RouterError):
    """EFF-03: over max_input_tokens and cannot be compacted enough to fit."""


class RouterExhaustedError(RouterError):
    """Every candidate profile failed, or none had the required capability."""


AttemptOutcome = Literal["ok", "error", "safety_blocked", "schema_invalid", "verifier_rejected", "low_confidence"]


@dataclass
class RouterAttempt:
    """One attempt at one profile -- PRD 9.3 trace material plus bookkeeping."""

    profile_id: str
    provider: str
    outcome: AttemptOutcome
    latency_ms: float
    tokens_in: int | None = None
    tokens_out: int | None = None
    error_type: str | None = None
    reason: str | None = None  # why this attempt was made (the prior attempt's fallback/escalation reason)


@dataclass
class RouterResult:
    role_id: str
    outcome: Literal["ok", "safety_blocked"]
    response: GenerateResponse | None
    attempts: list[RouterAttempt] = field(default_factory=list)


def validate_json_schema(response: GenerateResponse, schema: dict[str, Any]) -> bool:
    """Does `response.text` parse as JSON and validate against `schema`? Shared by the router's
    schema-failure escalation and `tilo_providers.conformance`'s schema_adherence check."""
    if response.text is None:
        return False
    try:
        data = json.loads(response.text)
    except (TypeError, ValueError):
        return False
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError:
        return False
    return True


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def _usage(response: GenerateResponse) -> tuple[int | None, int | None]:
    if response.usage is None:
        return None, None
    return response.usage.get("input_tokens"), response.usage.get("output_tokens")


def _fold(prompt: str, outputs: list[str]) -> str:
    return prompt if not outputs else prompt + "\n\n" + "\n\n".join(outputs)


def _truncate_to_budget(text: str, budget: int, count_tokens: Callable[[str], int]) -> str:
    if budget <= 0:
        return _TRUNCATION_MARKER
    words = text.split()
    keep = len(words)
    while keep > 0 and count_tokens(" ".join([*words[:keep], _TRUNCATION_MARKER])) > budget:
        keep -= 1
    return " ".join([*words[:keep], _TRUNCATION_MARKER]) if keep > 0 else _TRUNCATION_MARKER


def _resolve_max_output_tokens(role: Any, request: GenerateRequest) -> int:
    if request.max_output_tokens is not None:
        return request.max_output_tokens
    if role.max_output_tokens is not None:
        return role.max_output_tokens
    return _DEFAULT_MAX_OUTPUT_TOKENS


class Router:
    """PL-03/EFF-02/EFF-03: role -> ModelProvider, by capability and budget, cheapest-first
    cascades, per-role token caps. `provider_for_profile` (profile_id -> ModelProvider) is the
    test/production seam; without it, providers are built lazily via
    `tilo_providers.factory.provider_for_role_profile` against `fixtures_dir` (replay unless
    `LIVE=1`)."""

    def __init__(
        self,
        config: ProvidersConfig,
        *,
        provider_for_profile: Callable[[str], ModelProvider] | None = None,
        fixtures_dir: Any = None,
    ) -> None:
        if provider_for_profile is None and fixtures_dir is None:
            raise RouterError("Router needs either provider_for_profile or fixtures_dir")
        self._config = config
        self._provider_for_profile = provider_for_profile
        self._fixtures_dir = fixtures_dir

    def _provider(self, role_id: str, profile_id: str) -> ModelProvider:
        if self._provider_for_profile is not None:
            return self._provider_for_profile(profile_id)
        from tilo_providers.factory import provider_for_role_profile  # noqa: PLC0415

        return provider_for_role_profile(role_id, profile_id, self._config, fixtures_dir=self._fixtures_dir)

    def _candidate_profile_ids(self, role: Any) -> list[str]:
        if role.cascade:
            return list(role.cascade)
        ids = [role.primary]
        if role.fallback and role.fallback not in ids:
            ids.append(role.fallback)
        return ids

    def _resolve_candidates(self, role_id: str, role: Any, required_capability: Capability | None) -> list[str]:
        candidates = self._candidate_profile_ids(role)
        if required_capability is not None:
            candidates = [
                pid
                for pid in candidates
                if required_capability in {Capability(c) for c in self._config.profiles[pid].caps}
            ]
        if not candidates:
            raise RouterExhaustedError(
                f"PL-03: role {role_id!r} has no candidate with capability {required_capability!r}"
            )
        return candidates

    def _prepare_request(
        self,
        role_id: str,
        role: Any,
        request: GenerateRequest,
        tool_outputs: list[str] | None,
        count_tokens: Callable[[str], int],
    ) -> GenerateRequest:
        max_output = _resolve_max_output_tokens(role, request)
        outputs = list(tool_outputs or [])
        cap = role.max_input_tokens
        if cap is not None:

            def total() -> int:
                return count_tokens(_fold(request.prompt, outputs))

            while len(outputs) > 1 and total() > cap:
                outputs.pop(0)  # EFF-03: oldest tool output dropped first
            if total() > cap:
                if not outputs:
                    raise TokenCapExceededError(
                        f"EFF-03: role {role_id!r} prompt is over its max_input_tokens cap of {cap} tokens, "
                        "nothing left to compact"
                    )
                budget = max(cap - count_tokens(request.prompt), 0)
                outputs[0] = _truncate_to_budget(outputs[0], budget, count_tokens)
                if total() > cap:
                    raise TokenCapExceededError(
                        f"EFF-03: role {role_id!r} still over its max_input_tokens cap of {cap}"
                    )
        return request.model_copy(update={"prompt": _fold(request.prompt, outputs), "max_output_tokens": max_output})

    def _check_budget(self, profile_id: str, provider: ModelProvider, request: GenerateRequest, budget: float) -> None:
        tokens_in = provider.count_tokens(request.prompt)
        quote = self._config.price(profile_id)
        cost_usd = (tokens_in * quote.input + (request.max_output_tokens or 0) * quote.output) / 1_000_000
        cost_credits = self._config.credits(cost_usd)
        if cost_credits > budget:
            raise BudgetExceededError(
                f"PL-03: estimated {cost_credits:.4f} credits for {profile_id!r} exceeds budget {budget}"
            )

    def _setup(
        self,
        role_id: str,
        request: GenerateRequest,
        tool_outputs: list[str] | None,
        budget: float | None,
        required_capability: Capability | None,
    ) -> tuple[list[str], GenerateRequest, ModelProvider]:
        role = self._config.roles[role_id]
        candidates = self._resolve_candidates(role_id, role, required_capability)
        provider0 = self._provider(role_id, candidates[0])
        effective_request = self._prepare_request(role_id, role, request, tool_outputs, provider0.count_tokens)
        if budget is not None:
            self._check_budget(candidates[0], provider0, effective_request, budget)
        return candidates, effective_request, provider0

    def _single_call(
        self, provider: ModelProvider, profile_id: str, request: GenerateRequest, incoming_reason: str | None
    ) -> tuple[RouterAttempt, GenerateResponse | None, Literal["ok", "safety_blocked", "fallback"]]:
        provider_name = self._config.profiles[profile_id].provider
        start = time.perf_counter()
        try:
            response = provider.generate(request)
        except RequestError:
            raise  # PL-03: the request itself is bad -- no fallback.
        except SafetyError:
            attempt = RouterAttempt(
                profile_id,
                provider_name,
                "safety_blocked",
                _ms(start),
                error_type="SafetyError",
                reason=incoming_reason,
            )
            return attempt, None, "safety_blocked"
        except (QuotaError, RetryableError, ProviderError) as error:
            # Every other ProviderError (incl. the base class an adapter raises directly for a
            # malformed response, bad tool-call JSON, ...) is not the caller's fault -- falls back.
            attempt = RouterAttempt(
                profile_id, provider_name, "error", _ms(start), error_type=type(error).__name__, reason=incoming_reason
            )
            return attempt, None, "fallback"
        # Any other exception (a bug, not any ProviderError subtype at all) is not caught here:
        # it propagates unchanged (P0-05 security hand-over).
        tokens_in, tokens_out = _usage(response)
        attempt = RouterAttempt(
            profile_id, provider_name, "ok", _ms(start), tokens_in, tokens_out, reason=incoming_reason
        )
        return attempt, response, "ok"

    def _try_candidate(
        self,
        provider: ModelProvider,
        profile_id: str,
        request: GenerateRequest,
        incoming_reason: str | None,
        *,
        verify: Callable[[GenerateResponse], bool] | None,
        confidence: Callable[[GenerateResponse], float] | None,
        confidence_threshold: float | None,
    ) -> tuple[list[RouterAttempt], GenerateResponse | None, str | None]:
        attempts: list[RouterAttempt] = []
        attempt, response, status = self._single_call(provider, profile_id, request, incoming_reason)
        attempts.append(attempt)
        if status == "safety_blocked":
            return attempts, None, None
        if status == "fallback":
            return attempts, None, f"fallback after {attempt.error_type}"

        schema = request.response_schema
        if schema is not None and not validate_json_schema(response, schema):  # type: ignore[arg-type]
            attempt.outcome = "schema_invalid"
            repair, repair_response, repair_status = self._single_call(
                provider, profile_id, request, "repair attempt after schema validation failed"
            )
            attempts.append(repair)
            if repair_status == "safety_blocked":
                return attempts, None, None
            if repair_status == "fallback":
                return attempts, None, f"fallback after {repair.error_type} during repair"
            if validate_json_schema(repair_response, schema):  # type: ignore[arg-type]
                return attempts, repair_response, None
            repair.outcome = "schema_invalid"
            return attempts, None, "escalated after schema validation failed (repair attempt exhausted)"

        if verify is not None and not verify(response):  # type: ignore[arg-type]
            attempt.outcome = "verifier_rejected"
            return attempts, None, "escalated after verifier rejected the response"

        if confidence is not None:
            threshold = confidence_threshold if confidence_threshold is not None else 0.0
            score = confidence(response)  # type: ignore[arg-type]
            if score < threshold:
                attempt.outcome = "low_confidence"
                return attempts, None, f"escalated after confidence {score:.2f} below threshold {threshold:.2f}"

        return attempts, response, None

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
        candidates, effective_request, provider0 = self._setup(
            role_id, request, tool_outputs, budget, required_capability
        )

        attempts: list[RouterAttempt] = []
        reason: str | None = None
        for profile_id in candidates:
            provider = provider0 if profile_id == candidates[0] else self._provider(role_id, profile_id)
            made, response, next_reason = self._try_candidate(
                provider,
                profile_id,
                effective_request,
                reason,
                verify=verify,
                confidence=confidence,
                confidence_threshold=confidence_threshold,
            )
            attempts.extend(made)
            if made[-1].outcome == "safety_blocked":
                return RouterResult(role_id=role_id, outcome="safety_blocked", response=None, attempts=attempts)
            if response is not None:
                return RouterResult(role_id=role_id, outcome="ok", response=response, attempts=attempts)
            reason = next_reason

        raise RouterExhaustedError(f"PL-03: role {role_id!r} exhausted every candidate profile {candidates!r}")

    def stream(
        self,
        role_id: str,
        request: GenerateRequest,
        *,
        budget: float | None = None,
        required_capability: Capability | None = None,
        tool_outputs: list[str] | None = None,
    ) -> Iterator[GenerateResponse]:
        """Fallback-on-error streaming (PL-03). EFF-02's escalation needs a complete response to
        evaluate, so it does not apply mid-stream; use `generate()` and stream only its final,
        already-escalated call if that is needed."""
        candidates, effective_request, provider0 = self._setup(
            role_id, request, tool_outputs, budget, required_capability
        )
        last_error: ProviderError | None = None
        for profile_id in candidates:
            provider = provider0 if profile_id == candidates[0] else self._provider(role_id, profile_id)
            try:
                yield from provider.stream(effective_request)
                return
            except RequestError:
                raise
            except SafetyError:
                raise  # PL-03: no fallback on a safety block, same policy as generate().
            except (QuotaError, RetryableError, ProviderError) as error:
                last_error = error  # every other ProviderError falls back, same as generate().
                continue
        assert last_error is not None  # noqa: S101 -- candidates is never empty
        raise last_error

    def embed(self, role_id: str, request: Any, *, required_capability: Capability | None = None) -> Any:
        role = self._config.roles[role_id]
        candidates = self._resolve_candidates(role_id, role, required_capability)
        last_error: ProviderError | None = None
        for profile_id in candidates:
            provider = self._provider(role_id, profile_id)
            try:
                return provider.embed(request)
            except RequestError:
                raise
            except SafetyError:
                raise
            except (QuotaError, RetryableError, ProviderError) as error:
                last_error = error
                continue
        assert last_error is not None  # noqa: S101
        raise last_error
