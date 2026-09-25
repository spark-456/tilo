"""EFF-01 (PRD 6.6): "Dev and CI make no paid model calls unless LIVE=1" --
"CI run with network egress to model endpoints blocked still passes." PRD
6.6 "Record and replay" row: "Dev and CI run on recorded model responses;
live calls need an explicit LIVE=1; UI work uses a fake provider." Ticket
P0-05 item 4 (record-and-replay) and item 5 (fake provider):

- "Default mode (LIVE unset) is replay: responses come from recordings
  under fixtures/model-recordings/<role>/<key>.json keyed by a stable hash
  of role, profile and the normalised request; a miss raises a clear error
  with the key."
- "Record mode needs LIVE=1 plus TILO_RECORD=1 and writes redacted
  recordings (no headers, keys or env values)."
- "The provider factory (role -> provider) picks replay unless LIVE=1;
  nothing builds a network client at import time."
- "Fake provider: deterministic canned responses for UI and fixture work."

Public interface under test: `ModelProvider.generate` (PRD 6.4), reached
through `tilo_providers.factory.build_provider` and
`tilo_providers.replay.RecordReplayProvider` directly. No real network
provider (google-genai is not installed in this environment at all -- see
report) is ever imported on the LIVE-unset path; several tests assert this
directly by checking `sys.modules`, which doubles as end-to-end proof that
importing the factory and building providers for every role does not
require google-genai or the openai-compatible adapter's runtime deps.
"""

from __future__ import annotations

import json
import sys

import pytest
from conftest import models_config, prices_config, write_providers_config
from tilo_providers.config import load_providers_config
from tilo_providers.interfaces import GenerateRequest, GenerateResponse, ModelProvider

ADAPTER_MODULES = ("tilo_providers.google_adapter", "tilo_providers.openai_compat_adapter")


def _config_with_a_live_provider(tmp_path):
    """conftest.BASE_MODELS profiles are all `provider: fake`; give
    "large" a real (never-installed-here) provider so build_provider's
    replay branch is actually exercised, not its fake-provider branch."""
    models = models_config()
    models["profiles"]["large"]["provider"] = "google"
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())
    return load_providers_config(models_path, prices_path)


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)


@pytest.fixture(autouse=True)
def _adapter_modules_start_unimported(monkeypatch):
    for name in ADAPTER_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)


def test_EFF_01_factory_returns_replay_or_fake_for_every_role_without_live(tmp_path):
    from tilo_providers.factory import build_provider  # noqa: PLC0415

    config = _config_with_a_live_provider(tmp_path)

    for role_id in config.roles:
        provider = build_provider(role_id, config, fixtures_dir=tmp_path / "fixtures")
        assert isinstance(provider, ModelProvider), f"role {role_id!r} must still get a ModelProvider"
        assert provider.__class__.__module__ in {"tilo_providers.replay", "tilo_providers.fake"}, (
            f"role {role_id!r}: LIVE unset must return replay or fake, got {provider.__class__.__module__}"
        )


def test_EFF_01_factory_never_imports_the_real_adapter_without_live(tmp_path):
    """ "nothing builds a network client at import time" -- checked at its
    strongest: the adapter module (google-genai/httpx client construction
    included) is never even imported, let alone a client built."""
    from tilo_providers.factory import build_provider  # noqa: PLC0415

    config = _config_with_a_live_provider(tmp_path)

    for role_id in config.roles:
        build_provider(role_id, config, fixtures_dir=tmp_path / "fixtures")

    for name in ADAPTER_MODULES:
        assert name not in sys.modules, f"EFF-01: build_provider without LIVE must not import {name}"


def test_EFF_01_fake_provider_role_returns_the_fake_provider(tmp_path):
    from tilo_providers.factory import build_provider  # noqa: PLC0415
    from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415

    config = _config_with_a_live_provider(tmp_path)  # only "large" changed; others stay `provider: fake`

    provider = build_provider("specialist", config, fixtures_dir=tmp_path / "fixtures")

    assert isinstance(provider, FakeModelProvider)


