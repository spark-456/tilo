"""LW-05 (ADR-0029 decision 7, PRD 12.2): `GoogleSearchProvider` answers a query with Gemini grounding. It sends only
the `google_search` tool and refuses URL context. The reply is typed: the answer, cited sources with cleaned redirect
URLs (never fetched or resolved here), the queries run, the search suggestions, and usage with `search_queries`.
The secret redactor runs on the query; a fake and a record-and-replay serve dev and CI. No test opens a network call."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from _fake_genai_sdk import FakeAPIError, FakeClient, FakeModelsAPI, FakeUsageMetadata
from tilo_contracts import ProvidersProfile
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError, QuotaError, RequestError, SafetyError
from tilo_providers.interfaces import SearchProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.search import (
    FakeSearchProvider,
    SearchRecordReplayProvider,
    SearchResult,
    clean_source_url,
    redact_query,
    refuse_other_tools,
    search_recording_key,
)

PROJECT, LOCATION = "demo-tilo", "global"
REDIRECT = "https://vertexaisearch.example/grounding-api-redirect/"
SECRET = "sk" + "-" + "A1b2C3d4" * 3  # assembled at runtime: no secret-looking literal in the repo


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)


def _profile(**overrides: object) -> ProvidersProfile:
    fields: dict[str, object] = {
        "provider": "google",
        "model": "example-search-model",
        "context": 1_000_000,
        "caps": ["json", "grounding"],
    }
    fields.update(overrides)
    return ProvidersProfile.model_validate(fields)


def grounded(text: str | None = "Paris is the capital.", **overrides: Any) -> SimpleNamespace:
    """A Gemini reply with grounding metadata (the SDK's field names)."""
    chunks = overrides.pop(
        "chunks", [("Atlas", REDIRECT + "a", "atlas.example"), ("Maps", REDIRECT + "b", "maps.example")]
    )
    metadata = SimpleNamespace(
        web_search_queries=overrides.pop("queries", ["capital of france", "paris population"]),
        grounding_chunks=[
            SimpleNamespace(web=SimpleNamespace(uri=uri, title=title, domain=domain)) for title, uri, domain in chunks
        ],
        search_entry_point=SimpleNamespace(rendered_content=overrides.pop("suggestions", "<div>chips</div>")),
    )
    candidate = SimpleNamespace(finish_reason=overrides.pop("finish", None), grounding_metadata=metadata)
    usage = overrides.pop("usage", FakeUsageMetadata(100, 40, 140))
    assert not overrides, overrides
    return SimpleNamespace(
        text=text, candidates=[candidate], usage_metadata=usage, prompt_feedback=None, function_calls=None
    )


def _provider(api: FakeModelsAPI, **kwargs: Any):
    from tilo_providers.google_search_adapter import GoogleSearchProvider  # noqa: PLC0415

    return GoogleSearchProvider(
        profile=kwargs.pop("profile", _profile()),
        profile_id="search-google",
        project=PROJECT,
        location=LOCATION,
        client=FakeClient(api),
        **kwargs,
    )


def test_LW_05_google_search_provider_is_a_search_provider_that_sends_only_the_google_search_tool():
    api = FakeModelsAPI(generate_content_result=grounded())
    provider = _provider(api)
    assert isinstance(provider, SearchProvider)
    provider.search("capital of france", max_output_tokens=512)
    (call,) = api.calls
    assert call["model"] == "example-search-model" and call["contents"] == "capital of france"
    config = call["config"]
    assert config["tools"] == [{"google_search": {}}]
    assert config["max_output_tokens"] == 512 and config["system_instruction"].strip()
    assert "response_mime_type" not in config  # a grounded reply is cited prose, not JSON mode


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tools": [{"url_context": {}}]},
        {"tools": [{"google_search": {}}, {"url_context": {}}]},
        {"url_context": True},
        {"urlContext": {}},
        {"tools": [{"urlContext": {}}]},
        {"unknown_option": 1},
    ],
)
def test_LW_05_the_url_context_tool_and_any_other_option_are_refused_before_anything_is_sent(kwargs):
    api = FakeModelsAPI(generate_content_result=grounded())
    with pytest.raises(RequestError):
        _provider(api).search("capital of france", **kwargs)
    assert api.calls == []


def test_LW_05_refuse_other_tools_allows_exactly_one_google_search_tool():
    refuse_other_tools([{"google_search": {}}])
    for tools in (
        [],
        [{"url_context": {}}],
        [{"google_search": {}}, {"url_context": {}}],
        [{"google_search": {"x": 1}}],
    ):
        with pytest.raises(RequestError):
            refuse_other_tools(tools)


