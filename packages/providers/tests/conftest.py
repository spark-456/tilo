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
import pathlib
import socket as socket_module

import pytest
import yaml
from _fake_genai_sdk import fake_genai_sdk  # noqa: F401 -- re-exported so pytest can discover it

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
