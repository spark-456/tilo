"""PRD 6.6 "Record and replay" row: "UI work uses a fake provider." Ticket
P0-05 item 5: "Fake provider: deterministic canned responses for UI and
fixture work." Public interface under test: `ModelProvider.generate` (PRD
6.4) via `tilo_providers.fake.FakeModelProvider`.
"""

from __future__ import annotations

from tilo_providers.interfaces import Capability, GenerateRequest, ModelProvider


def _provider(**kwargs):
    from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415

    return FakeModelProvider(**kwargs)


def test_PL_02_fake_provider_conforms_to_model_provider():
    assert isinstance(_provider(), ModelProvider)


def test_PL_02_fake_provider_generate_is_deterministic_for_the_same_request():
    provider = _provider(profile_id="fake-ui-1")
    request = GenerateRequest(prompt="Draft a status update.")

    first = provider.generate(request)
    second = provider.generate(request)

    assert first == second, "UI/fixture work needs stable, repeatable canned responses"
    assert first.profile_id == "fake-ui-1"
    assert first.text, "the canned response must not be empty"


def test_PL_02_fake_provider_generate_varies_with_the_prompt():
    """Deterministic does not mean constant: two different prompts must not
    collapse to the same canned text, or every UI mock would look identical."""
    provider = _provider(profile_id="fake-ui-1")

    a = provider.generate(GenerateRequest(prompt="Draft a status update."))
    b = provider.generate(GenerateRequest(prompt="Draft a risk log."))

    assert a.text != b.text


def test_PL_02_fake_provider_capabilities_and_price_are_configurable_and_stable():
    from tilo_providers.interfaces import PriceQuote  # noqa: PLC0415

    price = PriceQuote(input=0, output=0)
    provider = _provider(profile_id="fake-ui-1", caps={Capability.JSON, Capability.TOOLS}, price=price)

    assert provider.capabilities() == {Capability.JSON, Capability.TOOLS}
    assert provider.price() == price
    assert provider.capabilities() == provider.capabilities(), "must not vary between calls"
