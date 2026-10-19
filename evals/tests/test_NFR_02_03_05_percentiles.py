"""NFR-02, NFR-03, NFR-05 (PRD 17.1): the percentile helper behind the latency report.

`percentiles(samples) -> {"p50", "p95", "n"}`, nearest rank: the value at rank ceil(p/100 * n) (1-based) of the sorted
samples. It always returns a value that was measured (no interpolation, so no invented figure). Empty input raises
ValueError and never returns 0 (a zero would read as "instant"); so do a NaN, an infinity and a negative sample.
"""

import math

import pytest
from _latency_lib import (
    _offline_env,  # noqa: F401  (autouse: no live switch, no network)
    latency,
)
from hypothesis import given, settings
from hypothesis import strategies as st

_SAMPLES = st.lists(
    st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False), min_size=1, max_size=200
)


def test_NFR_02_percentiles_of_one_to_ten_are_nearest_rank():
    result = latency().percentiles([float(i) for i in range(1, 11)])

    assert result == {"p50": 5.0, "p95": 10.0, "n": 10}, "rank ceil(0.5*10)=5 and ceil(0.95*10)=10"


def test_NFR_03_percentiles_of_one_to_twenty_and_one_to_hundred():
    twenty = latency().percentiles([float(i) for i in range(1, 21)])
    hundred = latency().percentiles([float(i) for i in range(1, 101)])

    assert (twenty["p50"], twenty["p95"], twenty["n"]) == (10.0, 19.0, 20), "ranks 10 and ceil(19.0)=19"
    assert (hundred["p50"], hundred["p95"], hundred["n"]) == (50.0, 95.0, 100)


def test_NFR_05_percentiles_p95_of_twenty_is_not_the_maximum():
    samples = [10.0] * 19 + [5000.0]  # one slow outlier in twenty

    result = latency().percentiles(samples)

    assert result["p95"] == 10.0, "rank 19 of 20: the single outlier is above p95"
    assert result["p50"] == 10.0 and result["n"] == 20


def test_NFR_02_percentiles_single_sample_is_every_percentile():
    assert latency().percentiles([123.5]) == {"p50": 123.5, "p95": 123.5, "n": 1}


def test_NFR_02_percentiles_two_samples():
    assert latency().percentiles([9.0, 1.0]) == {"p50": 1.0, "p95": 9.0, "n": 2}, "ranks ceil(1)=1 and ceil(1.9)=2"


def test_NFR_03_percentiles_accept_unsorted_input_and_do_not_reorder_it():
    samples = [7.0, 1.0, 9.0, 3.0, 5.0, 2.0, 8.0, 4.0, 10.0, 6.0]
    before = list(samples)

    result = latency().percentiles(samples)

    assert result == {"p50": 5.0, "p95": 10.0, "n": 10}
    assert samples == before, "the caller's list is left as it was"


def test_NFR_03_percentiles_accept_ints_and_ties():
    result = latency().percentiles([4, 4, 4, 100, 4])

    assert (result["p50"], result["p95"], result["n"]) == (4, 100, 5), "rank 3 of 5 and rank 5 of 5"


def test_NFR_02_percentiles_empty_input_raises_value_error_never_zero():
    with pytest.raises(ValueError):
        latency().percentiles([])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -1.0])
def test_NFR_05_percentiles_refuse_a_sample_that_is_not_a_duration(bad):
    with pytest.raises(ValueError):
        latency().percentiles([1.0, 2.0, bad])


@settings(max_examples=100, deadline=None)
@given(_SAMPLES)
def test_NFR_03_percentiles_property_result_is_a_measured_value_between_min_and_max(samples):
    result = latency().percentiles(samples)

    assert result["n"] == len(samples)
    assert result["p50"] in samples and result["p95"] in samples, "nearest rank never interpolates"
    assert min(samples) <= result["p50"] <= result["p95"] <= max(samples)


@settings(max_examples=100, deadline=None)
@given(_SAMPLES)
def test_NFR_03_percentiles_property_enough_samples_sit_at_or_below_each_percentile(samples):
    result = latency().percentiles(samples)
    n = len(samples)

    assert sum(s <= result["p50"] for s in samples) >= math.ceil(0.5 * n)
    assert sum(s <= result["p95"] for s in samples) >= math.ceil(0.95 * n)
    assert sum(s < result["p50"] for s in samples) < math.ceil(0.5 * n), "and it is the smallest such value"
    assert sum(s < result["p95"] for s in samples) < math.ceil(0.95 * n)


@settings(max_examples=100, deadline=None)
@given(_SAMPLES, st.randoms())
def test_NFR_05_percentiles_property_order_of_arrival_does_not_matter(samples, rnd):
    shuffled = list(samples)
    rnd.shuffle(shuffled)

    assert latency().percentiles(shuffled) == latency().percentiles(samples)
