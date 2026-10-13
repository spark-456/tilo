"""BYOK-2 (ADR-0041, issue 934): the org-key provider seam in `packages/providers`, variant P (the proxy).

Nothing here holds a customer key: tilo-api's process only ever sees a connectors answer. Fake secrets are assembled
at runtime (no literal looks like a key), nothing goes to the network, nothing is paid. The flag is
`config/byok.yaml` `enabled`, default false; with it off the provider layer is exactly as before.
"""

from __future__ import annotations

import dataclasses
import json
import secrets
import traceback
from typing import Any

import pytest
import yaml
from conftest import (
    ScriptedCall,
    ScriptedModelProvider,
    prices_config_for,
    write_providers_config,
)
from tilo_contracts import ProvidersModels
from tilo_providers.byok import (
    ByokConfig,
    ByokConfigError,
    CredentialRefused,
    FakeOrgProviderSource,
    OrgBinding,
    ProxyOrgProviderSource,
    ProxyRefusal,
    load_byok_config,
)
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.errors import NotConfigured
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router, RouterCredentialError

ORG = "org_one"
URL = "https://byok.example.invalid/v1"


def _fake_key() -> str:  # assembled at runtime: no literal in this file looks like a secret (CLAUDE.md)
    return "".join(["k", "ey-", secrets.token_hex(24)])


def _models() -> dict[str, Any]:
    def org(model: str, kind: str = "openai_compat") -> dict[str, Any]:
        profile: dict[str, Any] = {"provider": kind, "model": model, "context": 100_000, "caps": ["json", "tools"]}
        if kind == "openai_compat":
            profile["base_url"] = URL
            profile["credential"] = "org"  # providers.schema.json 1.4.0, BK-12: the contract's marker (BQ-BYOK-8)
        return profile

    return {
        "example": True,
        "profiles": {
            "tilo-a": {"provider": "fake", "model": "fake-tilo-a", "context": 100_000, "caps": ["json", "tools"]},
            "tilo-b": {"provider": "fake", "model": "fake-tilo-b", "context": 100_000, "caps": ["json", "tools"]},
            "org-big": org("fake-org-big"),
            "org-small": org("fake-org-small"),
            "org-g": org("fake-org-g", "google"),
        },
        "roles": {
            "writer": {"primary": "tilo-a", "fallback": "tilo-b"},
            "director": {"primary": "tilo-a", "fallback": "tilo-b"},
            "safety": {"primary": "tilo-a", "fallback": "tilo-b"},
        },
        "rules": {"deny": []},
    }


def _providers(tmp_path, models: dict[str, Any] | None = None, prices: dict[str, Any] | None = None):
    models = models or _models()
    priced = {p: (1.0, 2.0) for p in models["profiles"]}
    models_path, prices_path = write_providers_config(tmp_path, models, prices or prices_config_for(priced))
    return load_providers_config(models_path, prices_path)


def _byok_yaml(tmp_path, **over: Any):
    doc: dict[str, Any] = {
        "enabled": True,
        "day_cap_credits_max": 10_000,
        "calls_per_org_per_minute": 120,
        "consent_version": 1,
        "bundles": {
            "openai-example": {
                "label": "OpenAI-compatible endpoint (example)",
                "kind": "openai_compat",
                "roles": {"writer": {"primary": "org-big", "fallback": "org-small"}},
            }
        },
    }
    doc.update(over)
    path = tmp_path / "byok.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _binding(config, bundle, source, run_id: str = "r_1") -> OrgBinding:
    return OrgBinding(org_id=ORG, slot="models", run_id=run_id, bundle=bundle, source=source)


class _Calls(FakeOrgProviderSource):
    """Records every provider the router asks the source for."""

    def __init__(self, config, **kw: Any) -> None:
        super().__init__(config, **kw)
        self.asked: list[tuple[str, str, str, str]] = []

    def provider_for(self, org_id, slot, profile_id, run_id):
        self.asked.append((org_id, slot, profile_id, run_id))
        return super().provider_for(org_id, slot, profile_id, run_id)


# --- BK-12 and the flag: the shipped config is inert --------------------------------------------------------------


def test_BK_12_shipped_config_is_off_with_no_bundle_and_missing_file_reads_as_off(repo_root, tmp_path):
    shipped = load_byok_config(repo_root / "config" / "byok.yaml")
    assert shipped.enabled is False and dict(shipped.bundles) == {}
    assert load_byok_config(tmp_path / "absent.yaml").enabled is False  # ADR failure table: missing = not configured


def test_BK_12_flag_off_validates_nothing_else_and_needs_no_provider_config(tmp_path):
    path = _byok_yaml(tmp_path, enabled=False)
    assert load_byok_config(path).enabled is False  # a disabled file is never cross-checked
    with pytest.raises(ByokConfigError):  # an unknown key is refused even when off (closed shape)
        load_byok_config(_byok_yaml(tmp_path, enabled=False, surprise=1))