def test_LW_05_the_reply_is_typed_with_answer_sources_queries_suggestions_and_usage():
    result = _provider(FakeModelsAPI(generate_content_result=grounded())).search("capital of france")
    assert isinstance(result, SearchResult)
    assert result.answer == "Paris is the capital." and result.profile_id == "search-google"
    assert result.queries == ["capital of france", "paris population"]
    assert [(s.title, s.domain, s.redirect_url) for s in result.sources] == [
        ("Atlas", "atlas.example", REDIRECT + "a"),
        ("Maps", "maps.example", REDIRECT + "b"),
    ]
    assert result.suggestions_html == "<div>chips</div>"
    assert result.usage == {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140, "search_queries": 2}
    assert result.query == "capital of france"


def test_LW_05_redirect_urls_stay_unresolved_and_are_never_fetched():
    api = FakeModelsAPI(generate_content_result=grounded())
    result = _provider(api).search("capital of france")
    assert all(s.resolved_url is None for s in result.sources), "LW-08 resolves them through tilo-browser"
    assert [c["method"] for c in api.calls] == ["generate_content"]  # and the socket guard fails any real fetch


def test_LW_05_source_urls_are_cleaned_and_unusable_ones_dropped():
    raw = [
        ("A", "https://user:pw@a.example/p?x=1#frag", None),
        ("dup", "https://a.example/p?x=1", None),
        ("http", "http://plain.example/p", None),
        ("js", "javascript:alert(1)", None),
        ("ctl", "https://c.example/p\x00\nq", None),
        ("blank", "", None),
    ]
    result = _provider(FakeModelsAPI(generate_content_result=grounded(chunks=raw))).search("q")
    assert [s.redirect_url for s in result.sources] == ["https://a.example/p?x=1", "https://c.example/pq"]
    assert clean_source_url("https://" + "a" * 3000 + ".example/") is None
    assert clean_source_url(None) is None  # type: ignore[arg-type]


def test_LW_05_a_reply_without_the_query_list_reports_no_query_count_and_an_empty_list_reports_zero():
    metadata_less = SimpleNamespace(
        text="From memory.", candidates=[SimpleNamespace(finish_reason=None)], usage_metadata=None, prompt_feedback=None
    )
    bare = _provider(FakeModelsAPI(generate_content_result=metadata_less)).search("q")
    assert bare.sources == [] and bare.queries == [] and bare.suggestions_html is None
    assert bare.usage is None or "search_queries" not in bare.usage, "unknown, never 0: the router charges the reserve"
    none_list = grounded(queries=None, usage=FakeUsageMetadata(1, 1, 2))
    assert "search_queries" not in _provider(FakeModelsAPI(generate_content_result=none_list)).search("q").usage
    zero = _provider(FakeModelsAPI(generate_content_result=grounded(queries=[], usage=FakeUsageMetadata(1, 1, 2))))
    assert zero.search("q").usage["search_queries"] == 0


def test_LW_05_the_query_goes_through_the_secret_redactor_before_it_is_sent():
    api = FakeModelsAPI(generate_content_result=grounded())
    result = _provider(api).search(f"price of x using key {SECRET} please")
    (call,) = api.calls
    assert SECRET not in call["contents"] and "[redacted]" in call["contents"]
    assert result.query == call["contents"], "the result names the query that was actually sent"
    assert SECRET not in result.model_dump_json()
    assert SECRET not in redact_query(f"Authorization: Bearer {SECRET}") and "[redacted]" in redact_query(
        "api_key=" + SECRET
    )


@pytest.mark.parametrize("query", ["", "   ", None, 7])
def test_LW_05_an_empty_or_non_text_query_is_a_request_error(query):
    api = FakeModelsAPI(generate_content_result=grounded())
    with pytest.raises(RequestError):
        _provider(api).search(query)
    assert api.calls == []


def test_LW_05_blocked_and_failed_calls_map_onto_provider_errors_without_the_raw_sdk_error(fake_genai_sdk):
    blocked = grounded(finish="SAFETY")
    with pytest.raises(SafetyError):
        _provider(FakeModelsAPI(generate_content_result=blocked)).search("q")
    token = "ya29" + "." + "x" * 30  # a Google access token shape, assembled at runtime
    api = FakeModelsAPI(generate_content_error=FakeAPIError(429, f"quota with {token}"))
    with pytest.raises(QuotaError) as caught:
        _provider(api).search("q")
    assert token not in str(caught.value) and token not in str(caught.value.__cause__)


def test_LW_05_a_profile_without_grounding_is_refused_and_a_real_client_needs_live():
    with pytest.raises(ProviderConfigError):
        _provider(FakeModelsAPI(), profile=_profile(caps=["json"]))
    from tilo_providers.google_search_adapter import GoogleSearchProvider  # noqa: PLC0415

    with pytest.raises(ProviderError, match="LIVE=1"):
        GoogleSearchProvider(profile=_profile(), profile_id="search-google", project=PROJECT, location=LOCATION)


# ---------------------------------------------------------------- fake and record-and-replay


