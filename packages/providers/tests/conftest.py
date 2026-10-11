"""Shared fixtures and config builders for packages/providers acceptance
tests (ticket P0-04, PRD 6.4 Model provider layer / 6.6 Cost efficiency /
12.5 Hands roadmap / 17.2 Availability and operations / 14.1 Credits).

Run with `uv run --package tilo-providers pytest` or `uv run pytest
packages/providers/tests` from the repo root. pyyaml, pytest and hypothesis
are shared workspace dev dependencies (root pyproject.toml
[dependency-groups].dev) and pydantic ships transitively via the
tilo-contracts workspace member, so `uv sync --all-packages` already
provides everything these tests import.

This directory has no __init__.py, so pytest's default "prepend" import mode
puts it on sys.path when collecting any test_*.py here -- the same
plain-module-import pattern tests/contracts uses for its own _lib.py.
"""

from __future__ import annotations

import copy
import json
import pathlib
import socket as socket_module
from dataclasses import dataclass
from typing import Any, Literal

import pytest
import yaml
from _fake_genai_sdk import fake_genai_sdk  # noqa: F401 -- re-exported so pytest can discover it
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


# Ticket P0-05 (PL-02, EFF-01): "no test may open a real network connection".
# Autouse so it covers every test in this directory, including ones ticket
# P0-05 writes for adapters that build a real SDK/httpx client -- a stray
# unmocked call fails loudly here instead of hanging or hitting a live model.
# httpx.MockTransport and the google.genai sys.modules fakes (see
# _fake_genai_sdk.py) never reach socket.socket.connect at all, so this is
# defence in depth, not the primary mocking mechanism.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def patient_pdf_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    """LW-06: counting a PDF's pages starts a child process with a wall-clock limit; a loaded machine must not turn a
    slow start into a refusal in a test that is about something else (tests of the limit set their own)."""
    from tilo_providers import media  # noqa: PLC0415

    monkeypatch.setattr(media, "PDF_TIMEOUT_SECONDS", 60.0)


@pytest.fixture(autouse=True)
def block_non_local_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket_module.socket.connect

    def guarded_connect(self: socket_module.socket, address: object, *args: object, **kwargs: object) -> object:
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK_HOSTS:
            raise RuntimeError(
                "packages/providers tests must not open real network connections (EFF-01: dev/CI make no "
                f"paid calls unless LIVE=1) -- blocked socket connect to {address!r}. Use a fake provider, "
                "an injected fake SDK client, or httpx.MockTransport instead."
            )
        return real_connect(self, address, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket_module.socket, "connect", guarded_connect)


# A minimal but schema-shaped config/models.yaml + config/prices.yaml pair
# (contracts/providers.schema.json $defs.models / $defs.prices), independent
# of the real config/ files so each test mutates only the field it exercises.
# "fake" profiles and "fake-*" model ids keep these fixtures out of PL-07's
# real denylist (config/models.yaml rules.deny).
BASE_MODELS: dict = {
    "example": True,
    "profiles": {
        "large": {
            "provider": "fake",
            "model": "fake-large-1",
            "context": 1_000_000,
            "caps": ["json", "tools", "thinking"],
        },
        "medium": {
            "provider": "fake",
            "model": "fake-medium-1",
            "context": 500_000,
            "caps": ["json", "tools"],
        },
        "small": {
            "provider": "fake",
            "model": "fake-small-1",
            "context": 128_000,
            "caps": ["json"],
        },
    },
    "roles": {
        "director": {"primary": "large", "fallback": "medium", "thinking": "high"},
        "specialist": {
            "primary": "medium",
            "fallback": "small",
            "cascade": ["small", "medium"],
            "max_input_tokens": 200_000,
            "max_output_tokens": 8_000,
        },
        # PRD 17.2 NFR-25: "fallback profile per role" -- every role, with no
        # exemption. contracts/providers.schema.json's $defs.role only
        # *requires* "primary", so the loader enforces fallback at start-up
        # (docs/open-questions.md BQ-18).
        "narrator": {"primary": "small", "fallback": "medium"},
    },
    "rules": {"deny": ["fake-legacy-*", "*-preview*"]},
}

BASE_PRICES_UNSET: dict = {
    "status": "unset",
    "effective_date": None,
    "source": None,
    "currency": "USD",
    "credit_usd": 0.005,
    "profiles": {
        "large": {"input": None, "output": None},
        "medium": {"input": None, "output": None},
        "small": {"input": None, "output": None},
    },
}

BASE_PRICES_SET: dict = {
    "status": "set",
    "effective_date": "2026-10-01",
    "source": "Fake provider price page, retrieved 2026-10-01",
    "currency": "USD",
    "credit_usd": 0.005,
    "profiles": {
        "large": {"input": 2.0, "output": 8.0},
        "medium": {"input": 0.5, "output": 2.0},
        "small": {"input": 0.1, "output": 0.4},
    },
}


def models_config() -> dict:
    """A fresh deep copy of BASE_MODELS -- callers mutate their own copy."""
    return copy.deepcopy(BASE_MODELS)


def prices_config(*, set_: bool = False) -> dict:
    """A fresh deep copy of BASE_PRICES_SET (set_=True) or BASE_PRICES_UNSET."""
    return copy.deepcopy(BASE_PRICES_SET if set_ else BASE_PRICES_UNSET)


def write_providers_config(tmp_path: pathlib.Path, models: dict, prices: dict) -> tuple[pathlib.Path, pathlib.Path]:
    """Writes a config/models.yaml + config/prices.yaml pair under tmp_path
    (mirroring the real config/ layout, PRD 6.4) and returns their paths.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    models_path = config_dir / "models.yaml"
    prices_path = config_dir / "prices.yaml"
    models_path.write_text(yaml.safe_dump(models, sort_keys=False), encoding="utf-8")
    prices_path.write_text(yaml.safe_dump(prices, sort_keys=False), encoding="utf-8")
    return models_path, prices_path