def test_BK_12_loader_accepts_a_valid_bundle_and_names_its_profiles(tmp_path):
    cfg = load_byok_config(_byok_yaml(tmp_path), providers=_providers(tmp_path))
    bundle = cfg.bundles["openai-example"]
    assert bundle.profile_ids == frozenset({"org-big", "org-small"})
    assert dict(bundle.roles) == {"writer": ("org-big", "org-small")}


@pytest.mark.parametrize(
    "bundle_patch, why",
    [
        ({"roles": {"safety": {"primary": "org-big", "fallback": "org-small"}}}, "a safety role is never BYOK (BK-13)"),
        ({"roles": {"search": {"primary": "org-big", "fallback": "org-small"}}}, "a search role is never BYOK"),
        ({"roles": {"writer": {"primary": "org-big", "fallback": "tilo-b"}}}, "a Tilo profile is never in a cascade"),
        ({"roles": {"writer": {"primary": "org-big", "fallback": "nope"}}}, "an unknown profile"),
        ({"roles": {"nope": {"primary": "org-big", "fallback": "org-small"}}}, "a role the config does not have"),
        ({"roles": {"writer": {"primary": "org-big", "fallback": None}}}, "NFR-25: a fallback is required"),
        ({"kind": "anything_else"}, "an unknown kind"),
        ({"kind": "google_api_key"}, "kind and profile provider must agree"),
    ],
)
def test_BK_13_loader_refuses_a_bad_bundle(tmp_path, bundle_patch, why):
    base = _byok_yaml(tmp_path)
    doc = yaml.safe_load(base.read_text(encoding="utf-8"))
    doc["bundles"]["openai-example"].update(bundle_patch)
    path = _byok_yaml(tmp_path, bundles=doc["bundles"])
    with pytest.raises(ByokConfigError):
        load_byok_config(path, providers=_providers(tmp_path))


def test_BK_12_a_profile_with_an_env_key_is_never_an_org_profile(tmp_path):
    models = _models()
    del models["profiles"]["org-big"]["credential"]  # with both, config.py refuses the pair at load (BYOK-6 tests)
    models["profiles"]["org-big"]["api_key_env"] = "TILO_SOME_TILO_KEY"  # a Tilo credential: never an org's
    with pytest.raises(ByokConfigError):
        load_byok_config(_byok_yaml(tmp_path), providers=_providers(tmp_path, models))


def test_BK_12_a_tilo_role_that_names_an_org_profile_is_refused(tmp_path):
    models = _models()
    models["roles"]["director"] = {"primary": "org-big", "fallback": "tilo-b"}
    with pytest.raises(ProviderConfigError):  # BK-12 lives in config.py now (providers.schema.json 1.4.0)
        _providers(tmp_path, models)
    # defence in depth: the bundle loader refuses it too for a config assembled without that loader
    unchecked = dataclasses.replace(_providers(tmp_path), models=ProvidersModels.model_validate(models))
    with pytest.raises(ByokConfigError):
        load_byok_config(_byok_yaml(tmp_path), providers=unchecked)


def test_BK_12_an_unpriced_org_profile_is_refused_PL_06(tmp_path):
    unset = prices_config_for({p: None for p in _models()["profiles"]}, set_=False)  # status unset: no invented price
    with pytest.raises(ByokConfigError):
        load_byok_config(_byok_yaml(tmp_path), providers=_providers(tmp_path, prices=unset))


def test_BK_16_the_ceiling_and_rate_are_positive_integers(tmp_path):
    for bad in ({"day_cap_credits_max": 0}, {"calls_per_org_per_minute": -1}, {"consent_version": True}):
        with pytest.raises(ByokConfigError):
            load_byok_config(_byok_yaml(tmp_path, **bad), providers=_providers(tmp_path))


def test_BQ_BYOK_2_both_google_modes_are_known_kinds_with_a_google_profile(tmp_path):
    for kind in ("google_api_key", "google_vertex_iam"):
        bundles = {
            "g": {"label": "Gemini", "kind": kind, "roles": {"writer": {"primary": "org-g", "fallback": "org-g"}}}
        }
        cfg = load_byok_config(_byok_yaml(tmp_path, bundles=bundles), providers=_providers(tmp_path))
        assert cfg.bundles["g"].kind == kind


# --- BK-09, BK-10: the Router asks the source for a covered role, never for an uncovered one ------------------------


def _router(config, bundle, source, *, tilo: dict[str, ScriptedModelProvider] | None = None, live: bool = True):
    tilo = tilo or {}
    return Router(
        config,
        provider_for_profile=tilo.__getitem__,
        live_permitted=live,
        org=_binding(config, bundle, source),
    )


