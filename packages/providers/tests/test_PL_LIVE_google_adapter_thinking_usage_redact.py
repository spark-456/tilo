"""PL-02 live Vertex smoke (ticket PL-LIVE-vertex-smoke): the three small changes the smoke needs in the
provider layer itself (`GenerateRequest`, `GoogleModelProvider`), pinned in API_PL_LIVE_vertex_smoke.md.

  (4) thinking level is the minimum the profile allows: `GenerateRequest.thinking_level` exists and the Google
      adapter maps it to the SDK's thinking config;
  (5) metering is honest: billed output includes thinking tokens, so `usage["output_tokens"]` is the candidate
      tokens plus thought tokens (FR-MTR-01 reconciles with the bill within 10%);
  (6) no tokens or secrets in recordings: `GoogleModelProvider.redact` scrubs OAuth access tokens and API keys
      (the shared Authorization/Bearer scrub in `replay.py` does not know their shape).

The SDK is faked at the `sys.modules` boundary; nothing here touches a network.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from _vertex_smoke_lib import FakeVertexSdk, config_thinking_level, fake_secret
from pydantic import ValidationError
from tilo_contracts import ProvidersProfile
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.replay import recording_key


def _provider(sdk: FakeVertexSdk, caps: tuple[str, ...] = ("json", "thinking")):
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "adapter-test-model", "context": 1000, "caps": list(caps)}
    )
    return GoogleModelProvider(
        profile=profile, profile_id="p", project="demo-project", location="global", client=sdk._client()
    )


@pytest.mark.parametrize("level", ["minimal", "low", "medium", "high"])
def test_PL_LIVE_04_generate_request_carries_a_thinking_level_the_adapter_sends(level: str) -> None:
    sdk = FakeVertexSdk()
    with sdk.installed():
        _provider(sdk).generate(GenerateRequest(prompt="hello", thinking_level=level))
    # Vertex 400s on "minimal" (PL-02 fix, 7 Oct 2026): the adapter sends it as "low", the other levels as given
    assert config_thinking_level(sdk.calls[0]["config"]) == ("low" if level == "minimal" else level)


def test_PL_LIVE_04_no_thinking_level_means_no_thinking_config() -> None:
    sdk = FakeVertexSdk()
    with sdk.installed():
        _provider(sdk).generate(GenerateRequest(prompt="hello", max_output_tokens=16))
    config = sdk.calls[0]["config"]
    assert config_thinking_level(config) is None
    assert getattr(config, "max_output_tokens", None) == 16


def test_PL_LIVE_04_a_profile_without_the_thinking_capability_ignores_the_level() -> None:
    # a fallback profile may not think even when the primary does; sending it a thinking config would be a 400
    sdk = FakeVertexSdk()
    with sdk.installed():
        _provider(sdk, caps=("json", "tools")).generate(GenerateRequest(prompt="hello", thinking_level="minimal"))
    assert config_thinking_level(sdk.calls[0]["config"]) is None


def test_PL_LIVE_04_an_unknown_thinking_level_is_rejected_by_the_request_model() -> None:
    assert GenerateRequest(prompt="hello", thinking_level="low").thinking_level == "low"
    assert GenerateRequest(prompt="hello").thinking_level is None
    with pytest.raises(ValidationError):
        GenerateRequest(prompt="hello", thinking_level="maximum")


def test_PL_LIVE_04_existing_recording_keys_do_not_shift() -> None:
    # a request that never sets thinking_level hashes exactly as before the field existed (EFF-01 replay)
    normalised = json.dumps(
        {"role": "r", "profile": "p", "request": {"prompt": "x", "json_mode": False}}, sort_keys=True
    )
    expected = hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]
    assert recording_key("r", "p", GenerateRequest(prompt="x")) == expected


def test_PL_LIVE_05_output_tokens_include_thinking_tokens_because_they_are_billed_as_output() -> None:
    sdk = FakeVertexSdk(usage=(20, 30), thoughts=7)
    with sdk.installed():
        response = _provider(sdk).generate(GenerateRequest(prompt="hello"))
    assert response.usage == {"input_tokens": 20, "output_tokens": 37, "total_tokens": 57}


def test_PL_LIVE_05_without_thought_tokens_output_tokens_are_the_candidate_tokens() -> None:
    sdk = FakeVertexSdk(usage=(20, 30), thoughts=None)
    with sdk.installed():
        response = _provider(sdk).generate(GenerateRequest(prompt="hello"))
    assert response.usage == {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50}


def test_PL_LIVE_06_google_provider_redacts_oauth_access_tokens_and_api_keys() -> None:
    sdk = FakeVertexSdk()
    token, key = fake_secret("access_token"), fake_secret("api_key")
    with sdk.installed():
        provider = _provider(sdk)
        scrubbed = provider.redact(f"reply mentions {token} and also {key} in passing")
    assert token not in scrubbed and key not in scrubbed
    assert "reply mentions" in scrubbed and "in passing" in scrubbed  # only the secrets go
    assert provider.redact("nothing secret here") == "nothing secret here"
