"""PRD 6.4: "All model access goes through one interface, ModelProvider, in
packages/providers: generate, stream, embed, count_tokens, capabilities,
price. Sibling interfaces cover SearchProvider, SafetyProvider,
SpeechProvider and RenderProvider. Business code asks for a role, never a
model name." Capabilities: "structured output, tool calling, vision, audio
input, context size, thinking levels, computer use, search grounding, code
execution."

Ticket P0-04 section 1: interfaces "as typing.Protocol or ABCs with pydantic
request/response models... Keep them thin."

Ambiguity resolved (see report): PRD 6.4 names ModelProvider's six methods
explicitly but only asserts that the other four sibling interfaces exist --
it does not name their methods anywhere in the PRD. These tests therefore
require existence plus exactly one PRD-grounded method per sibling
interface, matching the one capability the PRD's surrounding text actually
describes for each: search grounding ("Grounded search through the search
provider", PRD 6.1) -> `search`; safety flags (policy conditions "no safety
flags", PRD 10.4) -> `check`; voice intake/notes "transcribed by the speech
provider" (FR-INT-14, FR-CHN-16) -> `transcribe`; PDF/PPTX "rendered from
templates" (PRD 12.4) -> `render`.
"""

from __future__ import annotations

import inspect
import json

import pydantic
import pytest
from tilo_providers.interfaces import (
    Capability,
    ModelProvider,
    RenderProvider,
    SafetyProvider,
    SearchProvider,
    SpeechProvider,
)


def test_PRD_6_4_capability_enum_matches_providers_schema(repo_root):
    schema = json.loads((repo_root / "contracts" / "providers.schema.json").read_text(encoding="utf-8"))
    schema_caps = set(schema["$defs"]["capability"]["enum"])

    assert {c.value for c in Capability} == schema_caps, "Capabilities must use the enum from providers.schema.json"


def test_PRD_6_4_model_provider_exposes_its_six_methods():
    for name in ("generate", "stream", "embed", "count_tokens", "capabilities", "price"):
        assert hasattr(ModelProvider, name), f"PRD 6.4: ModelProvider must expose {name}"


def test_PRD_6_4_interfaces_module_uses_pydantic_request_response_models():
    import tilo_providers.interfaces as interfaces_module

    model_classes = [
        obj
        for _, obj in inspect.getmembers(interfaces_module, inspect.isclass)
        if issubclass(obj, pydantic.BaseModel) and obj is not pydantic.BaseModel
    ]
    assert model_classes, (
        "ticket P0-04 section 1: interfaces must use pydantic request/response models, found none in "
        "tilo_providers.interfaces"
    )


def test_PRD_6_4_fake_model_provider_passes_conformance_check():
    """A fake ModelProvider, exercising the six PRD 6.4 methods end to end --
    the "tiny conformance check" the ticket asks for."""

    class FakeModelProvider(ModelProvider):
        def generate(self, request):
            return {"text": f"echo: {request['prompt']}", "profile_id": "fake-small"}

        def stream(self, request):
            yield {"text": "chunk", "profile_id": "fake-small"}

        def embed(self, request):
            return {"vectors": [[0.0, 1.0]], "profile_id": "fake-small"}

        def count_tokens(self, text):
            return len(text.split())

        def capabilities(self):
            return {Capability.JSON, Capability.TOOLS}

        def price(self):
            return {"input": 0.1, "output": 0.4}

    fake = FakeModelProvider()

    response = fake.generate({"prompt": "hi"})
    assert response["text"] == "echo: hi"
    assert list(fake.stream({"prompt": "hi"}))[0]["text"] == "chunk"
    assert fake.embed({"texts": ["a"]})["vectors"]
    assert fake.count_tokens("a b c") == 3
    assert Capability.JSON in fake.capabilities()
    assert fake.price()["input"] == pytest.approx(0.1)


@pytest.mark.parametrize(
    ("interface", "method"),
    [
        (SearchProvider, "search"),
        (SafetyProvider, "check"),
        (SpeechProvider, "transcribe"),
        (RenderProvider, "render"),
    ],
)
def test_PRD_6_4_sibling_provider_interface_exists(interface, method):
    assert hasattr(interface, method), f"PRD 6.4: {interface.__name__} must exist and expose {method}"


def test_PRD_6_4_fake_sibling_providers_pass_conformance_check():
    class FakeSearchProvider(SearchProvider):
        def search(self, query, **kwargs):
            return {"results": [f"result for {query}"]}

    class FakeSafetyProvider(SafetyProvider):
        def check(self, text, **kwargs):
            return {"flags": [], "blocked": False}

    class FakeSpeechProvider(SpeechProvider):
        def transcribe(self, audio, **kwargs):
            return {"text": "transcribed"}

    class FakeRenderProvider(RenderProvider):
        def render(self, template, data, **kwargs):
            return {"bytes": b"%PDF-fake", "content_type": "application/pdf"}

    assert FakeSearchProvider().search("suppliers")["results"]
    assert FakeSafetyProvider().check("hello")["blocked"] is False
    assert FakeSpeechProvider().transcribe(b"...")["text"] == "transcribed"
    assert FakeRenderProvider().render("deck.pptx", {})["content_type"] == "application/pdf"
