"""PRD 6.4 Model provider layer (ticket P0-02 sections 1 and 2:
providers.schema.json plus example config/models.yaml and config/prices.yaml).

Ticket's rule test: "providers config rejects an unknown capability." PRD 6.4
lists the closed capability set: json, tools, vision, audio, thinking,
computer_use, grounding, code_execution.

Also covers the ticket's config deliverables: both files parse as YAML and
validate against the contract, `config/models.yaml` is marked as an example
with `example: true`, and `config/prices.yaml` never invents a price (status
unset, prices null) -- "the loader will refuse live metering until set."

`providers.schema.json` may hold "two top-level definitions in one file" (as
`$defs.models` / `$defs.prices`) "or split into models and prices
sub-schemas referenced from it" (ticket section 1) -- both shapes are tried
before failing, since the split is the builder's choice.
"""

from __future__ import annotations

import copy

import pytest
import yaml
from _lib import SCHEMA_ID_TEMPLATE, contracts_dir, errors_for, load_json, load_schema

PROVIDERS_ID = SCHEMA_ID_TEMPLATE.format(name="providers")
KNOWN_CAPS = {"json", "tools", "vision", "audio", "thinking", "computer_use", "grounding", "code_execution"}


def _sub_schema_candidates(repo_root, part: str) -> list[dict]:
    """Every schema this repo currently offers that could describe `part`
    ("models" or "prices"): a `$defs.<part>` inside providers.schema.json, or
    a standalone contracts/**/*<part>*.schema.json file.
    """
    candidates: list[dict] = []
    try:
        providers_schema = load_schema(repo_root, "providers")
    except FileNotFoundError:
        providers_schema = {}
    if part in providers_schema.get("$defs", {}):
        candidates.append({"$ref": f"{PROVIDERS_ID}#/$defs/{part}"})
    for path in sorted(contracts_dir(repo_root).glob(f"**/*{part}*.schema.json")):
        candidates.append(load_json(path))
    return candidates


def _validates_against_any(repo_root, registry, part: str, instance) -> tuple[bool, list[str]]:
    candidates = _sub_schema_candidates(repo_root, part)
    if not candidates:
        return False, [
            f"no schema found for {part!r}: no providers.schema.json $defs.{part} and no "
            f"contracts/**/*{part}*.schema.json file"
        ]
    messages: list[str] = []
    for schema in candidates:
        errors = errors_for(schema, instance, registry)
        if not errors:
            return True, []
        messages.append(f"{schema.get('$id', schema)}: {[e.message for e in errors]}")
    return False, messages


@pytest.fixture()
def models_yaml(repo_root):
    path = repo_root / "config" / "models.yaml"
    assert path.is_file(), "PRD 6.4: config/models.yaml must exist (ticket P0-02 section 2)"
    return path, yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture()
def prices_yaml(repo_root):
    path = repo_root / "config" / "prices.yaml"
    assert path.is_file(), "PRD 6.4: config/prices.yaml must exist (ticket P0-02 section 2)"
    return path, yaml.safe_load(path.read_text(encoding="utf-8"))


def test_PRD_6_4_models_yaml_validates_against_providers_contract(repo_root, registry, models_yaml):
    path, data = models_yaml
    ok, messages = _validates_against_any(repo_root, registry, "models", data)
    assert ok, f"PRD 6.4: {path.relative_to(repo_root)} must validate against the providers contract: {messages}"


def test_PRD_6_4_prices_yaml_validates_against_providers_contract(repo_root, registry, prices_yaml):
    path, data = prices_yaml
    ok, messages = _validates_against_any(repo_root, registry, "prices", data)
    assert ok, f"PRD 6.4: {path.relative_to(repo_root)} must validate against the providers contract: {messages}"


def test_PRD_6_4_models_yaml_is_marked_as_an_example(repo_root, models_yaml):
    path, data = models_yaml
    assert data.get("example") is True, (
        'PRD 6.4: config/models.yaml must set "example: true" -- these are example profiles, the '
        "user chooses final models (ticket P0-02 section 2)"
    )
    header = path.read_text(encoding="utf-8").splitlines()[:10]
    assert any("#" in line and "example" in line.lower() for line in header), (
        "PRD 6.4: config/models.yaml must open with a header comment saying these are examples"
    )


