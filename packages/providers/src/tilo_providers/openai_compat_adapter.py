"""tilo_providers.openai_compat_adapter — generic OpenAI-compatible adapter
(PL-02, PRD 6.4). Works against any endpoint speaking the OpenAI chat
completions/embeddings shape, including NVIDIA NIM
(https://integrate.api.nvidia.com/v1, ADR-0003). `base_url`/`api_key_env`
are `contracts/providers.schema.json` `$defs.profile` fields (1.1.0,
ADR-0002/ADR-0003, `provider: openai_compat` only); the factory reads them
off the profile, but stay constructor args so a caller can build directly.

Built on `httpx` (BSD-3-Clause, `docs/licences.md`); `transport` is injected
by tests so no real socket opens in dev/CI. Without an injected `transport`,
construction refuses to build a real `httpx.Client` unless `LIVE=1`
(EFF-01: the gate must hold at every direct-construction path, not only
inside `RecordReplayProvider`). The API key is read once from the named env
var and sent only as `Authorization`; `redact()` scrubs it out of any text
handed to it (`tilo_providers.replay`, PRD 16.1 rule 4), so a recording
stays clean even if a misbehaving endpoint echoes the key back into output.

Secret hygiene (PRD 16.1 rule 4): the env value is checked at construction
for stray whitespace/control characters (e.g. a trailing CR pasted on
Windows) and rejected by naming only the variable, never the value — an
unchecked CR/LF makes h11 raise "Illegal header value" with the value
inlined in its own message, which would otherwise leak the key through
`_post`'s exception. `_post`/`_raise_for_status` also never fold a raw
`httpx` exception's `str()` or an unbounded/verbatim response body into a
raised error: fixed messages plus the status code, or the server's own
message truncated and scrubbed."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from typing import Any

import httpx
from tilo_contracts import ProvidersProfile

from tilo_providers.errors import ProviderError, SafetyError, map_http_status, map_transport_error
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

        # EFF-01: a test injects `transport`; anything else building a real
        # `httpx.Client` must say LIVE=1 first -- the gate cannot live only
        # in RecordReplayProvider, since this constructor is reachable
        # directly (the factory's live_factory, or a caller's own code).
        if transport is None and os.environ.get("LIVE") != "1":
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
        # A raw httpx/h11 exception's own str() can inline a malformed
        # header value verbatim (e.g. a CR-suffixed API key), so it is never
        # folded into our message, and `from None` keeps it out of the
        # formatted traceback's chained-cause section too (PRD 16.1 rule 4).
        try:
            return self._client.post(path, json=body)
        except httpx.HTTPError as error:
            mapped = map_transport_error(error)
            assert mapped is not None  # httpx.HTTPError always maps
            raise mapped from None

    def redact(self, text: str) -> str:
        # Replace every occurrence of the raw key, whole, before any caller
        # truncates -- a truncate-then-scrub order lets a key straddling the
        # cut survive as an unmatched prefix (PRD 16.1 rule 4).
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
        # Never copy an unbounded or verbatim body into the exception: bound
        # it and scrub the key in case a misbehaving/echoing proxy reflected
        # it back (PRD 16.1 rule 4).
        raise map_http_status(response.status_code, self._scrub(message))

    def _map_message(
        self, message: dict[str, Any], usage_raw: dict[str, Any] | None, finish_reason: str | None = None
    ) -> GenerateResponse:
        if finish_reason == "content_filter":
            # Honesty rule, same mapping as the google adapter's
            # prompt_feedback.block_reason check: a blocked completion
            # surfaces as SafetyError, never as ordinary (possibly empty)
            # text -- the router (P0-06) must see this, not a silent None.
            raise SafetyError(f"PL-02: blocked by content filter (finish_reason={finish_reason!r})")
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
        return self._map_message(choice["message"], data.get("usage"), choice.get("finish_reason"))

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        body: dict[str, Any] = {"model": self._profile.model, "messages": self._messages(request), "stream": True}
        if request.tools is not None:
            body["tools"] = request.tools
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        response_format = self._response_format(request)
        if response_format is not None:
            body["response_format"] = response_format

        # Review fix: a plain `client.post()` (as `_post` uses for generate())
        # reads the whole response body before returning, so nothing would
        # be yielded until the SSE stream had already finished -- `stream=True`
        # over `client.stream()` keeps the connection open and hands lines to
        # `iter_lines()` as they arrive, so a caller sees each chunk as soon
        # as the server sends it, not all at once at the end.
        buffers: dict[int, dict[str, Any]] = {}
        try:
            with self._client.stream("POST", "/chat/completions", json=body) as response:
                if response.status_code >= 400:
                    response.read()  # a streamed response must be read before .json()/.text is usable
                    self._raise_for_status(response)
                # Tool-call deltas arrive fragmented by `index` (name in the
                # first fragment, `arguments` accumulated in later ones);
                # collected here and yielded once complete, as one chunk,
                # mirroring `generate()`'s shape (PL-02 tool calling).
                for line in response.iter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    choice = json.loads(payload)["choices"][0]
                    finish_reason = choice.get("finish_reason")
                    if finish_reason == "content_filter":
                        # Same mapping as generate()/the google adapter: a
                        # blocked stream must raise, not silently end with
                        # partial/no text.
                        raise SafetyError(f"PL-02: blocked by content filter (finish_reason={finish_reason!r})")
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
            # Same mapping as `_post`: never fold a raw httpx/h11 exception's
            # str() into our message (PRD 16.1 rule 4).
            mapped = map_transport_error(error)
            assert mapped is not None  # httpx.HTTPError always maps
            raise mapped from None
        if buffers:
            tool_calls = [
                {"name": buf["name"], "args": json.loads(buf["args"]) if buf["args"] else {}}
                for _, buf in sorted(buffers.items())
            ]
            yield GenerateResponse(text=None, profile_id=self._profile_id, tool_calls=tool_calls)

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
