"""tilo_providers.router — role -> ModelProvider router (PL-03, EFF-02, EFF-03; PRD 6.4, 6.6). Business code
calls `Router.generate(role, request, budget=...)` (also `stream`, `embed`), never a model; every attempt is
recorded for the PRD 9.3 trace. Error policy and stream rules: packages/providers/CLAUDE.md."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any, Literal

from tilo_providers.config import ProvidersConfig
from tilo_providers.errors import (
    MissingCapabilityError,
    OutputTruncatedError,
    ProviderError,
    RequestError,
    SafetyError,
)
from tilo_providers.factory import build_provider
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, SearchProvider
from tilo_providers.media import capabilities_needed, check_parts, estimate_tokens, provider_takes
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.replay import is_live_mode
from tilo_providers.schema_guard import first_error, short
from tilo_providers.search import redact_query

ProviderFor = Callable[[str], ModelProvider]
SearchFor = Callable[[str], SearchProvider]

# PL-03 / EFF-03: a call is reserved at its input plus the role's expected output (`config/expected_output.yaml`; 1024
# when the role has none, never above the call's cap), and refused before sending when its full cap is over twice the
# budget left.
_DEFAULT_EXPECTED_OUTPUT = 1024
_CAP_HEADROOM = 2


class RouterError(Exception):
    """Router-level error; `attempts` holds every attempt made before it was raised. `budget_left` is what is
    left of the call's budget after charging a truncated call (FR-MTR-01); None when it has none or nothing set it."""

    def __init__(
        self, message: str, attempts: list[RouterAttempt] | None = None, budget_left: float | None = None
    ) -> None:
        super().__init__(message)
        self.attempts = list(attempts or [])
        self.budget_left = budget_left


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
    tokens_cached: int | None = None  # EFF-04: cache reads, a part of tokens_in; None is unknown, never 0
    search_queries: int | None = None  # LW-05: the search queries charged (reported, else the role's reserve_units)
    units_overrun: int | None = None  # LW-05: queries beyond reserve_units; they are charged in full (ADR-0029)
    error_type: str | None = None
    reason: str | None = None  # why this attempt was made (the escalation or fallback reason)
    tokens_audio: int | None = None  # LW-06: audio input tokens, a part of tokens_in; None is unknown, never 0
    quoted_credits: float = field(default=0.0, repr=False)  # the pre-call reserve (input + expected output)
    ceiling_credits: float = field(default=0.0, repr=False)  # input + the full cap: a cut reply's charge with no usage


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
    search_result: Any = None  # search()'s `SearchResult`, attempts alongside it (LW-05)
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


def _usage(attempt: RouterAttempt, response: Any) -> None:  # a GenerateResponse or a SearchResult: both carry .usage
    if response.usage:
        attempt.tokens_in, attempt.tokens_out = response.usage.get("input_tokens"), response.usage.get("output_tokens")
        attempt.tokens_cached = response.usage.get("cached_tokens")
        attempt.tokens_audio = response.usage.get("audio_tokens")