def test_PL_06_prices_yaml_status_is_set_with_date_and_source(repo_root, prices_yaml):
    _, data = prices_yaml
    assert data.get("status") == "set", "PL-06: config/prices.yaml carries the user-supplied prices, status set"
    assert data.get("effective_date") == "2026-10-08"  # ADR-0029 draft (regional rates), was 2026-09-24
    assert "Google price pages" in (data.get("source") or "") and "asia-southeast1" in data["source"]


def test_PL_06_status_set_requires_every_value_date_and_source(repo_root, registry, prices_yaml):
    """status set with a null price, date or source fails the contract (never invent a price)."""
    _, data = prices_yaml
    for mutate in (
        lambda d: d["profiles"]["flash-38"].update(input=None),
        lambda d: d["profiles"]["lite-31"].update(output=None),
        lambda d: d.update(effective_date=None),
        lambda d: d.update(source=None),
    ):
        broken = copy.deepcopy(data)
        mutate(broken)
        ok, _ = _validates_against_any(repo_root, registry, "prices", broken)
        assert not ok, "PL-06: a set prices file with a null value, date or source must be rejected"


def test_PL_06_confirmed_prices_and_credit_rate(repo_root, prices_yaml):
    """User-supplied 2026-10-08 (ADR-0029 draft): USD per 1M tokens, asia-southeast1, Standard paid tier."""
    _, data = prices_yaml
    assert data["credit_usd"] == 0.005  # PRD 14.1: 1 credit = US$0.005
    assert data["currency"] == "USD"
    profiles = data["profiles"]
    promo = {"cached_input": 0.0825, "valid_until": "2026-12-31"}  # promotional through 2026-12-31 (ADR-0029 4)
    assert profiles["flash-38"] == {"input": 0.825, "output": 4.125, **promo}
    assert profiles["flash-37"] == {"input": 0.825, "output": 4.125, **promo}
    assert profiles["lite-31"] == {"input": 0.275, "output": 1.65, "cached_input": 0.0275, "audio_input": 0.55}
    # Free NVIDIA NIM trial profiles and the dev fakes make no paid call (read from config, not hard-coded here).
    free_profiles = {"safety-fake"}
    for name in ("models.dev.yaml", "models.nim.yaml"):
        free_profiles |= set(yaml.safe_load((repo_root / "config" / name).read_text(encoding="utf-8"))["profiles"])
    assert len(free_profiles) >= 4
    for free in free_profiles:
        assert profiles[free] == {"input": 0, "output": 0}, f"PL-06: {free} makes no paid call, price 0"


def test_PL_06_every_profile_in_every_models_file_has_a_price(repo_root, prices_yaml):
    _, data = prices_yaml
    priced = set(data["profiles"])
    files = sorted((repo_root / "config").glob("models*.yaml"))
    assert files, "PL-06: expected config/models*.yaml"
    for path in files:
        profiles = yaml.safe_load(path.read_text(encoding="utf-8")).get("profiles", {})
        missing = set(profiles) - priced
        assert not missing, f"PL-06: {path.name} profiles without a price in config/prices.yaml: {sorted(missing)}"


def test_PRD_6_4_providers_config_rejects_unknown_capability(repo_root, registry, models_yaml):
    # config/models.yaml mirrors the PRD 6.4 example directly: a "profiles"
    # mapping of profile id -> {provider, model, context, caps: [...]}.
    _, data = models_yaml
    profiles = data.get("profiles")
    assert isinstance(profiles, dict) and profiles, (
        "PRD 6.4: config/models.yaml must have a non-empty top-level 'profiles' mapping"
    )
    first_profile = next(iter(profiles.values()))
    assert "caps" in first_profile, "PRD 6.4: each models.yaml profile must list 'caps'"

    mutated = copy.deepcopy(data)
    first_key = next(iter(mutated["profiles"]))
    mutated["profiles"][first_key]["caps"] = list(mutated["profiles"][first_key]["caps"]) + ["telepathy"]

    ok, messages = _validates_against_any(repo_root, registry, "models", mutated)
    assert not ok, (
        "PRD 6.4: a models config with an unknown capability ('telepathy', not one of "
        f"{sorted(KNOWN_CAPS)}) must be rejected, but it validated: {messages}"
    )
