"""BYOK-6 (ADR-0041, BQ-BYOKC-6): the provider layer follows contracts/providers.schema.json 1.4.0 (`credential: org`),
contracts/byok.schema.json and contracts/model_call_rpc.schema.json. Inert: `config/byok.yaml` stays `enabled: false`.

The generated pydantic models do not enforce the schema's `dependentRequired` and `if/then/else`, so the loader's
rules are pinned here against the contract's own fixtures (the JSON Schema is the judge: tests/contracts)."""

from __future__ import annotations

import copy
import json
import pathlib
import re
from typing import Any

import pytest
import yaml
from _lw06_media import PNG
from test_BYOK_2_org_provider_seam import ORG, _byok_yaml, _models, _providers
from tilo_providers import byok
from tilo_providers.byok import ByokConfigError, ProxyModelProvider, ProxyOrgProviderSource, load_byok_config
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.errors import MissingCapabilityError, ProviderError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.media import MediaPart

FIXTURES = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "providers"
CONTRACTS = FIXTURES.parent.parent
INVALID = sorted((FIXTURES / "invalid").glob("credential_*.json"))


def _load(doc: dict[str, Any], tmp_path: pathlib.Path):
    """The fixtures are schema-level (a role may lack a fallback); the loader's NFR-25 needs one, so each role gets
    its own primary as fallback: a refusal below is then for the credential rule and for nothing else."""
    for role in doc["models"]["roles"].values():
        role.setdefault("fallback", role["primary"])
    models, prices = tmp_path / "models.yaml", tmp_path / "prices.yaml"
    models.write_text(yaml.safe_dump(doc["models"], sort_keys=False), encoding="utf-8")
    prices.write_text(yaml.safe_dump(doc["prices"], sort_keys=False), encoding="utf-8")
    return load_providers_config(models, prices)


def test_BK_12_BYOK_6_the_valid_org_profile_fixture_loads_with_credential_org(tmp_path):
    config = _load(json.loads((FIXTURES / "valid" / "org_profile_credential_org.json").read_text("utf-8")), tmp_path)
    assert config.profiles["byok-large"].credential == "org"
    assert config.profiles["large"].credential is None


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_BK_12_BYOK_6_the_loader_refuses_every_invalid_credential_fixture(path, tmp_path):
    """`credential` on a google profile, with api_key_env, or without base_url is refused at load, as the schema's
    `dependentRequired` and `if/then/else` say (the pydantic model alone accepts all three)."""
    why = "BK-12|PL-02"  # a google profile's base_url is PL-02's: the fixture is refused by either rule, never loaded
    if path.stem.endswith("_tilo"):
        why = "failed schema validation"  # a wrong word is the generated model's own check
    with pytest.raises(ProviderConfigError, match=why):
        _load(json.loads(path.read_text("utf-8")), tmp_path)


@pytest.mark.parametrize("slot", ["primary", "fallback"])
def test_BK_12_BYOK_6_a_tilo_role_that_names_a_credential_org_profile_is_refused_at_load(tmp_path, slot):
    doc = json.loads((FIXTURES / "valid" / "org_profile_credential_org.json").read_text("utf-8"))
    doc["models"]["roles"]["writer"]["fallback"] = "large"
    doc["models"]["roles"]["writer"][slot] = "byok-large"
    with pytest.raises(ProviderConfigError, match="BK-12"):
        _load(doc, tmp_path)


def test_BK_12_BYOK_6_a_bundle_names_only_profiles_with_credential_org(tmp_path):
    """BQ-BYOK-8's marker ("named by a bundle and by no role") is replaced: an openai_compat profile with a fixed
    base_url but no `credential: org` is not an org profile, so a bundle that names it is refused."""
    models = copy.deepcopy(_models())
    assert models["profiles"]["org-big"]["credential"] == "org"
    del models["profiles"]["org-big"]["credential"]
    with pytest.raises(ByokConfigError, match="BK-12"):
        load_byok_config(_byok_yaml(tmp_path), providers=_providers(tmp_path, models))


