"""PL-03 / EFF-02 / EFF-03 / FR-MTR-01, live run 2 of 8 Oct 2026 (13.5 credits for a simple ask, then a refusal):

* A reply cut at its output cap is terminal for that cap: the Router never falls back to a sibling that would be sent
  the same cap (it would burn the same tokens), and raises a RouterError carrying every attempt with the
  OutputTruncatedError as `__cause__`. Quota, retryable and base provider errors still fall back.
* The Router fills `thinking_level` from the role's configured `thinking` when the caller left it unset (like
  `max_output_tokens`, BQ-63); an explicit value on the request always wins; a role with no `thinking` sends none.
* A call that raised OutputTruncatedError was billed by the provider: the Router charges it from the reported usage
  (input tokens from the error, output plus thinking tokens), else from its pre-call quote. Other raised calls are
  never charged.

Scripted providers only: no network, no live call.
"""

from __future__ import annotations

import pytest
from conftest import ScriptedCall, ScriptedModelProvider
from tilo_providers.errors import OutputTruncatedError, QuotaError, RetryableError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import RouterError, RouterExhaustedError


def _router(config, providers: dict[str, ScriptedModelProvider]):
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile=providers.__getitem__)


def _cut(**counts) -> OutputTruncatedError:
    return OutputTruncatedError("PL-02: the reply hit its max_output_tokens cap", **counts)


def test_PL_03_a_truncated_reply_makes_exactly_one_call_and_never_falls_back(providers_config):
    cut = _cut(output_tokens=0, thinking_tokens=1024)
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=cut)] * 2)
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="would burn the same cap again")])

    with pytest.raises(RouterExhaustedError) as raised:
        _router(providers_config, {"large": primary, "medium": fallback}).generate(
            "director", GenerateRequest(prompt="Draft a brief.")
        )

    assert len(primary.calls) == 1 and fallback.calls == [], "one paid call, no second at the same cap"
    assert raised.value.__cause__ is cut
    assert [a.error_type for a in raised.value.attempts] == ["OutputTruncatedError"]
    assert "1024" in str(raised.value), "the message names the cap that was burned"


def test_PL_03_a_truncated_stream_start_is_terminal_too(providers_config):
    cut = _cut(output_tokens=0, thinking_tokens=1024)
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=cut)])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="never")])

    with pytest.raises(RouterError) as raised:
        list(
            _router(providers_config, {"large": primary, "medium": fallback}).stream(
                "director", GenerateRequest(prompt="Draft a brief.")
            )
        )

    assert fallback.calls == [] and raised.value.__cause__ is cut


@pytest.mark.parametrize("error", [QuotaError("slow down"), RetryableError("503")], ids=["quota", "retryable"])
def test_PL_03_other_failures_still_fall_back(providers_config, error):
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=error)])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="served by the fallback")])

    result = _router(providers_config, {"large": primary, "medium": fallback}).generate(
        "director", GenerateRequest(prompt="hello")
    )

    assert result.response is not None and result.response.text == "served by the fallback"
    assert len(primary.calls) == 1 and len(fallback.calls) == 1


# --- the role's thinking level -------------------------------------------------------------------------------------


def test_PL_03_the_router_fills_the_roles_thinking_when_the_caller_left_it_unset(providers_config):
    primary = ScriptedModelProvider("large", [ScriptedCall(text="ok")])

    _router(providers_config, {"large": primary, "medium": primary}).generate(
        "director", GenerateRequest(prompt="hello")
    )

    assert primary.calls[0].thinking_level == "high", "config BASE_MODELS: director has thinking high"


@pytest.mark.parametrize("level", ["minimal", "low", "medium"])
def test_PL_03_an_explicit_thinking_level_is_never_overridden_by_the_role(providers_config, level):
    primary = ScriptedModelProvider("large", [ScriptedCall(text="ok")])

    _router(providers_config, {"large": primary, "medium": primary}).generate(
        "director", GenerateRequest(prompt="hello", thinking_level=level)
    )

    assert primary.calls[0].thinking_level == level


def test_PL_03_a_role_with_no_thinking_sends_none(providers_config):
    small = ScriptedModelProvider("small", [ScriptedCall(text="ok")])

    _router(providers_config, {"small": small, "medium": small}).generate("narrator", GenerateRequest(prompt="hello"))

    assert small.calls[0].thinking_level is None


def test_PL_03_only_a_profile_with_the_thinking_capability_is_sent_the_roles_level(providers_config):
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=QuotaError("slow down"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="ok")])  # medium declares no `thinking`

    _router(providers_config, {"large": primary, "medium": fallback}).generate(
        "director", GenerateRequest(prompt="hello")
    )

    assert primary.calls[0].thinking_level == "high" and fallback.calls[0].thinking_level is None


# --- billing a truncated call (FR-MTR-01) ----------------------------------------------------------------------------


def test_PL_03_a_truncated_call_is_charged_from_its_reported_usage(providers_config):
    cut = _cut(output_tokens=0, thinking_tokens=500, input_tokens=100)
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=cut)])

    with pytest.raises(RouterError) as raised:
        _router(providers_config, {"large": primary, "medium": primary}).generate(
            "director", GenerateRequest(prompt="hello there"), budget=100.0
        )

    billed = providers_config.credits((100 * 2.0 + 500 * 8.0) / 1e6)  # large: 2.0 in / 8.0 out per million tokens
    assert raised.value.budget_left == pytest.approx(100.0 - billed)
    attempt = raised.value.attempts[-1]
    assert (attempt.tokens_in, attempt.tokens_out) == (100, 500), "output counts the thinking tokens (billed as output)"


def test_PL_03_a_truncated_call_with_no_usage_is_charged_at_its_estimate(providers_config):
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=_cut())])

    with pytest.raises(RouterError) as raised:
        _router(providers_config, {"large": primary, "medium": primary}).generate(
            "director", GenerateRequest(prompt="hello there"), budget=100.0
        )

    quote = providers_config.credits((2 * 2.0 + 1024 * 8.0) / 1e6)  # two prompt words, the Router's default 1024 cap
    assert raised.value.budget_left == pytest.approx(100.0 - quote)
    assert (raised.value.attempts[-1].tokens_in, raised.value.attempts[-1].tokens_out) == (None, None)


def test_PL_03_a_call_that_failed_on_quota_is_not_charged(providers_config):
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=QuotaError("slow down"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="ok", usage={"input_tokens": 2, "output_tokens": 2})])

    result = _router(providers_config, {"large": primary, "medium": fallback}).generate(
        "director", GenerateRequest(prompt="hello"), budget=100.0
    )

    assert result.budget == pytest.approx(100.0 - providers_config.credits((2 * 0.5 + 2 * 2.0) / 1e6))
