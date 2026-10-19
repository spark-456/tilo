"""PL-02 (PRD 6.4): a request the Gen AI SDK refuses to BUILD never reaches the network, so it is a rejected request,
not an "unknown" failure.

Incident (live batch B-007, run twice): the SDK raised a pydantic `ValidationError` while turning the Director's
`GenerateContentConfig` into a request body, before anything was sent. Nothing in the adapter mapped it, the Router
gave up with a bare cause and `vertex_smoke.classify` printed "unknown" ("director role: unknown").

Pinned here: the adapter maps a client-side `pydantic.ValidationError` (from `generate` and `stream`) onto
`RequestError`, so `classify` answers "rejected" and a metering wrapper already treats it as never billed. The
message names the error class only: the validation text echoes the input values (the schema, and so potentially a
prompt), so neither the message nor the `__cause__` chain (which the Router and the logs print) may carry it.
"""

from __future__ import annotations

import pydantic
import pytest
from _fake_genai_sdk import FakeClient, FakeGenerateContentResponse, FakeModelsAPI
from tilo_contracts import ProvidersProfile
from tilo_providers.errors import RequestError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.vertex_smoke import classify, scrubbed_server_text

MARKER = "SCHEMA-OR-PROMPT-TEXT-MARKER"


class _Model(pydantic.BaseModel):
    count: int


def _validation_error() -> pydantic.ValidationError:
    try:
        _Model.model_validate({"count": MARKER})
    except pydantic.ValidationError as error:
        return error
    raise AssertionError("the probe model accepted a bad value")


def _provider(models_api: FakeModelsAPI):
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "gemini-3.8-flash", "context": 1_000_000, "caps": ["json"]}
    )
    return GoogleModelProvider(
        profile=profile, profile_id="flash-38", project="demo-tilo", location="global", client=FakeClient(models_api)
    )


def _all_text(error: BaseException) -> str:
    texts: list[str] = []
    link: BaseException | None = error
    while link is not None:
        texts.append(f"{type(link).__name__}: {link}")
        link = link.__cause__ or link.__context__
    return "\n".join(texts)


def test_PL_02_a_client_side_validation_error_is_a_rejected_request_not_unknown(fake_genai_sdk) -> None:
    provider = _provider(FakeModelsAPI(generate_content_error=_validation_error()))
    with pytest.raises(RequestError) as caught:
        provider.generate(GenerateRequest(prompt=MARKER, response_schema={"type": "object"}))
    assert classify(caught.value) == "rejected"
    assert "ValidationError" in str(caught.value), "the class name is the only detail kept"


def test_PL_02_a_client_side_validation_error_leaks_no_schema_or_prompt_text(fake_genai_sdk) -> None:
    provider = _provider(FakeModelsAPI(generate_content_error=_validation_error()))
    with pytest.raises(RequestError) as caught:
        provider.generate(GenerateRequest(prompt=MARKER))
    assert MARKER not in _all_text(caught.value), "message, __cause__ and __context__ carry the class name only"
    assert MARKER not in scrubbed_server_text(caught.value)


def test_PL_02_a_client_side_validation_error_from_a_stream_is_a_rejected_request(fake_genai_sdk) -> None:
    api = FakeModelsAPI()

    def refuses(**_: object) -> object:
        raise _validation_error()

    api.generate_content_stream = refuses  # type: ignore[method-assign]
    provider = _provider(api)
    with pytest.raises(RequestError) as caught:
        list(provider.stream(GenerateRequest(prompt=MARKER)))
    assert classify(caught.value) == "rejected" and MARKER not in _all_text(caught.value)


def test_PL_02_an_unrelated_error_is_still_not_mapped_to_a_request_error(fake_genai_sdk) -> None:
    provider = _provider(FakeModelsAPI(generate_content_error=KeyError("surprise")))
    with pytest.raises(KeyError):
        provider.generate(GenerateRequest(prompt="hi"))
    ok = _provider(FakeModelsAPI(generate_content_result=FakeGenerateContentResponse(text="{}")))
    assert ok.generate(GenerateRequest(prompt="hi")).text == "{}"
