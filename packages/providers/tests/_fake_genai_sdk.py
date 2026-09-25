"""Fixture helper for PL-02 google-adapter tests: a fake `google.genai` SDK
surface installed into `sys.modules`, and a fake `Client` whose
`.models.*` methods return canned results or raise a fake `errors.APIError`.

Ticket P0-05 item 1 asks for the google adapter to be "tested with mocked
transport or recorded responses only" (no live call in tests or CI, EFF-01).
`google-genai` is not yet a dependency of this workspace (the adapter that
imports it does not exist yet either) and adding it is the builder's job
(ticket item 1, "record the licence"). Rather than depend on the real SDK's
exact response classes -- which cannot be verified against a package that
is not installed -- this fakes the SDK's public surface at the
`sys.modules` boundary the adapter is expected to import from
(`from google import genai`, `from google.genai import types, errors`):
a legitimate "mocked transport" per the ticket, and the standard technique
for testing code against an SDK that lives behind a stable import path.

`install()` only ever replaces `google.genai`, `google.genai.types` and
`google.genai.errors` -- never `sys.modules["google"]` itself, which this
machine's real (unrelated) `google` namespace package already occupies.
Call it through the `fake_genai_sdk` fixture (autouse=False) so
`monkeypatch` restores `sys.modules` after each test.

Ambiguity resolved (see report): the real SDK's response objects are not
importable here to verify field names against, so this fakes the minimal,
best-effort shape documented in the SDK's README (`response.text`,
`errors.APIError.code`/`.message`) plus the fields the google adapter needs
for PL-02's conformance set (`function_calls`, `usage_metadata`,
`total_tokens`, `prompt_feedback.block_reason`). If the real SDK's field
names differ, the builder reconciles this fake with the real one when
implementing the adapter -- the acceptance test itself (call `generate`,
assert the mapped `GenerateResponse`) does not change.
"""

from __future__ import annotations

import sys
import types as pytypes
from dataclasses import dataclass, field
from typing import Any

import pytest


class FakeAPIError(Exception):
    """Stands in for `google.genai.errors.APIError` (SDK README section 5:
    `.code` is the HTTP-ish status, `.message` the server message)."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass
class FakeFunctionCall:
    name: str
    args: dict[str, Any]


@dataclass
class FakeUsageMetadata:
    prompt_token_count: int
    candidates_token_count: int
    total_token_count: int


@dataclass
class FakePromptFeedback:
    block_reason: str | None = None


@dataclass
class FakeGenerateContentResponse:
    text: str | None = None
    function_calls: list[FakeFunctionCall] = field(default_factory=list)
    usage_metadata: FakeUsageMetadata | None = None
    prompt_feedback: FakePromptFeedback | None = None


@dataclass
class FakeCountTokensResponse:
    total_tokens: int


class FakeGenerateContentConfig:
    """Captures whatever kwargs the adapter passes, so a test can assert on
    them (e.g. `config.max_output_tokens`) without depending on the real
    `types.GenerateContentConfig`'s validation."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class FakeModelsAPI:
    """Fakes `client.models`. Configure one `*_result` or `*_error` per
    method; unconfigured methods raise `AssertionError` if called, so a test
    only exercising `generate` fails loudly if the adapter also calls
    `count_tokens` unexpectedly."""

    def __init__(
        self,
        *,
        generate_content_result: FakeGenerateContentResponse | None = None,
        generate_content_error: Exception | None = None,
        generate_content_stream_result: list[FakeGenerateContentResponse] | None = None,
        count_tokens_result: FakeCountTokensResponse | None = None,
    ) -> None:
        self._generate_content_result = generate_content_result
        self._generate_content_error = generate_content_error
        self._generate_content_stream_result = generate_content_stream_result
        self._count_tokens_result = count_tokens_result
        self.calls: list[dict[str, Any]] = []  # every call, for assertions

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> FakeGenerateContentResponse:
        self.calls.append({"method": "generate_content", "model": model, "contents": contents, "config": config})
        if self._generate_content_error is not None:
            raise self._generate_content_error
        assert self._generate_content_result is not None, "test did not configure generate_content_result"
        return self._generate_content_result

    def generate_content_stream(self, *, model: str, contents: Any, config: Any = None):
        self.calls.append({"method": "generate_content_stream", "model": model, "contents": contents, "config": config})
        assert self._generate_content_stream_result is not None, "test did not configure generate_content_stream_result"
        yield from self._generate_content_stream_result

    def count_tokens(self, *, model: str, contents: Any) -> FakeCountTokensResponse:
        self.calls.append({"method": "count_tokens", "model": model, "contents": contents})
        assert self._count_tokens_result is not None, "test did not configure count_tokens_result"
        return self._count_tokens_result


class FakeClient:
    """A fake `genai.Client`: has `.models`, nothing else. Adapter tests
    build one directly and inject it -- `genai.Client(...)` (real
    construction) is never called in tests."""

    def __init__(self, models: FakeModelsAPI) -> None:
        self.models = models


def install() -> None:
    genai_pkg = pytypes.ModuleType("google.genai")
    types_mod = pytypes.ModuleType("google.genai.types")
    errors_mod = pytypes.ModuleType("google.genai.errors")

    types_mod.GenerateContentConfig = FakeGenerateContentConfig  # type: ignore[attr-defined]
    errors_mod.APIError = FakeAPIError  # type: ignore[attr-defined]
    genai_pkg.types = types_mod  # type: ignore[attr-defined]
    genai_pkg.errors = errors_mod  # type: ignore[attr-defined]

    def _unexpected_construction(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("tests inject a FakeClient directly; the real genai.Client(...) must not be constructed")

    genai_pkg.Client = _unexpected_construction  # type: ignore[attr-defined]

    sys.modules["google.genai"] = genai_pkg
    sys.modules["google.genai.types"] = types_mod
    sys.modules["google.genai.errors"] = errors_mod


@pytest.fixture
def fake_genai_sdk(monkeypatch: pytest.MonkeyPatch) -> pytypes.ModuleType:
    """Installs the fake `google.genai` SDK for the duration of one test and
    returns the fake `google.genai` module (for `errors.APIError` etc.)."""
    for name in ("google.genai", "google.genai.types", "google.genai.errors"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    install()
    yield sys.modules["google.genai"]
    for name in ("google.genai", "google.genai.types", "google.genai.errors"):
        monkeypatch.delitem(sys.modules, name, raising=False)