def test_EFF_01_replay_miss_raises_a_clear_error_naming_the_key(tmp_path):
    from tilo_providers.replay import RecordReplayProvider, ReplayMissError, recording_key  # noqa: PLC0415

    request = GenerateRequest(prompt="never recorded")
    key = recording_key("director", "large", request)
    provider = RecordReplayProvider(
        role="director", profile_id="large", live_factory=_unexpected_live_factory, fixtures_dir=tmp_path
    )

    with pytest.raises(ReplayMissError) as excinfo:
        provider.generate(request)

    message = str(excinfo.value)
    assert key in message, f"EFF-01: a replay miss must name the recording key, got: {message!r}"
    assert "director" in message
    assert "large" in message


def test_EFF_01_recording_is_refused_without_both_live_and_record_flags(tmp_path, monkeypatch):
    from tilo_providers.replay import RecordReplayProvider, ReplayMissError  # noqa: PLC0415

    request = GenerateRequest(prompt="hello")
    calls = []
    provider = RecordReplayProvider(
        role="director",
        profile_id="large",
        live_factory=lambda: _CountingLiveProvider(calls),
        fixtures_dir=tmp_path,
    )

    # Neither flag: replay (miss).
    with pytest.raises(ReplayMissError):
        provider.generate(request)
    assert calls == [], "EFF-01: no live call without LIVE=1 and TILO_RECORD=1"

    # TILO_RECORD=1 without LIVE=1 is not enough to go live or record.
    monkeypatch.setenv("TILO_RECORD", "1")
    with pytest.raises(ReplayMissError):
        provider.generate(request)
    assert calls == [], "EFF-01: no live call without LIVE=1, even with TILO_RECORD=1"
    assert list(tmp_path.rglob("*.json")) == []


def test_EFF_01_live_without_record_calls_the_live_provider_and_writes_nothing(tmp_path, monkeypatch):
    """PRD 6.6: "live calls need an explicit LIVE=1". LIVE=1 alone sends the
    call to the real adapter (built lazily) without writing a recording."""
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    request = GenerateRequest(prompt="hello")
    calls = []
    built = []

    def live_factory():
        built.append(1)
        return _CountingLiveProvider(calls)

    provider = RecordReplayProvider(
        role="director", profile_id="large", live_factory=live_factory, fixtures_dir=tmp_path
    )
    assert built == [], "the live provider must be built lazily, not at construction"

    monkeypatch.setenv("LIVE", "1")
    response = provider.generate(request)

    assert response.text == "live: hello"
    assert len(calls) == 1, "LIVE=1 must make exactly one live call"
    assert list(tmp_path.rglob("*.json")) == [], "LIVE=1 without TILO_RECORD=1 must not write a recording"


def test_EFF_01_record_then_replay_round_trip(tmp_path, monkeypatch):
    """LIVE=1 + TILO_RECORD=1 calls the live provider once and writes a
    recording; a later call with both flags unset replays it without
    touching the live provider again."""
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    request = GenerateRequest(prompt="hello")
    calls = []
    live_factory = lambda: _CountingLiveProvider(calls)  # noqa: E731

    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")
    recorder = RecordReplayProvider(
        role="director", profile_id="large", live_factory=live_factory, fixtures_dir=tmp_path
    )
    recorded = recorder.generate(request)
    assert len(calls) == 1, "record mode must call the live provider exactly once"

    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)
    replayer = RecordReplayProvider(
        role="director", profile_id="large", live_factory=_unexpected_live_factory, fixtures_dir=tmp_path
    )
    replayed = replayer.generate(request)

    assert replayed.text == recorded.text
    assert len(calls) == 1, "replay must not call the live provider again"