@pytest.fixture
def providers_config(tmp_path: pathlib.Path):
    """A loaded, validated `ProvidersConfig` (BASE_MODELS + priced
    BASE_PRICES_SET) for router tests (ticket P0-06) that need a real config
    object without caring about the loader itself (that is P0-04's job,
    already covered by test_NFR_25_*.py and test_PL_07_*.py)."""
    from tilo_providers.config import load_providers_config  # noqa: PLC0415

    models_path, prices_path = write_providers_config(tmp_path, models_config(), prices_config(set_=True))
    return load_providers_config(models_path, prices_path)


def build_providers_config(models: dict, prices: dict):
    """Same validated shape as `providers_config`/`load_providers_config`,
    but in memory (no disk I/O) -- for the Hypothesis property tests, which
    must not use a function-scoped fixture like `tmp_path` inside `@given`
    (Hypothesis's `function_scoped_fixture` health check forbids it, since
    the fixture is not re-created per generated example)."""
    from tilo_contracts import ProvidersModels, ProvidersPrices  # noqa: PLC0415
    from tilo_providers.config import ProvidersConfig  # noqa: PLC0415

    return ProvidersConfig(models=ProvidersModels.model_validate(models), prices=ProvidersPrices.model_validate(prices))


def prices_config_for(price_by_profile: dict[str, tuple[float, float] | None], *, set_: bool = True) -> dict:
    """Same shape as `prices_config()`, but priced for an arbitrary set of
    profile ids -- for router test fixtures (cascade/capability configs
    below) that do not use conftest's large/medium/small profiles."""
    profiles: dict[str, dict[str, float | None]] = {}
    for profile_id, price in price_by_profile.items():
        if set_ and price is not None:
            input_, output_ = price
            profiles[profile_id] = {"input": input_, "output": output_}
        else:
            profiles[profile_id] = {"input": None, "output": None}
    return {
        "status": "set" if set_ else "unset",
        "effective_date": "2026-10-01" if set_ else None,
        "source": "Fake provider price page, retrieved 2026-10-01" if set_ else None,
        "currency": "USD",
        "credit_usd": 0.005,
        "profiles": profiles,
    }


