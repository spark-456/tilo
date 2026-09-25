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
rule 4).

Secret hygiene (PRD 16.1 rule 4): the env value is checked at construction
time for stray whitespace/control characters (e.g. a trailing CR from
pasting a key on Windows) and rejected by naming only the variable, never
the value — an unchecked CR/LF in a header value makes h11 raise "Illegal
header value" *with the value inlined in its own message*, which would
otherwise surface the key through `_post`'s exception. `_post` and
`_raise_for_status` also never fold a raw `httpx` exception's `str()` or an
unbounded/verbatim response body into a raised error, as a second layer:
fixed messages plus the status code, or the server's own JSON error message
truncated and with the key scrubbed out."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from typing import Any

import httpx
from tilo_contracts import ProvidersProfile

from tilo_providers.errors import ProviderError, map_http_status
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

_CLEAN_TOKEN_RE = re.compile(r"^[\x21-\x7e]+$")  # printable ASCII, no whitespace or control characters
_MAX_ERROR_MESSAGE_LEN = 500
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1"}


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

        # The key rides in a header, so it only ever goes over TLS; plain
        # http is allowed for loopback test servers only.
        url = httpx.URL(base_url)
        if not (url.scheme == "https" or (url.scheme == "http" and url.host in _LOOPBACK_HOSTS)):
            raise ProviderError("PL-02: base_url must use https (plain http only for localhost/127.0.0.1)")

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ProviderError(f"PL-02: environment variable {api_key_env!r} (api_key_env) is not set")
        if not _CLEAN_TOKEN_RE.fullmatch(api_key):
            # Never include the value: it may be exactly the malformed
            # content (whitespace/control characters) this check exists to
            # catch before it reaches an HTTP header.
            raise ProviderError(
                f"PL-02: environment variable {api_key_env!r} (api_key_env) is not a clean ASCII token "
                "(no whitespace or control characters)"
            )

        self._api_key = api_key
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
        # A raw httpx/h11 exception's own str() can inline a malformed
        # header value verbatim (e.g. a CR-suffixed API key), so it is never
        # folded into our message, and `from None` keeps it out of the
        # formatted traceback's chained-cause section too (PRD 16.1 rule 4).
        try:
            return self._client.post(path, json=body)
        except httpx.TimeoutException:
            raise map_http_status(504, "PL-02: request to the provider endpoint timed out") from None
        except httpx.HTTPError:
            raise map_http_status(503, "PL-02: request to the provider endpoint failed") from None

    def _scrub(self, message: str) -> str:
        # Replace the full key in the complete text *before* truncating, so a
        # key straddling the cut can never survive as an unmatched prefix.
        return message.replace(self._api_key, "***")[:_MAX_ERROR_MESSAGE_LEN]

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        message = f"PL-02: provider returned HTTP {response.status_code}"
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            data = None
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict):
                candidate = error.get("message")
            elif isinstance(error, str):
                candidate = error
            else:
                candidate = None
            if isinstance(candidate, str) and candidate:
                message = candidate
        # Never copy an unbounded or verbatim body into the exception: bound
        # it and scrub the key in case a misbehaving/echoing proxy reflected
        # it back (PRD 16.1 rule 4).
        raise map_http_status(response.status_code, self._scrub(message))

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

    def _response_format(self, request: GenerateRequest) -> dict[str, Any] | None:
        # PL-02 structured output / JSON mode.
        if request.response_schema is not None:
            return {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": request.response_schema, "strict": True},
            }
        if request.json_mode:
            return {"type": "json_object"}
        return None

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        body: dict[str, Any] = {"model": self._profile.model, "messages": self._messages(request)}
        if request.tools is not None:
            body["tools"] = request.tools
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        response_format = self._response_format(request)
        if response_format is not None:
            body["response_format"] = response_format

        response = self._post("/chat/completions", body)
        self._raise_for_status(response)
        data = response.json()
        choice = data["choices"][0]
        return self._map_message(choice["message"], data.get("usage"))

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        body: dict[str, Any] = {"model": self._profile.model, "messages": self._messages(request), "stream": True}
        if request.tools is not None:
            body["tools"] = request.tools
        response_format = self._response_format(request)
        if response_format is not None:
            body["response_format"] = response_format

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
