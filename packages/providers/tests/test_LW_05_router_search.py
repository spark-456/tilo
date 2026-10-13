"""LW-05 (ADR-0029 decisions 1, 2, 7): `Router.search` reserves `reserve_units * per_1k / 1000` under the PL-03 budget
check before it sends; a reply that reports its query count is charged that count, a reply without it is charged the
reserve, an overrun is charged in full and recorded on the attempt. Cached input tokens are charged at `cached_input`.
A role that goes live is refused at the wrong region. Prices below are fake: 1 query costs 2.8 credits."""

from __future__ import annotations

import pathlib
from typing import Any

import pytest
import yaml
from tilo_providers.config import ProviderConfigError, ProvidersConfig, load_providers_config
from tilo_providers.errors import QuotaError
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, SearchProvider
from tilo_providers.router import (
    BudgetExceededError,
    Router,
    RouterExhaustedError,
    RouterRequestError,
    TokenCapExceededError,
)
from tilo_providers.search import SearchResult

REPO = pathlib.Path(__file__).resolve().parents[3]
QUERY = "capital of france"  # 17 bytes: about 9 tokens as the router estimates
TOKENS_CREDITS = (1000 * 1.0 + 500 * 2.0) / 1e6 / 0.005  # one reply of 1000 in, 500 out: 0.4 credits
QUERY_CREDITS = 14 / 1000 / 0.005  # 2.8


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_LOCATION"):
        monkeypatch.delenv(name, raising=False)


def make_config(tmp_path: pathlib.Path, **search_role: Any) -> ProvidersConfig:
    profile = {"provider": "google", "context": 1000}
    models = {
        "example": True,
        "profiles": {
            "srch": {**profile, "model": "example-search", "caps": ["json", "grounding"]},
            "cheap": {**profile, "model": "example-cheap", "caps": ["json"]},
        },
        "roles": {
            "search": {
                "primary": "srch",
                "fallback": "srch",
                "reserve_units": 5,
                "max_output_tokens": 4096,
                **search_role,
            },
            "writer": {"primary": "cheap", "fallback": "cheap"},
        },
        "rules": {"deny": []},
    }
    prices = {
        "status": "set",
        "effective_date": "2026-10-01",
        "source": "Fake price sheet for tests.",
        "region": "asia-southeast1",
        "currency": "USD",
        "credit_usd": 0.005,
        "profiles": {
            "srch": {"input": 1.0, "output": 2.0, "unit_price": {"unit": "query", "per_1k": 14}},
            "cheap": {"input": 1.0, "output": 2.0, "cached_input": 0.1},
        },
    }
    (tmp_path / "models.yaml").write_text(yaml.safe_dump(models), encoding="utf-8")
    (tmp_path / "prices.yaml").write_text(yaml.safe_dump(prices), encoding="utf-8")
    return load_providers_config(tmp_path / "models.yaml", tmp_path / "prices.yaml", env={})


class StubSearch(SearchProvider):
    def __init__(self, usage: dict[str, int] | None, error: Exception | None = None) -> None:
        self.usage, self.error = usage, error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def search(self, query: str, **kwargs: Any) -> SearchResult:
        self.calls.append((query, kwargs))
        if self.error is not None:
            raise self.error
        return SearchResult(query=query, answer="Paris.", sources=[], queries=[], profile_id="srch", usage=self.usage)


def reply_usage(**extra: int) -> dict[str, int]:
    return {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500, **extra}


def router(config: ProvidersConfig, stub: StubSearch, tmp_path: pathlib.Path) -> Router:
    return Router(config, fixtures_dir=tmp_path, search_for_profile=lambda profile_id: stub)


def test_LW_05_the_reserve_is_checked_against_the_budget_before_anything_is_sent(tmp_path):
    config, stub = make_config(tmp_path), StubSearch(reply_usage(search_queries=1))
    reserve = 5 * QUERY_CREDITS  # 14 credits
    with pytest.raises(BudgetExceededError):
        router(config, stub, tmp_path).search("search", QUERY, budget=reserve)  # the tokens alone tip it over
    assert stub.calls == [], "nothing over the budget is sent"
    result = router(config, stub, tmp_path).search("search", QUERY, budget=reserve + 2)
    assert result.search_result.answer == "Paris." and len(stub.calls) == 1
    assert stub.calls[0] == (QUERY, {"max_output_tokens": 4096}), "the role's cap, not the router default of 1024"


