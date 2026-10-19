"""PL-LIVE-E2E / FR-MTR-01, live run 2 of 8 Oct 2026: a call that stopped `truncated` was billed by the provider but the
meter charged it at a word count and the full output cap. A truncated call is now metered from the usage the error
reports (input tokens from the error, output plus thinking tokens), and only when none is known from the provider's own
count of the input and the cap the call burned. A response that carries no usage is counted by the provider's own token
count, not by words. Fakes only: no network, no live call."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from _live_e2e_lib import (
    bank_case,
    live_e2e,
    network_guard,  # noqa: F401  (autouse fixture)
    run_direct,
)
from tilo_providers.config import load_providers_config
from tilo_providers.errors import OutputTruncatedError, truncated_message
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

PROFILE = "flash-38"


class _Inner(ModelProvider):
    """Raises or answers as told, and counts tokens as three per word (so a word count is never the right answer)."""

    def __init__(self, outcome: Exception | GenerateResponse) -> None:
        self._outcome = outcome

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    def stream(self, request: GenerateRequest) -> Any:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        return 3 * len(text.split())

    def provider_count_tokens(self, text: str) -> int:  # what RecordReplayProvider offers a meter
        return self.count_tokens(text)

    def capabilities(self) -> set[Capability]:
        return {Capability.JSON}

    def price(self) -> PriceQuote:
        return PriceQuote(input=0.0, output=0.0)


def _meter() -> Any:
    module = live_e2e()
    config = load_providers_config(module._REPO / "config" / "models.yaml", module._REPO / "config" / "prices.yaml")
    return module, module._Meter(config, 1000.0)


def _call(outcome: Exception | GenerateResponse, cap: int | None = 2048) -> tuple[Any, Any, GenerateRequest]:
    module, meter = _meter()
    request = GenerateRequest(system="be brief", prompt="one two three four", max_output_tokens=cap)
    metered = module._Metered(_Inner(outcome), "writer", PROFILE, meter)
    try:
        metered.generate(request)
    except OutputTruncatedError:
        pass
    return module, meter, request


def _cut(**counts: int | None) -> OutputTruncatedError:
    return OutputTruncatedError(truncated_message(counts.get("output_tokens"), counts.get("thinking_tokens")), **counts)


def test_PL_LIVE_E2E_33_a_truncated_call_is_metered_from_the_usage_its_error_reports() -> None:
    _, meter, _ = _call(_cut(input_tokens=700, output_tokens=0, thinking_tokens=2048))

    (row,) = meter.rows.values()
    assert (row.calls, row.tokens_in, row.tokens_out) == (1, 700, 2048)
    assert row.credits == pytest.approx(meter.cost(PROFILE, 700, 2048))
    assert meter.quoted_calls == 0, "the call is billed from usage, not from a quote"


def test_PL_LIVE_E2E_33_reported_visible_output_and_thinking_are_both_billed_as_output() -> None:
    _, meter, _ = _call(_cut(input_tokens=700, output_tokens=300, thinking_tokens=1000))

    (row,) = meter.rows.values()
    assert row.tokens_out == 1300


def test_PL_LIVE_E2E_33_with_no_usage_the_input_is_the_providers_count_and_the_output_the_cap_burned() -> None:
    _, meter, request = _call(_cut(), cap=2048)

    (row,) = meter.rows.values()
    assert row.tokens_in == 3 * len("be brief one two three four".split()), "the provider's count, not words"
    assert row.tokens_out == 2048, "a cut reply used its whole cap"
    assert row.credits == pytest.approx(meter.cost(PROFILE, row.tokens_in, 2048))


def test_PL_LIVE_E2E_33_a_response_with_no_usage_is_counted_by_the_providers_own_token_count() -> None:
    _, meter, _ = _call(GenerateResponse(text="alpha beta gamma", profile_id=PROFILE))

    (row,) = meter.rows.values()
    assert row.tokens_in == 3 * len("be brief one two three four".split())
    assert row.tokens_out == 3 * 3


def test_PL_LIVE_E2E_33_a_response_with_usage_still_uses_the_usage() -> None:
    usage = {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33}
    _, meter, _ = _call(GenerateResponse(text="alpha beta", profile_id=PROFILE, usage=usage))

    (row,) = meter.rows.values()
    assert (row.tokens_in, row.tokens_out) == (11, 22)


def test_PL_LIVE_E2E_33_the_reports_totals_are_the_sum_of_every_attempt_including_the_truncated_ones(
    tmp_path: Path,
) -> None:
    from test_PL_LIVE_E2E_writer_output_cap import _TruncatingWorld  # noqa: PLC0415

    module = live_e2e()
    world = _TruncatingWorld(script=bank_case("B-007").director, needs={"writer": 10**6})

    report, _ = run_direct(tmp_path, world=world)

    writer = [r for r in report.rows if r.role == "writer"]
    assert sum(r.calls for r in writer) == 2, "the capped call and the one doubled retry: no sibling, no third"
    assert sum(r.tokens_out for r in writer) == module._OUT["writer"] * 3, "each cut call burned the cap it was sent"
    assert report.total_credits == pytest.approx(math.fsum(r.credits for r in report.rows))
    assert report.total_credits > 0