def _bundle(tmp_path, config):
    return load_byok_config(_byok_yaml(tmp_path), providers=config).bundles["openai-example"]


def test_BK_10_a_covered_role_runs_on_the_bundles_profiles_through_the_source(tmp_path):
    config = _providers(tmp_path)
    source = _Calls(config)
    tilo = {"tilo-a": ScriptedModelProvider("tilo-a", []), "tilo-b": ScriptedModelProvider("tilo-b", [])}
    result = _router(config, _bundle(tmp_path, config), source, tilo=tilo).generate(
        "writer", GenerateRequest(prompt="Draft the note.")
    )
    assert result.outcome == "ok" and result.response is not None
    assert [a.profile_id for a in result.attempts] == ["org-big"]
    assert source.asked == [(ORG, "models", "org-big", "r_1")]
    assert tilo["tilo-a"].calls == [] and tilo["tilo-b"].calls == [], "Tilo's key is never used for a covered role"


def test_BK_10_a_role_the_bundle_leaves_out_stays_on_tilos_profile_and_meter(tmp_path):
    config = _providers(tmp_path)
    source = _Calls(config)
    tilo = {"tilo-a": ScriptedModelProvider("tilo-a", [ScriptedCall(text="tilo answer")])}
    result = _router(config, _bundle(tmp_path, config), source, tilo=tilo).generate(
        "director", GenerateRequest(prompt="Plan.")
    )
    assert result.response is not None and result.response.text == "tilo answer"
    assert source.asked == [] and [a.payer for a in result.attempts] == ["tilo"]


def test_BK_14_every_attempt_says_who_paid(tmp_path):
    config = _providers(tmp_path)
    result = _router(config, _bundle(tmp_path, config), _Calls(config)).generate("writer", GenerateRequest(prompt="Hi"))
    assert [a.payer for a in result.attempts] == ["org_key"]


def test_BK_10_a_quota_answer_falls_back_inside_the_bundle_never_to_tilo(tmp_path):
    config = _providers(tmp_path)
    source = _Calls(config, refuse={"org-big": "quota"})
    tilo = {"tilo-a": ScriptedModelProvider("tilo-a", []), "tilo-b": ScriptedModelProvider("tilo-b", [])}
    result = _router(config, _bundle(tmp_path, config), source, tilo=tilo).generate(
        "writer", GenerateRequest(prompt="Draft.")
    )
    assert [a.profile_id for a in result.attempts] == ["org-big", "org-small"]
    assert [a.payer for a in result.attempts] == ["org_key", "org_key"]
    assert tilo["tilo-a"].calls == [] and tilo["tilo-b"].calls == []


@pytest.mark.parametrize("code", ["invalid_key", "key_removed", "key_paused", "unverified", "cap_reached"])
def test_BK_17_a_credential_refusal_blocks_the_unit_and_never_falls_back(tmp_path, code):
    config = _providers(tmp_path)
    source = _Calls(config, refuse={"org-big": code})
    tilo = {"tilo-a": ScriptedModelProvider("tilo-a", []), "tilo-b": ScriptedModelProvider("tilo-b", [])}
    with pytest.raises(RouterCredentialError) as caught:
        _router(config, _bundle(tmp_path, config), source, tilo=tilo).generate(
            "writer", GenerateRequest(prompt="Draft.")
        )
    assert caught.value.code == code
    assert [a.profile_id for a in caught.value.attempts] == ["org-big"], "no second profile is tried (no hammering)"
    assert tilo["tilo-a"].calls == [] and tilo["tilo-b"].calls == []


def test_BK_15_a_router_that_cannot_go_live_never_asks_the_source(tmp_path):
    config = _providers(tmp_path)
    source = _Calls(config)
    tilo = {"tilo-a": ScriptedModelProvider("tilo-a", [ScriptedCall(text="replayed")])}
    for kwargs in ({"live": False}, {"live": True, "force": True}):
        router = Router(
            config,
            provider_for_profile=tilo.__getitem__,
            live_permitted=kwargs["live"],
            force_replay=kwargs.get("force", False),
            org=_binding(config, _bundle(tmp_path, config), source),
        )
        tilo["tilo-a"]._script = [ScriptedCall(text="replayed")]  # noqa: SLF001
        result = router.generate("writer", GenerateRequest(prompt="Hi"))
        assert result.response is not None and result.response.text == "replayed"
    assert source.asked == [], "replay and dev make no org-key call (EFF-01, BK-17 step 1)"