def test_EFF_01_written_recording_never_contains_the_api_key_env_value(tmp_path, monkeypatch):
    """ "writes redacted recordings (no headers, keys or env values)". A
    fake secret is assembled at runtime (never a real credential) and must
    not appear anywhere in the written file, even though the "live"
    provider used it to authenticate."""
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    fake_secret = "fake-nim-key-" + "".join(str(n) for n in range(20))  # assembled at runtime, not a real key
    monkeypatch.setenv("NVIDIA_API_KEY", fake_secret)
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")

    def live_factory():
        return _AuthenticatingLiveProvider(api_key_env="NVIDIA_API_KEY")

    provider = RecordReplayProvider(
        role="director", profile_id="large", live_factory=live_factory, fixtures_dir=tmp_path
    )
    provider.generate(GenerateRequest(prompt="hello"))

    recording_files = list(tmp_path.rglob("*.json"))
    assert recording_files, "record mode must write a recording file"
    for recording_file in recording_files:
        content = recording_file.read_text(encoding="utf-8")
        assert fake_secret not in content, f"16.1 rule 4: {recording_file} must not contain the API key env value"
        assert "authorization" not in content.lower(), f"{recording_file} must not contain a header block"


def test_EFF_01_written_recording_scrubs_a_key_echoed_in_the_model_output(tmp_path, monkeypatch):
    """Security review fix (P0-05, ticket item 5): the previous test proves
    a secret that never reaches `GenerateResponse` cannot leak. This proves
    the harder case -- a live provider whose *output itself* happens to
    contain its own secret (e.g. a misbehaving endpoint echoing the
    Authorization header back into model text) still must not end up in the
    written recording. `RecordReplayProvider` calls the live provider's own
    `ModelProvider.redact()` on everything before writing, not just its
    structured fields."""
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    fake_secret = "fake-nim-key-" + "".join(str(n) for n in range(20))  # assembled at runtime, not a real key
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")

    class _EchoingLiveProvider(_CountingLiveProvider):
        def generate(self, request: GenerateRequest) -> GenerateResponse:
            self._calls.append(request)
            return GenerateResponse(text=f"echo: Bearer {fake_secret}", profile_id="large")

        def redact(self, text: str) -> str:
            return text.replace(fake_secret, "***")

    calls: list[GenerateRequest] = []
    provider = RecordReplayProvider(
        role="director", profile_id="large", live_factory=lambda: _EchoingLiveProvider(calls), fixtures_dir=tmp_path
    )
    response = provider.generate(GenerateRequest(prompt="hello"))
    assert fake_secret in response.text, "test setup: the live provider must actually echo the secret"

    recording_files = list(tmp_path.rglob("*.json"))
    assert recording_files, "record mode must write a recording file"
    for recording_file in recording_files:
        content = recording_file.read_text(encoding="utf-8")
        assert fake_secret not in content, (
            f"16.1 rule 4: {recording_file} must not contain a secret echoed in the model's own output"
        )
        # Review fix: redaction must not corrupt the recording -- it has to
        # stay valid JSON, and replaying it must hand back the redacted text.
        json.loads(content)
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)
    replayer = RecordReplayProvider(
        role="director", profile_id="large", live_factory=_unexpected_live_factory, fixtures_dir=tmp_path
    )
    replayed_text = replayer.generate(GenerateRequest(prompt="hello")).text
    assert fake_secret not in replayed_text
    assert "echo:" in replayed_text


def test_EFF_01_written_recording_scrubs_an_authorization_like_string_regardless_of_provider(tmp_path, monkeypatch):
    """Backstop layer: even a live provider that does not override
    `redact()` at all must not have a raw `Authorization:`/`Bearer` string
    written into a recording."""
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    calls: list[GenerateRequest] = []
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")

    class _NonRedactingLiveProvider(_CountingLiveProvider):
        def generate(self, request: GenerateRequest) -> GenerateResponse:
            self._calls.append(request)
            return GenerateResponse(text="Authorization: Bearer literal-secret-value", profile_id="large")

    provider = RecordReplayProvider(
        role="director",
        profile_id="large",
        live_factory=lambda: _NonRedactingLiveProvider(calls),
        fixtures_dir=tmp_path,
    )
    provider.generate(GenerateRequest(prompt="hello"))

    recording_files = list(tmp_path.rglob("*.json"))
    assert recording_files
    for recording_file in recording_files:
        content = recording_file.read_text(encoding="utf-8")
        assert "literal-secret-value" not in content
        assert "authorization" not in content.lower()
        # Review fix: the backstop regex used to also swallow the JSON
        # string's closing quote (and whatever followed it), so this text --
        # ending right where "Bearer <token>" does -- used to corrupt the
        # file. It must still parse, and still replay.
        json.loads(content)
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)
    replayer = RecordReplayProvider(
        role="director", profile_id="large", live_factory=_unexpected_live_factory, fixtures_dir=tmp_path
    )
    replayed = replayer.generate(GenerateRequest(prompt="hello"))
    assert "literal-secret-value" not in replayed.text
    assert "[redacted]" in replayed.text