def cascade_models_config() -> dict:
    """One role, "analyst", with a cost-ordered cascade (cheap -> mid ->
    rich) for EFF-02 escalation tests: PRD 6.6 "Cascades" -- "Try the cheap
    profile first; escalate only on schema failure, Verifier rejection or
    low confidence; log every escalation with its reason." """
    return {
        "example": True,
        "profiles": {
            "cheap": {"provider": "fake", "model": "fake-cheap-1", "context": 100_000, "caps": ["json", "tools"]},
            "mid": {"provider": "fake", "model": "fake-mid-1", "context": 100_000, "caps": ["json", "tools"]},
            "rich": {"provider": "fake", "model": "fake-rich-1", "context": 100_000, "caps": ["json", "tools"]},
        },
        "roles": {
            "analyst": {"primary": "cheap", "fallback": "rich", "cascade": ["cheap", "mid", "rich"]},
        },
        "rules": {"deny": []},
    }


def capability_models_config() -> dict:
    """One role, "seer", whose primary profile lacks a capability its
    fallback has -- for the PL-03 "a request needing a capability the
    primary lacks goes straight to a profile that has it" test."""
    return {
        "example": True,
        "profiles": {
            "text-only": {"provider": "fake", "model": "fake-text-1", "context": 100_000, "caps": ["json"]},
            "vision-capable": {
                "provider": "fake",
                "model": "fake-vision-1",
                "context": 100_000,
                "caps": ["json", "vision"],
            },
        },
        "roles": {"seer": {"primary": "text-only", "fallback": "vision-capable"}},
        "rules": {"deny": []},
    }


def token_cap_models_config() -> dict:
    """One role, "summariser", with a deliberately tiny `max_input_tokens`
    (word count, since every test double here counts tokens as
    `len(text.split())` like `FakeModelProvider`) -- for EFF-03 compaction
    tests."""
    return {
        "example": True,
        "profiles": {
            "capped": {"provider": "fake", "model": "fake-capped-1", "context": 1_000, "caps": ["json", "tools"]},
        },
        "roles": {
            "summariser": {
                "primary": "capped",
                "fallback": "capped",
                "max_input_tokens": 10,
                "max_output_tokens": 50,
            },
        },
        "rules": {"deny": []},
    }


def token_cap_tiered_models_config() -> dict:
    """Two *distinct* profiles under one role, "tiered" -- unlike `token_cap_models_config`'s single
    "capped" profile playing both primary and fallback, these are separate ids so a test can give each
    its own `count_tokens` (a different tokenizer) and prove a fallback/escalation candidate gets
    recompacted for its own tokenizer, not sent whatever the first candidate's tokenizer compacted to
    (EFF-03, ticket P0-06 review follow-up)."""
    return {
        "example": True,
        "profiles": {
            "primary-cap": {"provider": "fake", "model": "fake-primary-1", "context": 1_000, "caps": ["json", "tools"]},
            "fallback-cap": {
                "provider": "fake",
                "model": "fake-fallback-1",
                "context": 1_000,
                "caps": ["json", "tools"],
            },
        },
        "roles": {
            "tiered": {
                "primary": "primary-cap",
                "fallback": "fallback-cap",
                "max_input_tokens": 10,
                "max_output_tokens": 50,
            },
        },
        "rules": {"deny": []},
    }