def test_BK_13_a_byok_profile_is_generate_only_stream_is_one_chunk_and_embed_is_refused(tmp_path):
    config = _providers(tmp_path)
    provider = FakeOrgProviderSource(config).provider_for(ORG, "models", "org-big", "r_1")
    chunks = list(provider.stream(GenerateRequest(prompt="Hi")))
    assert len(chunks) == 1 and chunks[0].profile_id == "org-big"
    with pytest.raises(NotConfigured):
        provider.embed({"input": ["x"]})


def test_BK_12_the_source_refuses_an_unknown_or_unpriced_profile_before_any_call(tmp_path):
    config = _providers(tmp_path)
    source = FakeOrgProviderSource(config)
    with pytest.raises(CredentialRefused) as caught:
        source.provider_for(ORG, "models", "no-such-profile", "r_1")
    assert caught.value.code == "not_configured"


# --- BK-09, BK-22: no key in tilo-api, and nothing a failing unit raises can carry one --------------------------------


class _Leaky:
    """A connectors double whose failures echo a key into their text, as some providers do (BK-17)."""

    def __init__(self, key: str, mode: str) -> None:
        self.key, self.mode = key, mode

    def generate(self, **_: Any) -> Any:
        if self.mode == "401":
            raise ProxyRefusal("invalid_key")  # a fixed code only
        if self.mode == "5xx":
            raise RuntimeError(f"upstream 502 for Authorization: Bearer {self.key}")
        if self.mode == "timeout":
            raise TimeoutError(f"read timed out calling with {self.key}")
        if self.mode == "malformed":
            return {"text": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}, "key": self.key}
        if self.mode == "cause":
            try:
                raise ValueError(self.key)
            except ValueError as inner:
                raise RuntimeError("wrapped") from inner
        raise AssertionError(self.mode)


@pytest.mark.parametrize("mode", ["401", "5xx", "timeout", "malformed", "cause"])
def test_BK_22_no_key_characters_survive_a_failing_unit(tmp_path, mode):
    key = _fake_key()
    config = _providers(tmp_path)
    source = ProxyOrgProviderSource(config, _Leaky(key, mode))
    router = _router(config, _bundle(tmp_path, config), source)
    seen: list[str] = []
    try:
        result = router.generate("writer", GenerateRequest(prompt="Draft."))
        seen += [repr(result), json.dumps([a.__dict__ for a in result.attempts], default=str)]
    except Exception as error:  # noqa: BLE001
        seen.append("".join(traceback.format_exception(error)))
        seen += [repr(error), str(error), repr(getattr(error, "attempts", ""))]
        cause, depth = error, 0
        while cause is not None and depth < 8:  # every link of the chain, `__cause__` and `__context__`
            seen += [repr(cause), str(cause)]
            cause, depth = cause.__cause__ or cause.__context__, depth + 1
    assert key not in "\n".join(seen), f"BK-22: key characters in the output of a failing unit ({mode})"


def test_BK_09_the_proxy_provider_has_no_credential_attribute_or_field(tmp_path):
    config = _providers(tmp_path)
    provider = FakeOrgProviderSource(config).provider_for(ORG, "models", "org-big", "r_1")
    names = " ".join(vars(provider)).lower()
    assert not any(word in names for word in ("key", "secret", "token", "credential", "password"))
    assert "org-big" in repr(provider) and "http" not in repr(provider)


def test_BK_22_a_reply_with_a_key_field_is_refused_and_not_echoed(tmp_path):
    key = _fake_key()
    config = _providers(tmp_path)
    source = ProxyOrgProviderSource(config, _Leaky(key, "malformed"))
    router = _router(config, _bundle(tmp_path, config), source)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        router.generate("writer", GenerateRequest(prompt="Draft."))
    assert key not in "".join(traceback.format_exception(caught.value))


# --- BK-18: no tool, skill, MCP surface or plan unit reaches the source ----------------------------------------------


def test_BK_18_only_the_router_seam_and_the_api_wiring_name_the_org_source(repo_root):
    allowed = {
        "packages/providers/src/tilo_providers/byok.py",
        "packages/providers/src/tilo_providers/router.py",
        "services/api/src/tilo_api/byok_unit.py",
        "services/api/src/tilo_api/deps.py",
    }
    hits = set()
    for root in ("packages", "services", "skills"):
        for path in (repo_root / root).rglob("*.py"):
            rel = path.relative_to(repo_root).as_posix()
            if "/tests/" in rel or "/node_modules/" in rel or "/.venv/" in rel:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "OrgProviderSource" in text or "ProxyOrgProviderSource" in text:
                hits.add(rel)
    assert hits <= allowed, f"BK-18: unexpected reach of the org source: {sorted(hits - allowed)}"


def test_BK_12_byok_config_type_is_a_plain_frozen_record():
    cfg = ByokConfig()
    assert cfg.enabled is False and cfg.bundles == {}
    with pytest.raises(AttributeError):
        cfg.enabled = True  # type: ignore[misc]
