"""tilo_providers.openai_compat_adapter — generic OpenAI-compatible adapter
(PL-02, PRD 6.4). Works against any endpoint that speaks the OpenAI chat
completions / embeddings shape, including NVIDIA NIM
(https://integrate.api.nvidia.com/v1, ADR-0003). `base_url` and
`api_key_env` are constructor arguments today, not profile fields:
`contracts/providers.schema.json` `$defs.profile` has `additionalProperties:
false` and no such fields — see `config/models.nim.yaml`'s header comment
(needs contract change, not edited here per root CLAUDE.md).

Built on `httpx` (BSD-3-Clause, `docs/licences.md`); `transport` is injected
by tests (`httpx.MockTransport`) so no real socket ever opens in dev/CI
(EFF-01). The API key is read once from the named environment variable at
construction time and sent only as the `Authorization` header — never
logged, never written into a recording (`tilo_providers.replay`, PRD 16.1
rule 4)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx
from tilo_contracts import ProvidersProfile

from tilo_providers.errors import ProviderError, map_http_status
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote


class OpenAICompatModelProvider(ModelProvider):
    def __init__(
        self,
        profile: ProvidersProfile,
        profile_id: str,
        base_url: str,
        api_key_env: str,
        transport: httpx.BaseTransport | None = None,
        price: PriceQuote | None = None,
    ) -> None:
        self._profile = profile
        self._profile_id = profile_id
        self._price = price

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ProviderError(f"PL-02: environment variable {api_key_env!r} (api_key_env) is not set")

        self._client = httpx.Client(
            base_url=base_url, transport=transport, headers={"Authorization": f"Bearer {api_key}"}
        )

    def _messages(self, request: GenerateRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system is not None:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        return messages

    def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        try:
            return self._client.post(path, json=body)
        except httpx.TimeoutException as error:
            raise map_http_status(504, str(error)) from error  # 504-shaped: mapped to RetryableError below
        except httpx.HTTPError as error:
            raise map_http_status(503, str(error)) from error

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            message = response.json().get("error", {}).get("message", response.text)
        except (json.JSONDecodeError, ValueError):
            message = response.text
        raise map_http_status(response.status_code, message)

    def _map_message(self, message: dict[str, Any], usage_raw: dict[str, Any] | None) -> GenerateResponse:
        tool_calls: list[dict[str, Any]] | None = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = [
                {"name": call["function"]["name"], "args": json.loads(call["function"]["arguments"])}
                for call in raw_tool_calls
            ]
        usage: dict[str, int] | None = None
        if usage_raw is not None:
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens", 0),
                "output_tokens": usage_raw.get("completion_tokens", 0),
                "total_tokens": usage_raw.get("total_tokens", 0),
            }
        return GenerateResponse(
            text=message.get("content"), profile_id=self._profile_id, tool_calls=tool_calls, usage=usage
        )

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        body: dict[str, Any] = {"model": self._profile.model, "messages": self._messages(request)}
        if request.tools is not None:
            body["tools"] = request.tools
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens

        response = self._post("/chat/completions", body)
        self._raise_for_status(response)
        data = response.json()
        choice = data["choices"][0]
        return self._map_message(choice["message"], data.get("usage"))

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        body: dict[str, Any] = {"model": self._profile.model, "messages": self._messages(request), "stream": True}
        if request.tools is not None:
            body["tools"] = request.tools

        response = self._post("/chat/completions", body)
        self._raise_for_status(response)
        for line in response.text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                yield GenerateResponse(text=content, profile_id=self._profile_id)

    def embed(self, request: Any) -> Any:
        texts = request["input"] if isinstance(request, dict) else request
        response = self._post("/embeddings", {"model": self._profile.model, "input": texts})
        self._raise_for_status(response)
        data = response.json()
        vectors = [item["embedding"] for item in data["data"]]
        return {"vectors": vectors, "usage": data.get("usage", {})}

    def count_tokens(self, text: str) -> int:
        # OpenAI-compatible endpoints (including NIM) offer no universal
        # tokenize route; a whitespace count is a deterministic, offline
        # estimate until a profile-specific tokenizer is wired in (P0-06).
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return {Capability(cap) for cap in self._profile.caps}

    def price(self) -> PriceQuote:
        if self._price is None:
            raise NotImplementedError(
                "PL-06: adapters do not own pricing — look up the profile's price through "
                "ProvidersConfig.price(profile_id), or construct this adapter with price=..."
            )
        return self._price