def test_LW_05_the_fake_is_deterministic_redacts_and_is_refused_live(monkeypatch):
    fake = FakeSearchProvider()
    one, two = fake.search("capital of france"), fake.search("capital of france")
    assert one == two and one != fake.search("another query")
    assert one.sources and one.queries == ["capital of france"] and one.usage["search_queries"] == 1
    assert SECRET not in fake.search(f"key {SECRET}").model_dump_json()
    with pytest.raises(RequestError):
        fake.search("q", tools=[{"url_context": {}}])
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    with pytest.raises(ProviderConfigError):
        FakeSearchProvider()


def _recording_provider(tmp_path, live_factory):
    return SearchRecordReplayProvider("search-google", live_factory, tmp_path)


def _never_live():
    raise AssertionError("replay must not build the live provider")


def test_LW_05_replay_serves_a_recording_and_a_miss_names_the_key(tmp_path, monkeypatch):
    live = _provider(FakeModelsAPI(generate_content_result=grounded()))
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    recorded = _recording_provider(tmp_path, lambda: live).search(f"capital of france {SECRET}")
    monkeypatch.delenv("LIVE")
    monkeypatch.delenv("TILO_RECORD")
    key = search_recording_key("search-google", recorded.query, None)
    path = tmp_path / "search-recordings" / f"{key}.json"
    assert path.is_file() and SECRET not in path.read_text(encoding="utf-8")
    replayed = _recording_provider(tmp_path, _never_live).search(f"capital of france {SECRET}")  # same redacted key
    assert replayed == recorded and replayed.sources[0].resolved_url is None
    with pytest.raises(ReplayMissError, match="LIVE=1 TILO_RECORD=1"):
        _recording_provider(tmp_path, _never_live).search("a query nobody recorded")


def test_LW_05_replay_refuses_options_and_a_corrupt_recording_fails_closed(tmp_path):
    with pytest.raises(RequestError):
        _recording_provider(tmp_path, _never_live).search("q", tools=[{"url_context": {}}])
    path = tmp_path / "search-recordings" / f"{search_recording_key('search-google', 'q', None)}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"result": {"answer": 3}}), encoding="utf-8")
    with pytest.raises(ProviderError, match="unreadable or malformed"):
        _recording_provider(tmp_path, _never_live).search("q")


def test_LW_05_live_only_with_the_live_switch_or_permission(tmp_path, monkeypatch):
    built: list[int] = []

    def factory():
        built.append(1)
        return _provider(FakeModelsAPI(generate_content_result=grounded()))

    with pytest.raises(ReplayMissError):
        _recording_provider(tmp_path, factory).search("q")
    assert built == []
    monkeypatch.setenv("LIVE", "1")
    _recording_provider(tmp_path, factory).search("q")
    assert built == [1] and not list(tmp_path.rglob("*.json")), "no recording without TILO_RECORD=1"


def test_LW_05_build_search_provider_picks_fake_or_replay_and_refuses_other_adapters(tmp_path):
    from tilo_providers.search import build_search_provider  # noqa: PLC0415

    config = _config({"fake": ("fake", "fake-search", ["grounding"]), "g": ("google", "m", ["json", "grounding"])})
    assert isinstance(
        build_search_provider("search", config, fixtures_dir=tmp_path, profile_id="fake"), FakeSearchProvider
    )
    replay = build_search_provider("search", config, fixtures_dir=tmp_path, profile_id="g")
    assert isinstance(replay, SearchRecordReplayProvider)
    for bad in ({"x": ("google", "m", ["json"])}, {"x": ("openai_compat", "m", ["grounding"])}):
        with pytest.raises(ProviderConfigError):
            build_search_provider("search", _config(bad), fixtures_dir=tmp_path, profile_id="x")


def _config(profiles: dict[str, tuple[str, str, list[str]]]):
    from tilo_contracts import ProvidersModels, ProvidersPrices  # noqa: PLC0415
    from tilo_providers.config import ProvidersConfig  # noqa: PLC0415

    entries = {}
    for name, (provider, model, caps) in profiles.items():
        entries[name] = {"provider": provider, "model": model, "context": 1000, "caps": caps}
        if provider == "openai_compat":
            entries[name].update(base_url="https://example.test/v1", api_key_env="EXAMPLE_KEY")
    first = next(iter(profiles))
    models = ProvidersModels.model_validate(
        {
            "example": True,
            "profiles": entries,
            "roles": {"search": {"primary": first, "fallback": first}},
            "rules": {"deny": []},
        }
    )
    prices = ProvidersPrices.model_validate(
        {
            "status": "unset",
            "effective_date": None,
            "source": None,
            "currency": "USD",
            "credit_usd": 0.005,
            "profiles": {n: {"input": None, "output": None} for n in profiles},
        }
    )
    return ProvidersConfig(models=models, prices=prices)