def test_LW_05_a_reply_that_reports_its_queries_is_charged_that_count(tmp_path):
    config, stub = make_config(tmp_path), StubSearch(reply_usage(search_queries=2))
    result = router(config, stub, tmp_path).search("search", QUERY, budget=100)
    assert result.budget == pytest.approx(100 - TOKENS_CREDITS - 2 * QUERY_CREDITS)
    (attempt,) = result.attempts
    assert (attempt.profile_id, attempt.outcome, attempt.search_queries, attempt.units_overrun) == ("srch", "ok", 2, 0)
    assert (attempt.tokens_in, attempt.tokens_out) == (1000, 500)


def test_LW_05_a_grounded_reply_without_the_query_count_is_charged_the_reserve(tmp_path):
    config, stub = make_config(tmp_path), StubSearch(reply_usage())
    result = router(config, stub, tmp_path).search("search", QUERY, budget=100)
    assert result.budget == pytest.approx(100 - TOKENS_CREDITS - 5 * QUERY_CREDITS)
    assert result.attempts[0].search_queries == 5 and result.attempts[0].units_overrun == 0
    no_usage = router(config, StubSearch(None), tmp_path).search("search", QUERY, budget=100)
    assert 100 - no_usage.budget > 5 * QUERY_CREDITS, "no usage at all: the token estimate plus the reserve"


def test_LW_05_more_queries_than_reserved_are_charged_in_full_and_the_overrun_is_recorded(tmp_path):
    config, stub = make_config(tmp_path), StubSearch(reply_usage(search_queries=8))
    result = router(config, stub, tmp_path).search("search", QUERY, budget=100)
    assert result.budget == pytest.approx(100 - TOKENS_CREDITS - 8 * QUERY_CREDITS)
    assert (result.attempts[0].search_queries, result.attempts[0].units_overrun) == (8, 3)


def test_LW_05_without_a_budget_nothing_is_priced_and_nothing_is_refused(tmp_path):
    config, stub = make_config(tmp_path), StubSearch(reply_usage(search_queries=1))
    result = router(config, stub, tmp_path).search("search", QUERY)
    assert result.budget is None and result.attempts[0].search_queries == 1


def test_LW_05_a_failed_search_is_never_charged_and_exhausts_the_role(tmp_path):
    config, stub = make_config(tmp_path), StubSearch(None, error=QuotaError("slow down"))
    with pytest.raises(RouterExhaustedError) as caught:
        router(config, stub, tmp_path).search("search", QUERY, budget=100)
    (attempt,) = caught.value.attempts
    assert (attempt.outcome, attempt.error_type) == ("error", "QuotaError")


def test_LW_05_the_role_input_cap_refuses_a_long_query_and_a_role_needs_reserve_units(tmp_path):
    config, stub = make_config(tmp_path, max_input_tokens=5), StubSearch(reply_usage())
    with pytest.raises(TokenCapExceededError):
        router(config, stub, tmp_path).search("search", QUERY, budget=100)
    assert stub.calls == []
    bare = Router(make_config(tmp_path), fixtures_dir=tmp_path, search_for_profile=lambda p: stub)
    with pytest.raises(Exception, match="reserve_units"):
        bare.search("writer", QUERY)


def test_LW_05_the_dev_search_runs_on_the_fake_at_zero_cost_and_a_bad_query_is_a_request_error(tmp_path):
    config = load_providers_config(REPO / "config" / "models.dev.yaml", REPO / "config" / "prices.yaml", env={})
    dev = Router(config, fixtures_dir=tmp_path)
    result = dev.search("search", QUERY, budget=10)
    assert result.search_result.profile_id == "search-fake" and result.budget == 10
    assert result.attempts[0].search_queries == 1
    with pytest.raises(RouterRequestError):
        dev.search("search", "   ", budget=10)


def test_LW_05_cached_input_tokens_are_charged_at_the_cached_rate_in_generate(tmp_path):
    config = make_config(tmp_path)
    usage = {"input_tokens": 1000, "output_tokens": 0, "total_tokens": 1000, "cached_tokens": 600}
    provider = FakeModelProvider(profile_id="cheap", usage=usage)
    result = Router(config, provider_for_profile=lambda profile_id: provider).generate(
        "writer", GenerateRequest(prompt="hello"), budget=100
    )
    assert result.budget == pytest.approx(100 - (400 * 1.0 + 600 * 0.1) / 1e6 / 0.005)


def test_LW_05_a_router_that_may_go_live_refuses_a_location_other_than_the_price_region(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    with pytest.raises(ProviderConfigError, match="GOOGLE_LOCATION"):
        Router(config, fixtures_dir=tmp_path, live_permitted=True)
    monkeypatch.setenv("GOOGLE_LOCATION", "asia-southeast1")
    Router(config, fixtures_dir=tmp_path, live_permitted=True)
    Router(config, fixtures_dir=tmp_path)  # replay and dev are never checked
