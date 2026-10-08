"""LW-06 (ADR-0029 decision 6): the Google adapter sends a media part as `inline_data` (media first, the prompt last)
and reports the audio share of the input tokens; the openai_compat adapter takes images only, and any other type is a
missing capability (the router falls back); neither adapter sends a URI part, and no error names the content."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from _fake_genai_sdk import (
    FakeClient,
    FakeGenerateContentResponse,
    FakeModelsAPI,
    FakeUsageMetadata,
)
from google.genai import types as real_genai_types  # the real SDK, imported before the fake replaces it
from tilo_contracts import ProvidersProfile
from tilo_providers.errors import MissingCapabilityError, ProviderError, RequestError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.media import MediaPart

MARK = b"SECRETMARK-do-not-leak"
PNG = b"\x89PNG\r\n\x1a\n" + MARK
PDF = b"%PDF-1.7\n" + MARK
WAV = b"RIFF\x00\x00\x00\x00WAVE" + MARK
KEY_ENV, KEY = "FAKE_OPENAI_COMPAT_API_KEY", "fake-test-key-do-not-use-1234567890"


def google(models_api: FakeModelsAPI):
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "example-model", "context": 1000, "caps": ["json", "vision", "documents"]}
    )
    return GoogleModelProvider(profile, "flash", "demo-tilo", "global", client=FakeClient(models_api))


def compat(handler):
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {
            "provider": "openai_compat",
            "model": "org/some-model",
            "context": 1000,
            "caps": ["json", "vision"],
            "base_url": "https://mock.openai-compat.example/v1",
            "api_key_env": KEY_ENV,
        }
    )
    return OpenAICompatModelProvider(
        profile, "compat", "https://mock.openai-compat.example/v1", KEY_ENV, transport=httpx.MockTransport(handler)
    )


def request(*parts: MediaPart, prompt: str = "read these") -> GenerateRequest:
    return GenerateRequest(prompt=prompt, parts=list(parts) or None)


def test_LW_06_google_sends_each_part_as_inline_data_before_the_prompt(fake_genai_sdk):
    api = FakeModelsAPI(generate_content_result=FakeGenerateContentResponse(text="ok"))
    png = MediaPart(mime_type="image/png", data=PNG)
    pdf = MediaPart(mime_type="application/pdf", data=PDF)
    google(api).generate(request(png, pdf))
    contents = api.calls[0]["contents"]
    assert contents == [
        {
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "image/png", "data": PNG}},
                {"inline_data": {"mime_type": "application/pdf", "data": PDF}},
                {"text": "read these"},
            ],
        }
    ]
    assert real_genai_types.Content.model_validate(contents[0]).parts[0].inline_data.data == PNG, "the SDK takes it"


def test_LW_06_google_text_only_requests_are_unchanged_and_the_stream_sends_parts_too(fake_genai_sdk):
    api = FakeModelsAPI(
        generate_content_result=FakeGenerateContentResponse(text="ok"),
        generate_content_stream_result=[FakeGenerateContentResponse(text="o")],
    )
    provider = google(api)
    provider.generate(request(prompt="plain"))
    assert api.calls[0]["contents"] == "plain"
    list(provider.stream(request(MediaPart(mime_type="image/png", data=PNG))))
    assert api.calls[1]["contents"][0]["parts"][0]["inline_data"]["data"] == PNG


def test_LW_06_google_refuses_a_uri_part_before_calling_the_sdk(fake_genai_sdk):
    api = FakeModelsAPI(generate_content_result=FakeGenerateContentResponse(text="ok"))
    uri = MediaPart(mime_type="application/pdf", uri="gs://tilo-bucket/a.pdf", sha256="a" * 64)
    with pytest.raises(RequestError, match="ADR-0018 T8"):
        google(api).generate(request(uri))
    assert api.calls == []


def test_LW_06_google_reports_the_audio_share_of_the_input_tokens_only_when_it_is_usable(fake_genai_sdk):
    def usage_with(details):
        usage = FakeUsageMetadata(prompt_token_count=100, candidates_token_count=5, total_token_count=105)
        if details is not ...:
            usage.prompt_tokens_details = details  # type: ignore[attr-defined]
        return FakeGenerateContentResponse(text="ok", usage_metadata=usage)

    def modality(name, count):
        return SimpleNamespace(modality=SimpleNamespace(value=name), token_count=count)

    def reported(details):
        api = FakeModelsAPI(generate_content_result=usage_with(details))
        return google(api).generate(request(prompt="p")).usage

    assert (reported([modality("AUDIO", 60), modality("TEXT", 40)]) or {}).get("audio_tokens") == 60
    assert (reported([modality("TEXT", 100)]) or {}).get("audio_tokens") == 0
    for unusable in (..., None, [modality("AUDIO", 101)], [modality("AUDIO", -1)], [modality("AUDIO", True)]):
        assert "audio_tokens" not in (reported(unusable) or {}), "unknown is absent, never 0"


def test_LW_06_openai_compat_sends_an_image_as_an_image_url_data_part():
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        message = {"role": "assistant", "content": "ok"}
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "stop"}]})

    import os  # noqa: PLC0415

    os.environ[KEY_ENV] = KEY
    try:
        provider = compat(handler)
        provider.generate(request(MediaPart(mime_type="image/png", data=PNG)))
        provider.generate(request(prompt="plain"))
    finally:
        os.environ.pop(KEY_ENV, None)
    content = seen[0]["messages"][-1]["content"]
    assert content[0]["type"] == "image_url" and content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[-1] == {"type": "text", "text": "read these"}
    assert seen[1]["messages"][-1] == {"role": "user", "content": "plain"}, "text-only requests are unchanged"


@pytest.mark.parametrize(
    "part",
    [
        MediaPart(mime_type="application/pdf", data=PDF),
        MediaPart(mime_type="audio/wav", data=WAV, seconds=2.0),
        MediaPart(mime_type="video/mp4", data=b"\x00\x00\x00\x18ftypmp42" + MARK, seconds=2.0),
    ],
)
def test_LW_06_openai_compat_takes_images_only_anything_else_is_a_missing_capability(monkeypatch, part):
    monkeypatch.setenv(KEY_ENV, KEY)
    called: list[int] = []
    provider = compat(lambda req: called.append(1) or httpx.Response(500))
    with pytest.raises(MissingCapabilityError, match=part.mime_type) as caught:
        provider.generate(request(MediaPart(mime_type="image/png", data=PNG), part))
    assert not called, "nothing is sent"
    assert isinstance(caught.value, ProviderError) and not isinstance(caught.value, RequestError)
    assert "SECRETMARK" not in str(caught.value)


def test_LW_06_openai_compat_refuses_a_uri_part(monkeypatch):
    monkeypatch.setenv(KEY_ENV, KEY)
    provider = compat(lambda req: httpx.Response(500))
    uri = MediaPart(mime_type="image/png", uri="gs://tilo-bucket/a.png", sha256="b" * 64)
    with pytest.raises(RequestError, match="ADR-0018 T8"):
        provider.generate(request(uri))
