"""FR-MEM-05 (PRD 16.1 rule 4: secrets never enter prompts; 16.2): the narrowest seam where text reaches a model is
`Router.generate` / `Router.stream`, which build the `GenerateRequest` each provider receives (`_prepare`). A secret in
the caller's `prompt`, `system` or `tool_outputs` must not be in any request that reaches a provider, and a request
with no secret must arrive exactly as before (replay recording keys hash the request, so nothing may drift).
Fake secrets are assembled at runtime (CLAUDE.md); no network, no model id (profile names only).
"""

from __future__ import annotations

import json

import pytest
from conftest import ScriptedCall, ScriptedModelProvider
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router

TAIL = "Qw3rTy9" * 6
SECRETS = {
    "prompt": "ya" + "29." + TAIL,
    "system": "s" + "k-" + TAIL,
    "tool_output": "Bearer " + TAIL,
}


def _router(config, provider: ScriptedModelProvider) -> Router:
    return Router(config, provider_for_profile={"large": provider}.__getitem__)


def _request() -> GenerateRequest:
    return GenerateRequest(
        prompt=f"Summarise the thread. The user pasted {SECRETS['prompt']} by mistake.",
        system=f"Be brief. Internal note: {SECRETS['system']}",
    )


def _sent(provider: ScriptedModelProvider) -> str:
    return json.dumps([call.model_dump() for call in provider.calls])


@pytest.mark.parametrize("method", ["generate", "stream"])
def test_FR_MEM_05_a_secret_in_the_prompt_system_or_tool_outputs_never_reaches_a_provider(providers_config, method):
    provider = ScriptedModelProvider("large", [ScriptedCall(text="done")])
    result = getattr(_router(providers_config, provider), method)(
        "director", _request(), tool_outputs=[f"fetched page says {SECRETS['tool_output']} ok"]
    )
    if method == "stream":
        list(result)
    assert len(provider.calls) == 1
    assert [name for name, secret in SECRETS.items() if secret in _sent(provider) or TAIL in _sent(provider)] == []
    assert "Summarise the thread." in provider.calls[0].prompt and "Be brief." in (provider.calls[0].system or "")
    assert "fetched page says" in provider.calls[0].prompt
    # what the result keeps for the trace and the archive is redacted too, not just the copy that was sent
    kept = json.dumps([result.request.model_dump(), result.raw_prompt, result.tool_outputs])
    assert TAIL not in kept


def test_FR_MEM_05_a_request_with_no_secret_reaches_the_provider_unchanged(providers_config):
    provider = ScriptedModelProvider("large", [ScriptedCall(text="done")])
    request = GenerateRequest(
        prompt="Summarise the thread for w_01HZXABCDEF, due 2026-10-14, budget $1,200.00.", system="Be brief."
    )
    _router(providers_config, provider).generate("director", request)
    sent = provider.calls[0]
    assert (sent.prompt, sent.system) == (request.prompt, request.system)