def test_EFF_01_written_recording_scrubs_a_secret_containing_quote_and_backslash_characters(tmp_path, monkeypatch):
    """Review fix: `json.dumps` escapes a value's own `"`/`\\`, so scrubbing
    the *serialised* text (as before) misses a secret that itself contains
    either character -- PL-02's `_CLEAN_TOKEN_RE` allows both in an
    `api_key_env` value. Redacting before serialising, on the raw value,
    must still catch it."""
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    tricky_secret = 'fake-key-"with-a-quote\\and-a-backslash'  # PL-02 _CLEAN_TOKEN_RE permits both chars
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")

    class _EchoingLiveProvider(_CountingLiveProvider):
        def generate(self, request: GenerateRequest) -> GenerateResponse:
            self._calls.append(request)
            return GenerateResponse(text=f"echo: {tricky_secret}", profile_id="large")

        def redact(self, text: str) -> str:
            return text.replace(tricky_secret, "***")

    calls: list[GenerateRequest] = []
    provider = RecordReplayProvider(
        role="director", profile_id="large", live_factory=lambda: _EchoingLiveProvider(calls), fixtures_dir=tmp_path
    )
    response = provider.generate(GenerateRequest(prompt="hello"))
    assert tricky_secret in response.text, "test setup: the live provider must actually echo the secret"

    recording_files = list(tmp_path.rglob("*.json"))
    assert recording_files, "record mode must write a recording file"
    for recording_file in recording_files:
        content = recording_file.read_text(encoding="utf-8")
        json.loads(content)
    # Review fix: `json.dumps` already escapes the raw secret's own '"'/'\\'
    # characters, so a bare `tricky_secret not in content` check on the
    # serialised text passes whether or not redaction ran at all -- the
    # escaped form of the un-redacted secret never matches the raw string
    # either. Replaying is the only check that actually exercises whether
    # the *value* written was redacted before serialising.
    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)
    replayer = RecordReplayProvider(
        role="director", profile_id="large", live_factory=_unexpected_live_factory, fixtures_dir=tmp_path
    )
    replayed_text = replayer.generate(GenerateRequest(prompt="hello")).text
    assert tricky_secret not in replayed_text, (
        "16.1 rule 4: a secret with '\"'/'\\\\' must not survive into the replayed response"
    )
    assert "echo:" in replayed_text


def test_EFF_01_record_then_replay_round_trips_a_tool_call_only_and_a_usage_only_turn(tmp_path, monkeypatch):
    """Review fix (security): `GenerateResponse.text` had no default, so
    `_write_recording`'s `model_dump(exclude_none=True)` dropped the key
    entirely for a `text=None` turn (tool calls only, no text content) --
    replaying it then raised a pydantic ValidationError ("text: Field
    required"), so no tool-calling turn from either adapter could ever be
    replayed in dev or CI (EFF-01). A response carrying only `usage` (no
    tool_calls, and text present) round-trips through the same code path
    and is checked here too."""
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")

    tool_call_request = GenerateRequest(prompt="what's the weather?")
    tool_call_response = GenerateResponse(
        text=None,
        profile_id="large",
        tool_calls=[{"name": "get_weather", "args": {"location": "Boston"}}],
    )

    usage_only_request = GenerateRequest(prompt="hello")
    usage_only_response = GenerateResponse(
        text="hi", profile_id="large", usage={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
    )

    class _ScriptedLiveProvider(_CountingLiveProvider):
        def __init__(self):
            super().__init__(calls=[])
            self._responses = {
                "what's the weather?": tool_call_response,
                "hello": usage_only_response,
            }

        def generate(self, request: GenerateRequest) -> GenerateResponse:
            self._calls.append(request)
            return self._responses[request.prompt]

    recorder = RecordReplayProvider(
        role="director", profile_id="large", live_factory=_ScriptedLiveProvider, fixtures_dir=tmp_path
    )
    recorded_tool_call = recorder.generate(tool_call_request)
    recorder.generate(usage_only_request)
    assert recorded_tool_call.text is None, "test setup: a tool-call-only turn has no text"

    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)
    replayer = RecordReplayProvider(
        role="director", profile_id="large", live_factory=_unexpected_live_factory, fixtures_dir=tmp_path
    )

    replayed_tool_call = replayer.generate(tool_call_request)
    assert replayed_tool_call.text is None
    assert replayed_tool_call.tool_calls == tool_call_response.tool_calls

    replayed_usage_only = replayer.generate(usage_only_request)
    assert replayed_usage_only.text == "hi"
    assert replayed_usage_only.usage == usage_only_response.usage


