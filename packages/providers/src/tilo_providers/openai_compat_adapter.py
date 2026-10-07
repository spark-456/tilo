"""tilo_providers.openai_compat_adapter — generic OpenAI-compatible adapter
(PL-02, PRD 6.4): any endpoint speaking the OpenAI chat completions/
embeddings shape, including NVIDIA NIM (ADR-0003). `base_url`/`api_key_env`
come off the profile (`$defs.profile` 1.1.0, ADR-0002/0003). `transport` is
injected by tests; without one, construction requires `LIVE=1` (EFF-01).
The API key is scrubbed from any text via `redact()` (PRD 16.1 rule 4), and
never folded raw into a raised error."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from typing import Any

import httpx
from tilo_contracts import ProvidersProfile

from tilo_providers.errors import (
    OutputTruncatedError,
    ProviderError,
    SafetyError,
    map_http_status,
    map_transport_error,
    truncated_message,
)
from tilo_providers.interfaces import (
    Capability,
    GenerateRequest,
    GenerateResponse,
    ModelProvider,
    PriceQuote,
    cached_tokens_or_none,
)

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
        live_permitted: bool = False,
    ) -> None:
        self._profile = profile
        self._profile_id = profile_id
        self._price = price

        # The key rides in a header: TLS only, except loopback test servers.
        url = httpx.URL(base_url)
        if not (url.scheme == "https" or (url.scheme == "http" and url.host in _LOOPBACK_HOSTS)):
            raise ProviderError("PL-02: base_url must use https (plain http only for localhost/127.0.0.1)")

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ProviderError(f"PL-02: environment variable {api_key_env!r} (api_key_env) is not set")
        if not _CLEAN_TOKEN_RE.fullmatch(api_key):
            # Never include the value: it may be exactly the malformed
            # whitespace/control content this check exists to catch.
            raise ProviderError(
                f"PL-02: environment variable {api_key_env!r} (api_key_env) is not a clean ASCII token "
                "(no whitespace or control characters)"
            )

        # EFF-01: reachable directly (not only via RecordReplayProvider). `live_permitted` is the SEC-15 injected
        # permission (the deployed-judge path); it is never read from the environment.
        if transport is None and os.environ.get("LIVE") != "1" and not live_permitted:
            raise ProviderError(
                "PL-02/EFF-01: refusing to build a real network client without LIVE=1 (inject transport= for tests)"
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
        # A raw httpx/h11 exception's str() can inline a malformed header
        # value verbatim, so it never folds into our message (PRD 16.1 r.4).
        try:
            return self._client.post(path, json=body)
        except httpx.HTTPError as error:
            mapped = map_transport_error(error)
            assert mapped is not None  # httpx.HTTPError always maps
            raise mapped from None

    def redact(self, text: str) -> str:
        # Scrub before any truncation, or a key straddling the cut survives.
        return text.replace(self._api_key, "***")

    def _scrub(self, message: str) -> str:
        return self.redact(message)[:_MAX_ERROR_MESSAGE_LEN]

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
        # Bound and scrub: never copy an unbounded/verbatim body (PRD 16.1 r.4).
        raise map_http_status(response.status_code, self._scrub(message))

    def _stream_error(self, error: Any) -> ProviderError:
        # A mid-stream `data: {"error": ...}` chunk carries no HTTP status of
        # its own; a NIM/vLLM-style server reports one in `error.code` when
        # it has one, so the same 429/5xx/other-4xx mapping as a rejected
        # HTTP response applies (falling back to a retryable 500).
        message = "PL-02: provider returned an error chunk"
        status_code = 500
        if isinstance(error, dict):
            candidate = error.get("message")
            if isinstance(candidate, str) and candidate:
                message = candidate
            code = error.get("code")
            if isinstance(code, int) and 400 <= code < 600:
                status_code = code
        elif isinstance(error, str) and error:
            message = error
        return map_http_status(status_code, self._scrub(message))

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        # A 2xx body that is not the shape we expect (bad JSON, or a
        # missing/short "choices"/"data") must reach the caller as a
        # ProviderError, not a raw JSONDecodeError/KeyError/IndexError.
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as error:
            raise ProviderError(self._scrub(f"PL-02: provider returned a malformed response body: {error}")) from None

    def _map_message(
        self, message: dict[str, Any], usage_raw: dict[str, Any] | None, finish_reason: str | None = None
    ) -> GenerateResponse:
        if finish_reason == "content_filter":
            # Honesty rule: a blocked completion surfaces as SafetyError,
            # not as ordinary (possibly empty) text.
            raise SafetyError(f"PL-02: blocked by content filter (finish_reason={finish_reason!r})")
        if finish_reason == "length":
            # The reply hit its max_tokens cap: cut off or empty, never a reply. No thinking count on this wire.
            output = None if usage_raw is None else (usage_raw.get("completion_tokens") or 0)
            raise OutputTruncatedError(truncated_message(output, None), output_tokens=output, thinking_tokens=None)
        tool_calls: list[dict[str, Any]] | None = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            try:
                tool_calls = [
                    {"name": call["function"]["name"], "args": json.loads(call["function"]["arguments"])}
                    for call in raw_tool_calls
                ]
            except json.JSONDecodeError as error:
                raise ProviderError(
                    self._scrub(f"PL-02: provider returned malformed tool-call arguments: {error}")
                ) from None
        usage: dict[str, int] | None = None
        if usage_raw is not None:
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens", 0),
                "output_tokens": usage_raw.get("completion_tokens", 0),
                "total_tokens": usage_raw.get("total_tokens", 0),
            }
            # EFF-04: NIM and others often leave prompt_tokens_details out; that is unknown, not 0.
            details = usage_raw.get("prompt_tokens_details")
            cached = cached_tokens_or_none(
                details.get("cached_tokens") if isinstance(details, dict) else None, usage["input_tokens"]
            )
            if cached is not None:
                usage["cached_tokens"] = cached
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

    def _body(self, request: GenerateRequest, *, stream: bool = False) -> dict[str, Any]:
        # EFF-04 stable prefix: the static parts (tool definitions, response schema) come before `messages`, which
        # holds the system prompt and then the per-call text; the per-call limits go last.
        body: dict[str, Any] = {"model": self._profile.model}
        if request.tools is not None:
            body["tools"] = request.tools
        response_format = self._response_format(request)
        if response_format is not None:
            body["response_format"] = response_format
        body["messages"] = self._messages(request)
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        if stream:
            body["stream"] = True
        return body

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        body = self._body(request)

        response = self._post("/chat/completions", body)
        self._raise_for_status(response)
        data = self._parse(response)
        try:
            choice = data["choices"][0]
            return self._map_message(choice["message"], data.get("usage"), choice.get("finish_reason"))
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(self._scrub(f"PL-02: provider response missing {error}")) from None

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        body = self._body(request, stream=True)

        # `client.stream()` keeps the connection open so each SSE line is
        # yielded as it arrives, instead of only after the body completes.
        buffers: dict[int, dict[str, Any]] = {}
        try:
            with self._client.stream("POST", "/chat/completions", json=body) as response:
                if response.status_code >= 400:
                    response.read()  # a streamed response must be read before .json()/.text is usable
                    self._raise_for_status(response)
                # Tool-call deltas arrive fragmented by `index`; collected
                # here and yielded once complete, mirroring generate()'s shape.
                for line in response.iter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except (json.JSONDecodeError, ValueError) as error:
                        raise ProviderError(
                            self._scrub(f"PL-02: provider returned a malformed stream chunk: {error}")
                        ) from None
                    if isinstance(chunk, dict) and "error" in chunk:
                        raise self._stream_error(chunk["error"])
                    try:
                        choice = chunk["choices"][0]
                    except (KeyError, IndexError, TypeError) as error:
                        raise ProviderError(self._scrub(f"PL-02: provider stream chunk missing {error}")) from None
                    finish_reason = choice.get("finish_reason")
                    if finish_reason == "content_filter":
                        raise SafetyError(f"PL-02: blocked by content filter (finish_reason={finish_reason!r})")
                    if finish_reason == "length":
                        usage_raw = chunk.get("usage")
                        output = None if not isinstance(usage_raw, dict) else (usage_raw.get("completion_tokens") or 0)
                        raise OutputTruncatedError(
                            truncated_message(output, None), output_tokens=output, thinking_tokens=None
                        )
                    delta = choice.get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield GenerateResponse(text=content, profile_id=self._profile_id)
                    for raw_call in delta.get("tool_calls") or []:
                        buffer = buffers.setdefault(raw_call.get("index", 0), {"name": None, "args": ""})
                        function = raw_call.get("function") or {}
                        buffer["name"] = function.get("name") or buffer["name"]
                        buffer["args"] += function.get("arguments") or ""
        except httpx.HTTPError as error:
            mapped = map_transport_error(error)
            assert mapped is not None  # httpx.HTTPError always maps
            raise mapped from None
        if buffers:
            try:
                tool_calls = [
                    {"name": buf["name"], "args": json.loads(buf["args"]) if buf["args"] else {}}
                    for _, buf in sorted(buffers.items())
                ]
            except json.JSONDecodeError as error:
                raise ProviderError(
                    self._scrub(f"PL-02: provider returned malformed tool-call arguments: {error}")
                ) from None
            yield GenerateResponse(text=None, profile_id=self._profile_id, tool_calls=tool_calls)

    def embed(self, request: Any) -> Any:
        texts = request["input"] if isinstance(request, dict) else request
        response = self._post("/embeddings", {"model": self._profile.model, "input": texts})
        self._raise_for_status(response)
        data = self._parse(response)
        try:
            vectors = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as error:
            raise ProviderError(self._scrub(f"PL-02: provider response missing {error}")) from None
        return {"vectors": vectors, "usage": data.get("usage", {})}

    def count_tokens(self, text: str) -> int:
        # No universal tokenize route across OpenAI-compatible endpoints;
        # a whitespace count is a deterministic estimate until P0-06.
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
