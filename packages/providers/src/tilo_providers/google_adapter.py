"""tilo_providers.google_adapter — Google Gen AI SDK adapter (PL-02, PRD 6.4,
6.5). Wraps `google.genai.Client` against Agent Platform / Vertex, through
the global endpoint, behind `ModelProvider`. Structured output maps onto
`GenerateContentConfig(response_mime_type=..., response_schema=...)`;
SDK/transport errors map onto `tilo_providers.errors`.

Imports `google.genai`/`.types`/`.errors` via `importlib.import_module`
rather than `from google import genai`, so the module works whether that
path resolves to the real SDK or to the fake installed into `sys.modules`
for tests (`tests/_fake_genai_sdk.py`). `client` is always injected in
tests; without one, construction requires `LIVE=1` (same EFF-01 gate as
`openai_compat_adapter`)."""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Iterator
from typing import Any

from tilo_contracts import ProvidersProfile

from tilo_providers.errors import ProviderError, SafetyError, map_http_status, map_transport_error
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote


def _genai_module(name: str) -> Any:
    return importlib.import_module(name)


# Finish reasons the SDK uses to mark a *generated* response as blocked
# (distinct from `prompt_feedback.block_reason`, which blocks the prompt
# before generation starts). Mirrors openai_compat_adapter's
# `finish_reason == "content_filter"` handling.
_SAFETY_FINISH_REASONS = frozenset({"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"})

# Google OAuth access tokens (ADC) and API keys: shapes the shared Authorization/Bearer scrub in `replay` misses.
_GOOGLE_SECRET_RE = re.compile(r"ya29\.[\w.\-]+|AIza[\w\-]{35,}")


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
            # EFF-01: reachable directly (not only via RecordReplayProvider).
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
        if not kwargs and request.thinking_level is None:
            return None
        types_mod = _genai_module("google.genai.types")
        if request.thinking_level is not None and Capability.THINKING.value in self._profile.caps:
            # A profile without the capability (e.g. a fallback) would answer a thinking config with a 400: omit it.
            kwargs["thinking_config"] = types_mod.ThinkingConfig(thinking_level=request.thinking_level.upper())
        return types_mod.GenerateContentConfig(**kwargs) if kwargs else None

    def _map_error(self, error: Exception) -> Exception:
        errors_mod = _genai_module("google.genai.errors")
        if isinstance(error, errors_mod.APIError):
            message = str(getattr(error, "message", error))
            return map_http_status(error.code, message)
        # The SDK's transport is httpx too, so this maps the same as
        # openai_compat_adapter's (mapping must not depend on the adapter).
        return map_transport_error(error) or error

    def _map_response(self, response: Any) -> GenerateResponse:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None) if prompt_feedback is not None else None
        if block_reason:
            # Honesty rule: a blocked response surfaces as SafetyError, not text.
            raise SafetyError(f"blocked by safety filter: {block_reason}")

        candidates = getattr(response, "candidates", None) or []
        finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
        if finish_reason in _SAFETY_FINISH_REASONS:
            # Honesty rule: Gemini usually blocks a *generated* response this
            # way (response.text is None with no prompt_feedback.block_reason
            # at all) -- without this check that would surface as an empty
            # success instead of a safety block.
            raise SafetyError(f"blocked by safety filter: finish_reason={finish_reason!r}")

        tool_calls: list[dict[str, Any]] | None = None
        function_calls = getattr(response, "function_calls", None)
        if function_calls:
            tool_calls = [{"name": call.name, "args": call.args} for call in function_calls]

        usage: dict[str, int] | None = None
        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata is not None:
            # Thinking tokens are billed as output, so metering counts them there (FR-MTR-01).
            thoughts = getattr(usage_metadata, "thoughts_token_count", None) or 0
            usage = {
                "input_tokens": usage_metadata.prompt_token_count,
                "output_tokens": usage_metadata.candidates_token_count + thoughts,
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
        # `.values` is the float vector; `list(item)` would iterate the
        # pydantic model's *fields* instead.
        return {"vectors": [item.values for item in response.embeddings], "profile_id": self._profile_id}

    def count_tokens(self, text: str) -> int:
        try:
            response = self._client.models.count_tokens(model=self._profile.model, contents=text)
        except Exception as error:
            raise self._map_error(error) from error
        return response.total_tokens

    def redact(self, text: str) -> str:
        return _GOOGLE_SECRET_RE.sub("[redacted]", text)

    def capabilities(self) -> set[Capability]:
        return {Capability(cap) for cap in self._profile.caps}

    def price(self) -> PriceQuote:
        if self._price is None:
            raise NotImplementedError(
                "PL-06: adapters do not own pricing — look up the profile's price through "
                "ProvidersConfig.price(profile_id), or construct this adapter with price=..."
            )
        return self._price