def test_EFF_01_written_recording_scrubs_a_secret_echoed_as_a_dict_key(tmp_path, monkeypatch):
    """Review fix (security): `_redact_strings` walked dict *values* but not
    dict *keys* -- a secret echoed back as an object key (e.g. a tool-call
    argument name) was written to the fixture verbatim. Tool-call args are a
    `dict[str, Any]` (`GenerateResponse.tool_calls`), so a key is exactly as
    reachable as a value here."""
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    fake_secret = "fake-nim-key-" + "".join(str(n) for n in range(20))  # assembled at runtime, not a real key
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("TILO_RECORD", "1")

    class _KeyEchoingLiveProvider(_CountingLiveProvider):
        def generate(self, request: GenerateRequest) -> GenerateResponse:
            self._calls.append(request)
            return GenerateResponse(
                text=None,
                profile_id="large",
                tool_calls=[{"name": "lookup", "args": {fake_secret: "value"}}],
            )

        def redact(self, text: str) -> str:
            return text.replace(fake_secret, "***")

    calls: list[GenerateRequest] = []
    provider = RecordReplayProvider(
        role="director",
        profile_id="large",
        live_factory=lambda: _KeyEchoingLiveProvider(calls),
        fixtures_dir=tmp_path,
    )
    provider.generate(GenerateRequest(prompt="hello"))

    recording_files = list(tmp_path.rglob("*.json"))
    assert recording_files, "record mode must write a recording file"
    for recording_file in recording_files:
        content = recording_file.read_text(encoding="utf-8")
        assert fake_secret not in content, (
            f"16.1 rule 4: {recording_file} must not contain a secret echoed back as a dict key"
        )
        json.loads(content)


def _unexpected_live_factory() -> ModelProvider:
    raise AssertionError("replay mode must not construct a live provider")


class _CountingLiveProvider(ModelProvider):
    """Minimal deterministic `ModelProvider` for record-mode tests; counts
    how many times `generate` is actually called."""

    def __init__(self, calls: list[GenerateRequest]):
        self._calls = calls

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self._calls.append(request)
        return GenerateResponse(text=f"live: {request.prompt}", profile_id="large")

    def stream(self, request: GenerateRequest):
        yield self.generate(request)

    def embed(self, request):
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self):
        return set()

    def price(self):
        raise NotImplementedError


class _AuthenticatingLiveProvider(_CountingLiveProvider):
    """Simulates what a real HTTP-backed adapter does: reads its secret
    from the named env var to authenticate. `RecordReplayProvider` only
    ever sees this class's `ModelProvider`-level request/response, never
    its authentication -- proving redaction by construction, not by an
    extra scrub step the recorder could forget."""

    def __init__(self, api_key_env: str):
        import os  # noqa: PLC0415

        super().__init__(calls=[])
        self._api_key = os.environ[api_key_env]  # used to authenticate a real call; never returned

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        assert self._api_key, "test setup: the fake key must be present"
        return super().generate(request)