def _fail(run: RouterResult, attempt: RouterAttempt, error: Exception, *, output_started: bool = False) -> None:
    """Records a failed candidate. Returns (the router falls back) for quota, retryable, base ProviderError,
    EFF-03 cap refusals and any unexpected exception (NotImplementedError, an adapter bug); raises a
    RouterError carrying every attempt, the adapter's error as `__cause__`, for everything with no fallback.
    A reply cut at its output cap is terminal (EFF-02): every candidate of a call is sent the same cap (BQ-63), so a
    sibling would burn the same tokens again; the live runner's own retry builds a new request with a larger cap."""
    attempt.outcome = "safety_blocked" if isinstance(error, SafetyError) else "error"
    attempt.error_type, run.last_error = type(error).__name__, error
    where = f"PL-03: role {run.role_id!r} profile {attempt.profile_id!r}"
    if isinstance(error, RequestError):  # the request itself is bad: no fallback
        raise RouterRequestError(f"{where} rejected the request: {error}", run.attempts) from error
    if isinstance(error, SafetyError):  # stream/embed; generate() turns this into a safety_blocked result
        raise RouterSafetyError(f"{where} blocked on safety grounds: {error}", run.attempts) from error
    if output_started:  # answers are never spliced
        raise StreamInterruptedError(f"{where} failed after output started", run.attempts) from error
    if isinstance(error, OutputTruncatedError):  # no sibling: the same cap burns the same tokens
        cap = run.request.max_output_tokens
        message = f"{where} reply truncated at its max_output_tokens cap of {cap}; not retried at the same cap"
        raise RouterExhaustedError(message, run.attempts, run.budget) from error


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
        self,
        config: ProvidersConfig,
        *,
        provider_for_profile: ProviderFor | None = None,
        fixtures_dir: Any = None,
        live_permitted: bool = False,
        search_for_profile: SearchFor | None = None,
        role_thinking: bool = True,
    ) -> None:
        if provider_for_profile is None and fixtures_dir is None:
            raise RouterError("Router needs either provider_for_profile or fixtures_dir")
        self._config, self._provider_for_profile, self._fixtures_dir = config, provider_for_profile, fixtures_dir
        self._search_for_profile = search_for_profile
        self._role_thinking = role_thinking  # False: never fill a role's `thinking` (the live smoke sends none)
        self._live_permitted = live_permitted  # SEC-15: set by the caller that decided this router may go live
        if live_permitted:
            config.check_live()  # ADR-0029 decisions 3 and 4: no live metering at the wrong region or past a promotion

    def _provider(self, role_id: str, profile_id: str) -> ModelProvider:
        if self._provider_for_profile is not None:
            return self._provider_for_profile(profile_id)
        return build_provider(
            role_id,
            self._config,
            fixtures_dir=self._fixtures_dir,
            profile_id=profile_id,
            live_permitted=self._live_permitted,
        )

    def _candidates(self, role_id: str, capability: Capability | None, media: Collection[str] = ()) -> list[str]:
        """The role's profiles in cascade order that declare `capability` and the capability of each media part
        (`media`, LW-06: vision, documents, audio, video): a profile without one is never picked for that part."""
        role = self._config.roles[role_id]
        ids = list(role.cascade or dict.fromkeys(p for p in (role.primary, role.fallback) if p))
        needed = {c for c in (capability, *map(Capability, sorted(media))) if c is not None}
        ids = [p for p in ids if needed <= set(map(Capability, self._config.profiles[p].caps))]
        if not ids:
            what = repr(capability) if not media else f"{sorted(c.value for c in needed)}"
            raise RouterExhaustedError(f"PL-03: role {role_id!r} has no candidate with capability {what}")
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
            if isinstance(error, OutputTruncatedError):
                self._charge_truncated(run, attempt, error)
            _fail(run, attempt, error)
        else:
            run.attempts.append(attempt)
        finally:
            attempt.latency_ms = (time.perf_counter() - start) * 1000

    def _start(self, role_id: str, req: GenerateRequest, outs: list[str] | None, cap: Any, budget: Any) -> RouterResult:
        parts = list(req.parts) if req.parts else req.parts  # a snapshot: the caller's list cannot change under the run
        try:
            check_parts(parts)  # LW-06: count, bytes, types, sha256, pages; a URI part is refused (ADR-0018 T8)
        except RequestError as error:
            raise RouterRequestError(f"LW-06: role {role_id!r} rejected the request: {error}") from error
        role, candidates = self._config.roles[role_id], self._candidates(role_id, cap, capabilities_needed(parts))
        max_output = next(n for n in (req.max_output_tokens, role.max_output_tokens, 1024) if n is not None)  # BQ-63
        request = req.model_copy(update={"max_output_tokens": max_output, "parts": parts})
        return RouterResult(role_id, request, candidates, budget, raw_prompt=req.prompt, tool_outputs=list(outs or []))

    def _prepare(
        self, run: RouterResult, profile_id: str, provider: ModelProvider, prompt: str | None = None
    ) -> tuple[GenerateRequest, float, float]:
        """EFF-03 with this candidate's own `count_tokens`, on everything sent (`_input_text`): compact the
        role's input to max_input_tokens (or refuse a repair `prompt` over it), then price the call (PL-03).
        Never sends anything over the cap."""
        cap = self._config.roles[run.role_id].max_input_tokens
        media, audio = self._media(run, profile_id)
        measure = lambda text: provider.count_tokens(_input_text(run.request, text)) + media  # noqa: E731
        if prompt is None:
            prompt = _compact(run.role_id, cap, run.raw_prompt, run.tool_outputs, measure)
        elif cap is not None and measure(prompt) > cap:
            raise TokenCapExceededError(f"EFF-03: role {run.role_id!r} repair prompt is over its cap of {cap}")
        sent = run.request.model_copy(update={"prompt": prompt})
        role = self._config.roles[run.role_id]
        if (
            self._role_thinking
            and sent.thinking_level is None
            and role.thinking
            and Capability.THINKING.value in self._config.profiles[profile_id].caps
        ):
            # BQ-LE2E-10: the role's `thinking` is the default for a caller that sets none (an explicit level wins), and
            # only a profile that declares the thinking capability is sent one (the others would answer a 400).
            sent = sent.model_copy(update={"thinking_level": role.thinking})
        cap = sent.max_output_tokens or 0
        expected = min(self._config.expected_output.get(run.role_id, _DEFAULT_EXPECTED_OUTPUT), cap)
        text = _input_text(sent, prompt)
        return sent, *self._quote(run, profile_id, provider, text, cap, expected, media=media, audio=audio)

    def _media(self, run: RouterResult, profile_id: str) -> tuple[int, int]:
        """LW-06, per candidate and before anything is sent: (media tokens, of which audio) from the profile's
        `media_tokens`, an upper bound that goes into the EFF-03 cap and the PL-03 price. A profile without
        `media_tokens`, whose adapter cannot take a part's type, or with no `audio_input` price for an audio part
        gets no media: it is recorded as a missing capability and the next candidate is tried."""
        parts = run.request.parts
        if not parts:
            return 0, 0
        profile = self._config.profiles[profile_id]
        if profile.media_tokens is None:
            raise MissingCapabilityError(f"LW-06: profile {profile_id!r} states no media_tokens, so it gets no media")
        for part in parts:
            if not provider_takes(profile.provider, part):
                raise MissingCapabilityError(f"LW-06: profile {profile_id!r} cannot take {part.mime_type}")
        if self._config.prices.status == "set" and any(p.kind == "audio" for p in parts):
            if self._config.prices.profiles[profile_id].audio_input is None:
                raise MissingCapabilityError(f"LW-06: profile {profile_id!r} has no audio_input price for audio")
        return estimate_tokens(parts, profile.media_tokens)

    def _price_day(self) -> date | None:
        """A promotional rate's `valid_until` binds only a call that can go live; a replay uses its recorded dates."""
        return datetime.now(UTC).date() if self._live_permitted or is_live_mode() else None

    def _cost(
        self, profile_id: str, tokens_in: int, tokens_out: int, cached: int = 0, units: int = 0, audio: int = 0
    ) -> float:
        usd = self._config.cost_usd(
            profile_id, tokens_in, tokens_out, cached=cached, units=units, audio=audio, at=self._price_day()
        )
        return self._config.credits(usd)

    def _quote(
        self,
        run: RouterResult,
        profile_id: str,
        provider: ModelProvider,
        text: str,
        out: int,
        expected: int | None = None,
        *,
        media: int = 0,
        audio: int = 0,
    ) -> tuple[float, float]:
        """PL-03: every call (first, repair, fallback, escalation) is priced before it is made (BQ-61). Returns
        (reserve, ceiling): the input (LW-06: media tokens included, audio at its own rate) plus the role's EXPECTED
        output (`expected`, else all of `out`), and the input plus the full cap `out`. Refused (nothing sent) only
        when (a) the reserve is over the budget left, or (b) the ceiling is over twice the budget left. A call past
        both is sent and may settle above its reserve; nothing is taken from the budget until it returns (`_spend`)."""
        if run.budget is None:
            return 0.0, 0.0
        tokens_in = provider.count_tokens(text) + media
        reserve = self._cost(profile_id, tokens_in, out if expected is None else min(expected, out), audio=audio)
        ceiling = reserve if expected is None else self._cost(profile_id, tokens_in, out, audio=audio)
        if reserve > run.budget:
            message = f"PL-03: a call on {profile_id!r} costs ~{reserve:.4f} credits, over {run.budget} left"
            raise BudgetExceededError(message, run.attempts)
        if ceiling > _CAP_HEADROOM * run.budget:
            message = (
                f"PL-03: a call on {profile_id!r} may cost up to ~{ceiling:.4f} credits at its cap, "
                f"over {_CAP_HEADROOM}x the {run.budget} left"
            )
            raise BudgetExceededError(message, run.attempts)
        return reserve, ceiling

    def _spend(
        self, run: RouterResult, profile_id: str, estimate: float, usage: dict[str, Any] | None, units: int = 0
    ) -> None:
        """PL-03: a call that returned is charged from its reported usage (cached tokens at their own rate, `units`
        at the profile's unit price), else its estimate. A call that raised (quota, retryable, ...) is never charged,
        so it cannot starve the fallback. The budget stops at 0."""
        if run.budget is None:
            return
        tokens_in, tokens_out = (usage or {}).get("input_tokens"), (usage or {}).get("output_tokens")
        if isinstance(tokens_in, int) and isinstance(tokens_out, int):
            cached = (usage or {}).get("cached_tokens")
            cached = cached if isinstance(cached, int) and 0 <= cached <= tokens_in else 0
            audio = self._audio_tokens(run, profile_id, usage, tokens_in - cached)
            estimate = self._cost(profile_id, tokens_in, tokens_out, cached, audio=audio)
        run.budget = max(0.0, run.budget - (estimate + (self._cost(profile_id, 0, 0, units=units) if units else 0)))

    def _audio_tokens(self, run: RouterResult, profile_id: str, usage: dict[str, Any] | None, room: int) -> int:
        """LW-06: the audio tokens of a returned call, charged at `audio_input`. A request with no audio part has
        none; a reply that reports no usable count is charged the pre-flight estimate (an upper bound: never
        understated). At most `room`, the input tokens that are not cached."""
        parts = run.request.parts
        if not any(p.kind == "audio" for p in parts or ()):
            return 0
        reported = (usage or {}).get("audio_tokens")
        if isinstance(reported, bool) or not isinstance(reported, int) or reported < 0:
            reported = estimate_tokens(parts, self._config.profiles[profile_id].media_tokens)[1]
        return min(reported, room)

    def _charge_truncated(self, run: RouterResult, attempt: RouterAttempt, error: OutputTruncatedError) -> None:
        """FR-MTR-01: a reply cut at its cap was billed (input, output and thinking tokens). It is charged from the
        usage the provider reported (input plus output and thinking, written to the attempt), else at its input plus
        the whole cap (`ceiling_credits`). This is the one place a call that raised is charged; quota and the like never
        are."""
        spent = (error.output_tokens or 0) + (error.thinking_tokens or 0)
        known = error.output_tokens is not None or error.thinking_tokens is not None
        if isinstance(error.input_tokens, int) and known:
            attempt.tokens_in, attempt.tokens_out = error.input_tokens, spent
            audio = self._audio_tokens(run, attempt.profile_id, None, error.input_tokens)  # LW-06: audio is priced
            credits = self._cost(attempt.profile_id, error.input_tokens, spent, audio=audio)
        else:
            credits = attempt.ceiling_credits  # no usage: a cut reply used its whole cap
        if run.budget is not None:
            run.budget = max(0.0, run.budget - credits)

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
                        sent, estimate, attempt.ceiling_credits = self._prepare(run, profile_id, provider, prompt)
                        attempt.quoted_credits = estimate
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
                sent, estimate, attempt.ceiling_credits = self._prepare(run, profile_id, provider)
                attempt.quoted_credits = estimate
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

    def _search_provider(self, role_id: str, profile_id: str) -> SearchProvider:
        if self._search_for_profile is not None:
            return self._search_for_profile(profile_id)
        from tilo_providers.search import build_search_provider  # noqa: PLC0415

        return build_search_provider(
            role_id,
            self._config,
            fixtures_dir=self._fixtures_dir,
            profile_id=profile_id,
            live_permitted=self._live_permitted,
        )

    def _search_quote(self, run: RouterResult, profile_id: str, query: str, out: int, reserve: int) -> float:
        """PL-03/EFF-03 before a search is sent: refuse a query over the role's `max_input_tokens` (it cannot be
        compacted; the estimate is two bytes a token, an upper bound), then price the call with `reserve` queries
        reserved, since the provider decides how many it runs (ADR-0029 decision 1). Returns the token estimate."""
        cap = self._config.roles[run.role_id].max_input_tokens
        tokens = len(query.encode("utf-8")) // 2 + 1
        if cap is not None and tokens > cap:
            raise TokenCapExceededError(f"EFF-03: role {run.role_id!r} query is over its max_input_tokens cap of {cap}")
        if run.budget is None:
            return 0.0
        estimate = self._cost(profile_id, tokens, out)
        total = estimate + self._cost(profile_id, 0, 0, units=reserve)
        if total > run.budget:
            message = f"PL-03: a search on {profile_id!r} costs ~{total:.4f} credits ({reserve} queries reserved)"
            raise BudgetExceededError(f"{message}, over {run.budget} left", run.attempts)
        return estimate

    def search(
        self, role_id: str, query: str, *, budget: float | None = None, max_output_tokens: int | None = None
    ) -> RouterResult:
        """LW-05: one grounded search through the role's `SearchProvider`. The role's `reserve_units` queries are
        reserved under the budget check before sending; the reply is charged its reported `search_queries` (else
        the reserve), an overrun is charged in full and recorded on the attempt (`units_overrun`)."""
        role = self._config.roles[role_id]
        if role.reserve_units is None:
            raise RouterError(f"LW-05: role {role_id!r} states no reserve_units; a search role must (ADR-0029)")
        reserve = role.reserve_units
        out = next(n for n in (max_output_tokens, role.max_output_tokens, 1024) if n is not None)  # BQ-63
        shown = redact_query(query) if isinstance(query, str) else ""  # the run (and so the Trace) never holds a secret
        request = GenerateRequest(prompt=shown, max_output_tokens=out)
        run = RouterResult(role_id, request, self._candidates(role_id, Capability.GROUNDING), budget, raw_prompt=shown)
        reason: str | None = None
        for profile_id in run.candidates:
            with self._candidate(run, profile_id, reason) as attempt:
                provider = self._search_provider(role_id, profile_id)
                estimate = self._search_quote(run, profile_id, shown, out, reserve)
                result = provider.search(query, max_output_tokens=out)
            if attempt.error_type:
                reason = f"fallback after {attempt.error_type}"
                continue
            reported = (result.usage or {}).get("search_queries")
            units = reported if isinstance(reported, int) and reported >= 0 else reserve  # no count: the reserve
            attempt.search_queries, attempt.units_overrun = units, max(0, units - reserve)
            self._spend(run, profile_id, estimate, result.usage, units)
            _usage(attempt, result)
            return replace(run, search_result=result)
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
                estimate, _ = self._quote(run, profile_id, provider, "\n\n".join(_embed_inputs(request)), 0)
                embedding = provider.embed(request)
            if not attempt.error_type:
                self._spend(run, profile_id, estimate, None)
                return replace(run, embedding=embedding)
            reason = f"fallback after {attempt.error_type}"
        raise _exhausted(run) from run.last_error