def safety_models_config(safety_provider: str = "fake") -> dict:
    """A minimal config/models.yaml shape (contracts/providers.schema.json
    $defs.models) with one "safety" role, for CC-SP-47 / FR-INT-02's
    `build_safety_provider()` (issue #47 item 3: "a factory build_safety_provider()
    driven by config/models.yaml"). No schema change is needed for this: a
    profile's `provider` field is already a free-form slug
    (`$defs.profile`), so a safety role/profile is exactly as generic as any
    LLM role's -- `build_safety_provider` resolves `roles["safety"].primary`
    the same way `tilo_providers.factory.build_provider` resolves any other
    role. `safety_provider="fake"` exercises FakeSafetyProvider; any other
    value (e.g. "model_armor") exercises the record-and-replay branch,
    per issue #47 item 3 ("record-and-replay like the other providers...
    Model Armor adapter later")."""
    return {
        "example": True,
        "profiles": {
            "safety-active": {
                "provider": safety_provider,
                "model": "fake-safety-1" if safety_provider == "fake" else "model-armor-1",
                "context": 1,
                "caps": [],
            },
        },
        "roles": {
            "safety": {"primary": "safety-active", "fallback": "safety-active"},
        },
        "rules": {"deny": []},
    }


@dataclass
class ScriptedCall:
    """One scripted outcome for `ScriptedModelProvider.generate()`: either a
    canned `GenerateResponse` ("ok") or an exception to raise ("error")."""

    outcome: Literal["ok", "error"] = "ok"
    text: str | None = "scripted response"
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    error: Exception | None = None


class ScriptedModelProvider(ModelProvider):
    """Test double for router tests (PL-03/EFF-02/EFF-03, ticket P0-06):
    plays back a fixed, ordered list of `ScriptedCall`s -- one consumed per
    `generate()` call -- and records every `GenerateRequest` it actually
    received, so a test can assert on what the router sent it (a compacted
    prompt, a filled-in `max_output_tokens`, ...) without a network client
    or a real adapter."""

    def __init__(
        self,
        profile_id: str,
        script: list[ScriptedCall],
        *,
        caps: set[Capability] | None = None,
        price: PriceQuote | None = None,
    ) -> None:
        self.profile_id = profile_id
        self._script = list(script)
        self._caps = set(caps) if caps is not None else {Capability.JSON, Capability.TOOLS}
        self._price = price if price is not None else PriceQuote(input=1.0, output=2.0)
        self.calls: list[GenerateRequest] = []

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.calls.append(request)
        if not self._script:
            raise AssertionError(
                f"ScriptedModelProvider({self.profile_id!r}): ran out of scripted calls at call {len(self.calls)}"
            )
        step = self._script.pop(0)
        if step.outcome == "error":
            assert step.error is not None, "a scripted error step must set `error`"
            raise step.error
        return GenerateResponse(
            text=step.text, profile_id=self.profile_id, tool_calls=step.tool_calls, usage=step.usage
        )

    def stream(self, request: GenerateRequest):
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise NotImplementedError("router tests (ticket P0-06) do not exercise embed()")

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return set(self._caps)

    def price(self) -> PriceQuote:
        return self._price


CONFORMANCE_CHECK_NAMES = (
    "schema_adherence",
    "tool_calling",
    "repair_rate",
    "latency_budget",
    "safety_handling",
)


def write_conformance_result_file(
    conformance_dir: pathlib.Path,
    profile_id: str,
    *,
    result: Literal["pass", "fail"] = "pass",
    date_str: str = "2026-09-25",
    build: str = "test-build",
) -> pathlib.Path:
    """Writes `<conformance_dir>/<profile_id>.json` in the shape PL-05's
    conformance runner produces (see test_PL_05_conformance_suite.py),
    without running the runner -- lets a config-loader gating test fix the
    recorded result directly (PL-05: "a failing profile cannot be assigned
    to a role")."""
    conformance_dir.mkdir(parents=True, exist_ok=True)
    checks = dict.fromkeys(CONFORMANCE_CHECK_NAMES, "pass")
    if result == "fail":
        checks["schema_adherence"] = "fail"
    payload = {"profile_id": profile_id, "date": date_str, "build": build, "checks": checks, "result": result}
    path = conformance_dir / f"{profile_id}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