@pytest.mark.parametrize("label", ["<b>Bold</b>", "see https://evil.example now", "a@b.example", "x" * 81, " lead", ""])
def test_BK_20_BYOK_6_a_bundle_label_is_the_contracts_closed_alphabet(tmp_path, label):
    """Every member sees the label (BK-20): letters, digits, space and `( ) . , ' / _ + -`, 1 to 80, no markup, link
    or address (byok.schema.json bundle.label, BQ-BYOKC-5a)."""
    doc = yaml.safe_load(_byok_yaml(tmp_path).read_text(encoding="utf-8"))
    doc["bundles"]["openai-example"]["label"] = label
    with pytest.raises(ByokConfigError):
        load_byok_config(_byok_yaml(tmp_path, bundles=doc["bundles"]), providers=_providers(tmp_path))


def test_BK_20_BYOK_6_the_loaders_label_and_id_patterns_are_the_schemas():
    defs = json.loads((CONTRACTS / "byok.schema.json").read_text("utf-8"))["$defs"]
    assert byok._LABEL.pattern == defs["bundle"]["properties"]["label"]["pattern"]
    assert byok._BUNDLE_ID.pattern == defs["bundle_id"]["pattern"]
    assert re.fullmatch(byok._BUNDLE_ID, "openai-example") and not re.fullmatch(byok._BUNDLE_ID, "Bad_ID")


def test_BK_20_BYOK_6_a_bundle_id_outside_the_schemas_pattern_is_refused(tmp_path):
    doc = yaml.safe_load(_byok_yaml(tmp_path).read_text(encoding="utf-8"))
    with pytest.raises(ByokConfigError):
        load_byok_config(
            _byok_yaml(tmp_path, bundles={"Not A Slug": doc["bundles"]["openai-example"]}),
            providers=_providers(tmp_path),
        )


# --- model_call_rpc: no media part leaves tilo-api, and an answer is the contract's or a fixed refusal ---------------


class _Recorder:
    def __init__(self, reply: Any = None) -> None:
        self.reply, self.calls = reply, 0

    def generate(self, **_: Any) -> Any:
        self.calls += 1
        return self.reply


def _provider(tmp_path, transport: Any) -> ProxyModelProvider:
    config = _providers(tmp_path)
    return ProxyOrgProviderSource(config, transport).provider_for(ORG, "models", "org-big", "r_1")  # type: ignore[return-value]


def test_BK_10_BYOK_6_a_request_with_a_media_part_is_refused_before_the_transport(tmp_path):
    """model_call_rpc.request has no `parts` (v1 is text only, BK-10): refused here, never sent."""
    transport = _Recorder({"text": "ok"})
    request = GenerateRequest(prompt="Describe.", parts=[MediaPart(mime_type="image/png", data=PNG)])
    with pytest.raises(MissingCapabilityError):
        _provider(tmp_path, transport).generate(request)
    assert transport.calls == 0


@pytest.mark.parametrize(
    "reply",
    [
        {"text": "ok", "usage": {"input_tokens": "3", "output_tokens": 1}},
        {"text": "ok", "usage": {"input_tokens": -1, "output_tokens": 1}},
        {"text": "ok", "usage": {"input_tokens": 1}},
        {"text": "ok", "usage": {"input_tokens": 1, "output_tokens": 1, "reasoning_tokens": 4}},
        {"text": "ok", "tool_calls": [{"args": {}}]},
        {"text": "ok", "tool_calls": [{"name": "t", "args": {}, "id": "x"}]},
        {"text": 5},
        {},
    ],
    ids=lambda r: json.dumps(r)[:48],
)
def test_BK_17_BYOK_6_an_answer_outside_generate_answer_is_a_fixed_unreachable(tmp_path, reply):
    with pytest.raises(ProviderError) as caught:
        _provider(tmp_path, _Recorder(reply)).generate(GenerateRequest(prompt="Hi"))
    assert type(caught.value).__name__ == "RetryableError"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_BK_14_BYOK_6_a_conforming_answer_passes_with_usage_unknown_left_out(tmp_path):
    full = {
        "text": "ok",
        "tool_calls": [{"name": "t", "args": {"a": 1}}],
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5, "cached_tokens": 1},
    }
    got = _provider(tmp_path, _Recorder(full)).generate(GenerateRequest(prompt="Hi"))
    assert got.text == "ok" and got.usage == full["usage"]
    assert _provider(tmp_path, _Recorder({"text": None})).generate(GenerateRequest(prompt="Hi")).usage is None
