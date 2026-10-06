"""EFF-04b (PRD 6.6 "cache-hit rate reported where the provider supports caching"; ADR-0022 decisions 5 and 8).

The eval report is what the nightly job publishes. Its cache-hit rate per role is the sum of `trace.tokens_cached`
over the sum of `trace.tokens_in`, taken over the events that carry the count, weighted by tokens. An event
without the count is unknown: it leaves both sums, is counted, and lowers coverage. A role with no event that
carries the count shows unknown (null), never 0%. The rate is a provider-side measure, not a credit saving.
Recordings only: the report reads stored events and calls no model, with the live switch off.
"""

import json
import os

import pytest
from _evals_lib import add_case, make_event
from tilo_evals import results as results_module
from tilo_evals.__main__ import main


def _ev(seq: int, role: str, tokens_in: int, cached: object = "absent") -> dict:
    trace: dict = {"model_role": role, "profile": "small", "tokens_in": tokens_in, "tokens_out": 10}
    if cached != "absent":
        trace["tokens_cached"] = cached
    return make_event(seq=seq, type="agent.working", trace=trace, credits=1.0)


def _json(repo):
    return json.loads((repo / "results.json").read_text(encoding="utf-8"))


@pytest.fixture
def mixed_pass(fake_repo, monkeypatch):
    """Two cases mixing known, zero and unknown events across three roles."""
    monkeypatch.delenv("LIVE", raising=False)
    first = [_ev(1, "specialist", 1000, 600), _ev(2, "specialist", 500, 0), _ev(3, "specialist", 500)]
    second = [_ev(4, "worker", 800), _ev(5, "worker", 200), _ev(6, "director", 1000, 100), _ev(7, "director", 9000)]
    add_case(fake_repo, "E-PLAN-01", first, credits=3.0)
    add_case(fake_repo, "E-PLAN-02", second + [make_event(seq=8)], credits=4.0)  # a no-trace event is ignored
    assert main(["run", "--pass", "full", "--results-json", "results.json"]) == 0
    return fake_repo


def test_EFF_04_nightly_report_includes_cache_hit_rate_per_role(mixed_pass):
    data = _json(mixed_pass)["cache_hit_rate_per_role"]
    assert set(data) == {"specialist", "worker", "director"}
    spec = data["specialist"]
    assert spec["rate"] == pytest.approx(600 / 1500), "sum cached over sum tokens_in of the events with a count"
    assert (spec["tokens_in"], spec["tokens_cached"], spec["unknown_events"]) == (1500, 600, 1)
    assert spec["coverage"] == pytest.approx(1500 / 2000)

    md = (mixed_pass / "evals" / "results.md").read_text(encoding="utf-8")
    section = md.split("### Cache-hit rate per role", 1)[1].split("\n### ", 1)[0]
    assert "provider-side hit rate, not credit saving" in section
    assert "- specialist: 600 of 1500 input tokens cached (40.0%)" in section


def test_EFF_04_report_is_weighted_by_tokens_not_an_average_of_event_rates(mixed_pass):
    director = _json(mixed_pass)["cache_hit_rate_per_role"]["director"]
    assert director["rate"] == pytest.approx(0.1) and director["tokens_in"] == 1000  # the 9000 unknown tokens stay out


def test_EFF_04_a_role_with_no_count_is_unknown_never_zero_percent(mixed_pass):
    worker = _json(mixed_pass)["cache_hit_rate_per_role"]["worker"]
    assert worker["rate"] is None, "null in JSON"
    assert (worker["tokens_in"], worker["tokens_cached"], worker["unknown_events"]) == (0, 0, 2)
    assert worker["coverage"] == 0.0

    md = (mixed_pass / "evals" / "results.md").read_text(encoding="utf-8")
    line = next(ln for ln in md.splitlines() if ln.startswith("- worker:") and "cached" in ln.lower())
    assert "unknown" in line and "0%" not in line and "0.0%" not in line


def test_EFF_04_a_known_zero_is_a_zero_rate_and_not_unknown(fake_repo):
    add_case(fake_repo, "E-PLAN-01", [_ev(1, "specialist", 400, 0)])
    assert main(["run", "--pass", "full", "--results-json", "results.json"]) == 0
    row = _json(fake_repo)["cache_hit_rate_per_role"]["specialist"]
    assert row["rate"] == 0.0 and row["coverage"] == 1.0 and row["unknown_events"] == 0
    md = (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")
    assert "- specialist: 0 of 400 input tokens cached (0.0%)" in md


def test_EFF_04_low_coverage_is_flagged_in_the_report_and_the_threshold_is_a_named_constant(mixed_pass):
    threshold = results_module.LOW_CACHE_COVERAGE
    assert 0 < threshold < 1
    md = (mixed_pass / "evals" / "results.md").read_text(encoding="utf-8")
    section = md.split("### Cache-hit rate per role", 1)[1].split("\n### ", 1)[0]
    lines = {ln.split(":")[0]: ln for ln in section.splitlines() if ln.startswith("- ")}
    assert "low coverage" in lines["- director"].lower(), "10% of its input tokens carry a count"
    assert "low coverage" not in lines["- specialist"].lower(), "75% coverage"


def test_EFF_04_a_pass_with_no_model_events_says_so(fake_repo):
    add_case(fake_repo, "E-PLAN-01", [make_event()])
    assert main(["run", "--pass", "full", "--results-json", "results.json"]) == 0
    assert _json(fake_repo)["cache_hit_rate_per_role"] == {}
    md = (fake_repo / "evals" / "results.md").read_text(encoding="utf-8")
    assert "### Cache-hit rate per role\n- none" in md


def test_EFF_04_the_report_makes_no_model_call_and_needs_no_live_switch(mixed_pass):
    assert "LIVE" not in os.environ


@pytest.mark.parametrize(
    ("cached", "tokens_in"),
    [(-1, 100), (True, 100), (2.5, 100), ("7", 100), (None, 100), (101, 100), (5, None)],
    ids=["negative", "bool", "fraction", "string", "null", "over_tokens_in", "tokens_in_missing"],
)
def test_EFF_04_a_recording_with_a_bad_tokens_cached_is_not_runnable(fake_repo, cached, tokens_in):
    trace = {"model_role": "specialist", "profile": "small", "tokens_in": tokens_in, "tokens_cached": cached}
    add_case(fake_repo, "E-PLAN-01", [make_event(type="agent.working", trace=trace)])
    main(["run", "--pass", "full", "--results-json", "results.json"])
    data = _json(fake_repo)
    assert data["not_runnable"] == ["E-PLAN-01"] and data["ran"] == []
    assert "tokens_cached" in data["not_runnable_reasons"]["E-PLAN-01"]


def test_EFF_04_a_recording_from_before_tokens_cached_existed_reads_as_unknown(fake_repo):
    old = make_event(type="agent.working", trace={"model_role": "specialist", "profile": "small", "tokens_in": 50})
    add_case(fake_repo, "E-PLAN-01", [old])
    assert main(["run", "--pass", "full", "--results-json", "results.json"]) == 0
    row = _json(fake_repo)["cache_hit_rate_per_role"]["specialist"]
    assert row["rate"] is None and row["unknown_events"] == 1
