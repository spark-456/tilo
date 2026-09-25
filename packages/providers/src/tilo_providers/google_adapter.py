"""tilo_providers.google_adapter — Google Gen AI SDK adapter (PL-02, PRD 6.4,
6.5). Wraps `google.genai.Client` against Agent Platform / Vertex, through
the global endpoint (PRD 6.5), behind `ModelProvider`: `generate`, `stream`,
`embed`, `count_tokens`, `capabilities`, `price`. Tool calling passes
straight through the SDK's own request/response shapes; structured output
(`GenerateRequest.json_mode`/`.response_schema`) maps onto
`GenerateContentConfig(response_mime_type="application/json",
response_schema=...)`. SDK errors map onto `tilo_providers.errors`
(quota/retryable/request/safety).

Imports `google.genai`/`.types`/`.errors` through `importlib.import_module`
rather than `from google import genai`, so the module works whether that
import path resolves to the real installed SDK (a client is constructed) or
to a fake installed straight into `sys.modules` for tests
(`packages/providers/tests/_fake_genai_sdk.py`) — `from google import
genai` would additionally require the fake to register itself as an
attribute of the real `google` namespace package, which it deliberately does
not do. No adapter test ever builds a real `genai.Client`; `client` is
always injected (EFF-01: "tested with mocked transport or recorded
responses only"). Without an injected `client`, construction refuses to
build a real one unless `LIVE=1` — the same EFF-01 gate as
`openai_compat_adapter`, so a direct construction of either adapter (not
only a call through `RecordReplayProvider`) can never open a real
client/transport in dev or CI."""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from typing import Any

from tilo_contracts import ProvidersProfile

from tilo_providers.errors import ProviderError, SafetyError, map_http_status
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote


def _genai_module(name: str) -> Any:
    return importlib.import_module(name)


class GoogleModelProvider(ModelProvider):
    def __init__(
        self,
        profile: ProvidersProfile,
        profile_id: str,
        project: str,
        location: str,
        client: Any | None = None,
        price: PriceQuote | None = None,
    ) -> None:
        self._profile = profile
        self._profile_id = profile_id
        self._project = project
        self._location = location
        self._price = price
        if client is None:
            # EFF-01: the LIVE gate cannot live only in RecordReplayProvider
            # -- this constructor is directly reachable (the factory's
            # live_factory, or a caller's own code), so it refuses to build
            # a real client itself.
            if os.environ.get("LIVE") != "1":
                raise ProviderError(
                    "PL-02/EFF-01: refusing to build a real network client without LIVE=1 (inject client= for tests)"
                )
            genai = _genai_module("google.genai")
            client = genai.Client(vertexai=True, project=project, location=location)
        self._client = client

    def _config(self, request: GenerateRequest) -> Any | None:
        kwargs: dict[str, Any] = {}
        if request.system is not None:
            kwargs["system_instruction"] = request.system
        if request.tools is not None:
            kwargs["tools"] = request.tools
        if request.max_output_tokens is not None:
            kwargs["max_output_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            # PL-02 structured output: a schema implies JSON output.
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_schema"] = request.response_schema
        elif request.json_mode:
            kwargs["response_mime_type"] = "application/json"
        if not kwargs:
            return None
        types_mod = _genai_module("google.genai.types")
        return types_mod.GenerateContentConfig(**kwargs)

    def _map_error(self, error: Exception) -> Exception:
        errors_mod = _genai_module("google.genai.errors")
        if isinstance(error, errors_mod.APIError):
            message = str(getattr(error, "message", error))
            return map_http_status(error.code, message)
        return error

    def _map_response(self, response: Any) -> GenerateResponse:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None) if prompt_feedback is not None else None
        if block_reason:
            # Honesty rule: never invent output the model did not produce —
            # a blocked response surfaces as SafetyError, not as text.
            raise SafetyError(f"blocked by safety filter: {block_reason}")

        tool_calls: list[dict[str, Any]] | None = None
        function_calls = getattr(response, "function_calls", None)
        if function_calls:
            tool_calls = [{"name": call.name, "args": call.args} for call in function_calls]

        usage: dict[str, int] | None = None
        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata is not None:
            usage = {
                "input_tokens": usage_metadata.prompt_token_count,
                "output_tokens": usage_metadata.candidates_token_count,
                "total_tokens": usage_metadata.total_token_count,
            }

        return GenerateResponse(text=response.text, profile_id=self._profile_id, tool_calls=tool_calls, usage=usage)

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        try:
            response = self._client.models.generate_content(
                model=self._profile.model, contents=request.prompt, config=self._config(request)
            )
        except Exception as error:
            raise self._map_error(error) from error
        return self._map_response(response)

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        try:
            chunks = self._client.models.generate_content_stream(
                model=self._profile.model, contents=request.prompt, config=self._config(request)
            )
            for chunk in chunks:
                yield self._map_response(chunk)
        except Exception as error:
            raise self._map_error(error) from error

    def embed(self, request: Any) -> Any:
        contents = request["input"] if isinstance(request, dict) else request
        try:
            response = self._client.models.embed_content(model=self._profile.model, contents=contents)
        except Exception as error:
            raise self._map_error(error) from error
        return {"vectors": [list(item) for item in response.embeddings], "profile_id": self._profile_id}

    def count_tokens(self, text: str) -> int:
        try:
            response = self._client.models.count_tokens(model=self._profile.model, contents=text)
        except Exception as error:
            raise self._map_error(error) from error
        return response.total_tokens

    def capabilities(self) -> set[Capability]:
        return {Capability(cap) for cap in self._profile.caps}

    def price(self) -> PriceQuote:
        if self._price is None:
            raise NotImplementedError(
                "PL-06: adapters do not own pricing — look up the profile's price through "
                "ProvidersConfig.price(profile_id), or construct this adapter with price=..."
            )
        return self._price
