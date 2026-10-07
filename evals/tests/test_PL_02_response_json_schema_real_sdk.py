"""PL-02 (PRD 6.4) live-run fix: the Director's schemas must reach the send through the REAL `google.genai` SDK.

Incident (live batch B-007, twice, "director role: unknown", 12.39 credits counted per attempt, nothing sent): the
adapter passed `GenerateRequest.response_schema` as `GenerateContentConfig(response_schema=...)`, the OpenAPI-subset
`Schema` type. The SDK validated the brief's JSON Schema against it while building the request body and raised a
pydantic `ValidationError` (`uniqueItems` is extra_forbidden; `type` as a list). The same dict as
`response_json_schema=` goes out as-is. The fake SDK of the providers tests cannot see this, because it accepts any
kwargs; these tests use the real SDK and cut the network at the one place the SDK sends from,
`BaseApiClient.request`, where a stub raises a sentinel. The sentinel (not a ValidationError) proves the request was
built and handed to the transport. No credentials, no network, no paid call.

Covers the three Director schemas: the brief (`tilo_planning.brief.output_schema`), the approaches and the plan
compiler replies. Also pins (c) and (d) of the fix: a call that failed before it was sent is never counted, and a call
that returned no usage is charged its quote without inventing output tokens.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from google import genai
from google.auth.credentials import AnonymousCredentials
from google.genai import _api_client
from tilo_contracts import ProvidersProfile
from tilo_evals import live_e2e
from tilo_planning import approaches, brief, compiler
from tilo_providers.config import load_providers_config
from tilo_providers.errors import RequestError
from tilo_providers.google_adapter import GoogleModelProvider
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.vertex_smoke import classify


class _NotSent(Exception):
    """Raised by the stub at the transport: the request was built and reached the send."""


SCHEMAS = {
    "brief": brief.output_schema,
    "approaches": approaches._Reply.model_json_schema,
    "compiler": compiler._Reply.model_json_schema,
}


def _provider(sent: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> GoogleModelProvider:
    def stub(self: object, http_method: str, path: str, request_dict: dict[str, Any], *_a: Any, **_k: Any) -> None:
        sent.append(request_dict)
        raise _NotSent

    monkeypatch.setattr(_api_client.BaseApiClient, "request", stub)
    client = genai.Client(
        vertexai=True, project="tilo-test-project", location="global", credentials=AnonymousCredentials()
    )
    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "placeholder-model", "context": 1_000_000, "caps": ["json", "thinking"]}
    )
    return GoogleModelProvider(
        profile=profile, profile_id="flash-38", project="tilo-test-project", location="global", client=client
    )


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_PL_02_the_director_schema_reaches_the_send_through_the_real_sdk(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema, sent = SCHEMAS[name](), []
    provider = _provider(sent, monkeypatch)
    with pytest.raises(_NotSent):  # a ValidationError here is the incident
        provider.generate(GenerateRequest(prompt="hello", response_schema=schema, max_output_tokens=16384))
    assert len(sent) == 1
    generation = sent[0]["generationConfig"]
    assert generation["responseMimeType"] == "application/json"
    assert generation["responseJsonSchema"] == json.loads(json.dumps(schema)), "the schema goes out unchanged"
    assert "responseSchema" not in generation
    assert generation["maxOutputTokens"] == 16384


def test_PL_02_the_same_schema_as_the_openapi_subset_field_is_what_the_sdk_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The root cause, kept as a canary: if a future SDK accepts this, the adapter's choice may be revisited."""
    from google.genai import types  # noqa: PLC0415

    sent: list[dict[str, Any]] = []
    provider = _provider(sent, monkeypatch)
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=brief.output_schema())
    with pytest.raises(Exception) as caught:  # noqa: PT011
        provider._client.models.generate_content(model="m", contents="hi", config=config)
    assert type(caught.value).__name__ == "ValidationError" and not sent


def test_PL_02_a_request_the_real_sdk_cannot_build_is_rejected_and_names_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, Any]] = []
    provider = _provider(sent, monkeypatch)
    marker = "PROMPT-TEXT-MARKER"
    # A tool the SDK's own types forbid is a client-side pydantic error, raised before the transport.
    bad = GenerateRequest(prompt=marker, max_output_tokens=10, tools=[{marker: 1}])
    with pytest.raises(RequestError) as caught:
        provider.generate(bad)
    assert not sent, "nothing reached the transport"
    assert classify(caught.value) == "rejected"
    link, text = caught.value, []
    while link is not None:
        text.append(str(link))
        link = link.__cause__
    assert marker not in " ".join(text)


# --- (c) a call that failed before it was sent is not counted; (d) a quote is not usage -------------------------


def _meter() -> Any:
    config = load_providers_config(live_e2e._REPO / "config" / "models.yaml", live_e2e._REPO / "config" / "prices.yaml")
    return live_e2e._Meter(config, 1000.0)


def test_PL_02_a_call_that_failed_before_it_was_sent_adds_no_credits(monkeypatch: pytest.MonkeyPatch) -> None:
    from google.genai import types  # noqa: PLC0415

    sent: list[dict[str, Any]] = []
    provider = _provider(sent, monkeypatch)
    meter = _meter()
    wrapped = live_e2e._Metered(provider, "director", "flash-38", meter)
    original = types.GenerateContentConfig

    def broken_config(**kwargs: Any) -> Any:
        return original(**{**kwargs, "response_schema": brief.output_schema()})  # the incident's request

    monkeypatch.setattr(types, "GenerateContentConfig", broken_config)
    request = GenerateRequest(prompt="hello", response_schema=brief.output_schema(), max_output_tokens=16384)
    with pytest.raises(RequestError):
        wrapped.generate(request)
    assert not sent and not meter.rows and meter.total == 0.0


def test_PL_02_an_unreturned_call_is_charged_its_quote_but_reports_no_output_tokens() -> None:
    meter = _meter()
    request = GenerateRequest(prompt="hello", max_output_tokens=16384)
    meter.add_unreturned("director", "flash-38", request, 100, 5.0)
    (row,) = meter.rows.values()
    assert row.calls == 1 and row.tokens_in == 100
    assert row.tokens_out == 0, "the 16384 is a quote, not usage"
    assert row.credits == pytest.approx(meter.cost("flash-38", 100, 16384)), "the credits still carry the full quote"
    assert meter.quoted_calls == 1
