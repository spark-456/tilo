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
import json
import os
import re
from collections.abc import Iterator, Mapping
from typing import Any

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

_NO_FIELD = object()


def _genai_module(name: str) -> Any:
    return importlib.import_module(name)


# Finish reasons the SDK uses to mark a *generated* response as blocked
# (distinct from `prompt_feedback.block_reason`, which blocks the prompt
# before generation starts). Mirrors openai_compat_adapter's
# `finish_reason == "content_filter"` handling.
_SAFETY_FINISH_REASONS = frozenset({"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"})

# Google OAuth access tokens (ADC) and API keys: shapes the shared Authorization/Bearer scrub in `replay` misses.
_GOOGLE_SECRET_RE = re.compile(r"ya29\.[\w.\-]+|AIza[\w\-]{35,}")

# The SDK builds the host from the location (`https://{location}-aiplatform.googleapis.com/`) and the path from the
# project, and follows GOOGLE_VERTEX_BASE_URL, so a crafted value would send the ADC token to another host. Only
# these shapes may reach `genai.Client`; fullmatch, so a trailing newline does not slip through.
_LOCATION_RE = re.compile(r"global|us|eu|[a-z]+-[a-z]+[0-9]+")
_PROJECT_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_BASE_URL_VAR = "GOOGLE_VERTEX_BASE_URL"
_CREDENTIALS_VAR = "GOOGLE_APPLICATION_CREDENTIALS"


class GoogleSettingsError(ProviderError):
    """A Google environment value was refused before any client was built. Names the variable, never its value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_google_settings(project: str, location: str, environ: Mapping[str, str] | None = None) -> None:
    """Refuses unsafe base-URL, location, project and credentials-file settings (PL-02); builds and sends nothing."""
    environ = os.environ if environ is None else environ
    if environ.get(_BASE_URL_VAR):
        raise GoogleSettingsError("base_url_set", f"{_BASE_URL_VAR} is set; remove it, calls go to Google only")
    if not _LOCATION_RE.fullmatch(location):
        raise GoogleSettingsError(
            "location_invalid", "GOOGLE_LOCATION is not global, us, eu or a region such as europe-west4"
        )
    if not _PROJECT_RE.fullmatch(project):
        raise GoogleSettingsError("project_invalid", "GOOGLE_CLOUD_PROJECT is not a valid project id")
    refuse_service_account_key(environ)


def refuse_service_account_key(environ: Mapping[str, str] | None = None) -> None:
    """Refuses a service-account key file as ADC (user ADC only); shared with the Model Armor adapter."""
    environ = os.environ if environ is None else environ
    explicit = environ.get(_CREDENTIALS_VAR)
    path = explicit or _well_known_adc_path(environ)  # ADC reads the variable's file, else gcloud's well-known one
    try:
        with open(path, encoding="utf-8") as handle:  # only the `type` field is read; ADC reports anything else
            content = json.load(handle)
    except (OSError, ValueError):
        content = None
    if isinstance(content, dict) and content.get("type") == "service_account":
        where = _CREDENTIALS_VAR if explicit else "the gcloud well-known ADC file"
        raise GoogleSettingsError("service_account_key", f"{where} names a service-account key; use user ADC only")


def _well_known_adc_path(environ: Mapping[str, str]) -> str:
    config_dir = environ.get("CLOUDSDK_CONFIG")
    if not config_dir:
        base = environ.get("APPDATA", "") if os.name == "nt" else os.path.join(os.path.expanduser("~"), ".config")
        config_dir = os.path.join(base, "gcloud")
    return os.path.join(config_dir, "application_default_credentials.json")


class _RedactedAPIError(Exception):
    """Stands in for the SDK's APIError as the `__cause__` of a mapped error: status code and redacted text only."""

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(message)
        self.code = code


