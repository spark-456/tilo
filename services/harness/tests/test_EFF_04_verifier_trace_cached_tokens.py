"""EFF-04b (PRD 6.6; ADR-0022 decision 7): the Verifier's trace sums cached input tokens only when every
model call it counts in `tokens_in` reported one. Otherwise the key is left out: unknown, never 0 and never null.
"""

from __future__ import annotations

from typing import Any

from tilo_harness.verifier import _trace
from tilo_providers.interfaces import GenerateResponse


def _response(usage: dict[str, int] | None) -> GenerateResponse:
    return GenerateResponse(text="ok", profile_id="small", usage=usage)


def _usage(tokens_in: int, cached: int | None, tokens_out: int = 10) -> dict[str, int]:
    usage = {"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out}
    return usage if cached is None else usage | {"cached_tokens": cached}


def test_EFF_04_trace_sums_cached_tokens_when_every_call_reported_one() -> None:
    trace = _trace([_response(_usage(1000, 600)), _response(_usage(500, 0)), _response(_usage(300, 300))])
    assert trace["tokens_in"] == 1800 and trace["tokens_cached"] == 900


def test_EFF_04_trace_leaves_the_key_out_when_one_call_did_not_report_it() -> None:
    trace = _trace([_response(_usage(1000, 600)), _response(_usage(500, None))])
    assert trace["tokens_in"] == 1500
    assert "tokens_cached" not in trace, "unknown, not a partial sum and not 0"


def test_EFF_04_trace_leaves_the_key_out_when_no_call_reported_usage_or_a_count() -> None:
    assert "tokens_cached" not in _trace([_response(_usage(100, None))])
    assert "tokens_cached" not in _trace([_response(None)])
    assert _trace([]) == {}


def test_EFF_04_trace_reports_a_known_miss_as_zero_not_as_a_missing_key() -> None:
    assert _trace([_response(_usage(400, 0))])["tokens_cached"] == 0


def test_EFF_04_trace_never_writes_null_or_a_bad_count_and_never_exceeds_tokens_in() -> None:
    bad: list[Any] = [-1, True, 2.5, "7", None, 5000]  # 5000 > the call's input: EV-16 would refuse the event
    for value in bad:
        usage: dict[str, Any] = _usage(1000, None) | {"cached_tokens": value}
        # model_construct skips pydantic's coercion, which would turn True or "7" into a whole number
        trace = _trace([GenerateResponse.model_construct(text="ok", profile_id="small", usage=usage)])
        assert "tokens_cached" not in trace, f"{value!r} must read as unknown"
