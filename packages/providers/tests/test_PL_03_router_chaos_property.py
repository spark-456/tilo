"""PL-03 (PRD 6.4) property: whatever a candidate provider raises -- from `count_tokens`, `generate`,
`stream` (before or after its first chunk) or `embed` -- the router only ever returns a `RouterResult` or
raises a `RouterError`; it records one attempt for every candidate it actually touched, in order; and it
never falls back after a `RequestError`, a safety block, or a stream chunk that already reached the
caller. Ticket P0-06 review: every provider interaction goes through one choke point, the budget check
included -- budgets fall between the candidates' prices, so a candidate the budget cannot cover is recorded,
never sent, and the next one tried; BudgetExceededError only when none left fits."""

from __future__ import annotations

from typing import Any

from conftest import build_providers_config, prices_config_for
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_providers.errors import ProviderError, QuotaError, RequestError, RetryableError, SafetyError
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

PROFILES = ["p0", "p1", "p2", "p3"]
ERRORS: list[type[Exception] | None] = [
    None,  # succeed
    QuotaError,
    RetryableError,
    RequestError,
    SafetyError,
    ProviderError,
    NotImplementedError,
    RuntimeError,
]
METHODS = ("count_tokens", "generate", "stream_before", "stream_after", "embed")
NO_FALLBACK = {"RequestError", "SafetyError"}


class ChaosProvider(ModelProvider):
    def __init__(self, profile_id: str, plan: dict[str, type[Exception] | None]) -> None:
        self.profile_id, self.plan = profile_id, plan
        self.touched = self.yielded = self.sent = False

    def _maybe_raise(self, method: str) -> None:
        self.touched = True
        self.sent = self.sent or method != "count_tokens"
        if (error := self.plan[method]) is not None:
            raise error(f"chaos {method} on {self.profile_id}")

    def count_tokens(self, text: str) -> int:
        self._maybe_raise("count_tokens")
        return len(text.split())

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self._maybe_raise("generate")
        return GenerateResponse(text="ok", profile_id=self.profile_id)

    def stream(self, request: GenerateRequest):
        self._maybe_raise("stream_before")
        self.yielded = True
        yield GenerateResponse(text="chunk", profile_id=self.profile_id)
        self._maybe_raise("stream_after")

    def embed(self, request: Any) -> Any:
        self._maybe_raise("embed")
        return {"vectors": [[0.0]]}

    def capabilities(self) -> set[Capability]:
        return {Capability.JSON}

    def price(self) -> PriceQuote:
        return PriceQuote(input=1.0, output=1.0)


def _config(candidates: list[str]):
    profiles = {p: {"provider": "fake", "model": f"fake-{p}-1", "context": 10_000, "caps": ["json"]} for p in PROFILES}
    role = {"primary": candidates[0], "fallback": candidates[-1], "cascade": candidates, "max_input_tokens": 1_000}
    models = {"example": True, "profiles": profiles, "roles": {"chaos": role}, "rules": {"deny": []}}
    # p0 is the cheapest, each next profile costs 10x more, so a drawn budget can fall between two of them
    return build_providers_config(
        models, prices_config_for({p: (0.1 * 10**i, 0.2 * 10**i) for i, p in enumerate(PROFILES)})
    )


def _unit_cost(config) -> float:
    """What one call on p0 costs: the 3-word prompt plus the default 1024 output tokens (BQ-61)."""
    return config.credits((3 * 0.1 + 1024 * 0.2) / 1_000_000)


plans = st.fixed_dictionaries({m: st.sampled_from(ERRORS) for m in METHODS})


@given(
    candidates=st.lists(st.sampled_from(PROFILES), min_size=1, max_size=4, unique=True),
    plan_by_profile=st.fixed_dictionaries({p: plans for p in PROFILES}),
    operation=st.sampled_from(["generate", "stream", "embed"]),
    budget_in_p0_calls=st.one_of(st.none(), st.sampled_from([0.0, 0.5, 1.5, 5.0, 15.0, 50.0, 150.0, 500.0, 1e12])),
)
@settings(max_examples=300, deadline=None)
def test_PL_03_router_only_returns_a_result_or_raises_a_router_error_under_chaos(
    candidates, plan_by_profile, operation, budget_in_p0_calls
):
    from tilo_providers.router import BudgetExceededError, Router, RouterError, RouterResult  # noqa: PLC0415

    providers = {p: ChaosProvider(p, plan_by_profile[p]) for p in PROFILES}
    config = _config(candidates)
    budget = None if budget_in_p0_calls is None else budget_in_p0_calls * _unit_cost(config)
    router = Router(config, provider_for_profile=providers.__getitem__)
    request = GenerateRequest(prompt="summarise the quarter")

    received: list[GenerateResponse] = []
    raised = False
    try:
        if operation == "generate":
            run = router.generate("chaos", request, budget=budget)
        elif operation == "embed":
            run = router.embed("chaos", {"input": ["summarise the quarter"]}, budget=budget)
        else:
            run = router.stream("chaos", request, budget=budget)
            for chunk in run:
                received.append(chunk)
        assert isinstance(run, RouterResult)
        attempts = run.attempts
    except RouterError as error:  # anything else escaping fails the test
        attempts, raised = error.attempts, True
        if isinstance(error, BudgetExceededError):  # only when the budget ended the run
            assert attempts and attempts[-1].error_type == "BudgetExceededError"

    # One attempt per candidate actually touched, in candidate order, and the touched ones are a prefix.
    touched = [p for p in candidates if providers[p].touched]
    assert [a.profile_id for a in attempts] == touched
    assert touched == candidates[: len(touched)]

    # Only the last attempt may be ok; an ok run ends on an ok (or safety_blocked) attempt.
    assert all(a.outcome != "ok" and a.error_type for a in attempts[:-1])
    if not raised:
        assert attempts[-1].outcome == ("ok" if run.outcome == "ok" else "safety_blocked")

    # No fallback after a RequestError or a safety block.
    for index, attempt in enumerate(attempts):
        if attempt.error_type in NO_FALLBACK:
            assert index == len(attempts) - 1, f"fell back after {attempt.error_type}"

    # No fallback after a stream chunk reached the caller, and no chunk from any other candidate.
    yielded = [p for p in candidates if providers[p].yielded]
    if operation == "stream" and received:
        assert yielded and yielded[-1] == touched[-1] == received[0].profile_id
        assert {c.profile_id for c in received} == {touched[-1]}

    # PL-03: a candidate the budget cannot cover is never sent; the budget is never overspent.
    for attempt in attempts:
        if attempt.error_type == "BudgetExceededError":
            assert budget is not None and not providers[attempt.profile_id].sent
    if not raised and budget is not None:
        assert run.budget is not None and run.budget >= 0