class GoogleModelProvider(ModelProvider):
    def __init__(
        self,
        profile: ProvidersProfile,
        profile_id: str,
        project: str,
        location: str,
        client: Any | None = None,
        price: PriceQuote | None = None,
        live_permitted: bool = False,
    ) -> None:
        self._profile = profile
        self._profile_id = profile_id
        self._project = project
        self._location = location
        self._price = price
        if client is None:
            # EFF-01: reachable directly (not only via RecordReplayProvider). `live_permitted` is the SEC-15
            # injected permission (the deployed-judge path); it is never read from the environment.
            if os.environ.get("LIVE") != "1" and not live_permitted:
                raise ProviderError(
                    "PL-02/EFF-01: refusing to build a real network client without LIVE=1 (inject client= for tests)"
                )
            validate_google_settings(project, location)  # before any client exists
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
            message = self.redact(str(getattr(error, "message", error)))  # a server message can echo a token
            return map_http_status(error.code, message)
        # The SDK's transport is httpx too, so this maps the same as
        # openai_compat_adapter's (mapping must not depend on the adapter).
        return map_transport_error(error) or error

    def _failure(self, error: Exception) -> Exception:
        """The mapped error, ready to raise *after* the `except` block so the raw SDK error is not its `__context__`."""
        mapped = self._map_error(error)
        if mapped is not error:
            if isinstance(error, _genai_module("google.genai.errors").APIError):
                # The raw SDK error carries the unredacted server message: keep only its code and redacted text.
                mapped.__cause__ = _RedactedAPIError(getattr(error, "code", None), str(mapped))
            else:
                mapped.__cause__ = error
        return mapped

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

        usage_metadata = getattr(response, "usage_metadata", None)
        if str(getattr(finish_reason, "value", finish_reason)) == "MAX_TOKENS":
            # The reply hit its output cap (thinking tokens count against it): empty or cut off, never a reply.
            # Vertex leaves a visible-output count out when it is 0 (so 0 with usage present, None with no usage); a
            # missing thinking count stays None: the model did not report one.
            output = thoughts = None
            if usage_metadata is not None:
                output = getattr(usage_metadata, "candidates_token_count", None) or 0
                thoughts = getattr(usage_metadata, "thoughts_token_count", None)
            raise OutputTruncatedError(
                truncated_message(output, thoughts), output_tokens=output, thinking_tokens=thoughts
            )

        tool_calls: list[dict[str, Any]] | None = None
        function_calls = getattr(response, "function_calls", None)
        if function_calls:
            tool_calls = [{"name": call.name, "args": call.args} for call in function_calls]

        usage: dict[str, int] | None = None
        if usage_metadata is not None:
            # Thinking tokens are billed as output, so metering counts them there (FR-MTR-01).
            # Vertex leaves a count None when thinking used the whole output cap: that is zero, never a crash.
            thoughts = getattr(usage_metadata, "thoughts_token_count", None) or 0
            usage = {
                "input_tokens": usage_metadata.prompt_token_count or 0,
                "output_tokens": (usage_metadata.candidates_token_count or 0) + thoughts,
                "total_tokens": usage_metadata.total_token_count or 0,
            }
            # EFF-04: the API leaves a zero cached count out, so present usage with a None count is a reported 0.
            # An object with no such field at all (not the SDK's model) reports nothing: unknown.
            cached = getattr(usage_metadata, "cached_content_token_count", _NO_FIELD)
            cached = cached_tokens_or_none(0 if cached is None else cached, usage["input_tokens"])
            if cached is not None:
                usage["cached_tokens"] = cached

        return GenerateResponse(text=response.text, profile_id=self._profile_id, tool_calls=tool_calls, usage=usage)

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        try:
            response = self._client.models.generate_content(
                model=self._profile.model, contents=request.prompt, config=self._config(request)
            )
        except Exception as error:
            failure = self._failure(error)
        else:
            return self._map_response(response)
        raise failure

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        failure: Exception | None = None
        try:
            chunks = self._client.models.generate_content_stream(
                model=self._profile.model, contents=request.prompt, config=self._config(request)
            )
            for chunk in chunks:
                yield self._map_response(chunk)
        except Exception as error:
            failure = self._failure(error)
        if failure is not None:
            raise failure

    def embed(self, request: Any) -> Any:
        contents = request["input"] if isinstance(request, dict) else request
        try:
            response = self._client.models.embed_content(model=self._profile.model, contents=contents)
        except Exception as error:
            failure = self._failure(error)
        else:
            # `.values` is the float vector; `list(item)` would iterate the
            # pydantic model's *fields* instead.
            return {"vectors": [item.values for item in response.embeddings], "profile_id": self._profile_id}
        raise failure

    def count_tokens(self, text: str) -> int:
        try:
            response = self._client.models.count_tokens(model=self._profile.model, contents=text)
        except Exception as error:
            failure = self._failure(error)
        else:
            return response.total_tokens  # type: ignore[no-any-return]
        raise failure

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
