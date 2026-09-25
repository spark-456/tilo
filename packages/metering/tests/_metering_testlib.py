"""Shared fixtures and config/price builders for packages/metering
acceptance tests (ticket P8-01, PRD 14.1 Credits and the Treasury / 14.5
FR-MTR-01, FR-MTR-02, FR-MTR-04; se-spec.md "## P8-01").

Run with `uv run pytest packages/metering/tests` from the repo root. pyyaml,
pytest and hypothesis are shared workspace dev dependencies (root
pyproject.toml [dependency-groups].dev); tilo-contracts ships as an
existing uv workspace member (packages/contracts-py), so `uv sync
--all-packages` already provides everything these tests import except
tilo_metering itself, which ticket P8-01's builder creates as a new
workspace member (packages/metering, distribution tilo-metering).

This directory has no __init__.py, so pytest's default "prepend" import
mode puts it on sys.path when collecting any test_*.py here -- the same
plain-module-import pattern packages/providers/tests/conftest.py uses.
Named _metering_testlib.py (not conftest.py, and not _lib.py) per
docs/parallel-sessions.md session SE's ticket spec, section 0: helper
modules need unique basenames across the repo because pytest's prepend
import mode has no package namespacing to fall back on.
"""

from __future__ import annotations

import copy
import pathlib

import yaml
from tilo_metering import InMemoryFlagStore, MeteringConfig, PriceBook, Treasury

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Prices (contracts/providers.schema.json $defs.prices, validated through
# tilo_contracts.ProvidersPrices -- PriceBook.load does that validation
# itself, so this helper only has to build schema-shaped dicts). Each fake
# prices file is one PriceBook "version": one status, one effective_date.
# Numbers are obviously fake (never copied from a real provider price
# page) -- root CLAUDE.md "Prices are never invented" is a rule about
# config/prices.yaml, not about throwaway per-test fixtures.
# ---------------------------------------------------------------------------


def prices_version(
    *,
    profiles: dict[str, dict[str, float | None]],
    effective_date: str | None = None,
    status: str = "set",
    source: str | None = "Fake price sheet for tests, not a real provider price page.",
    credit_usd: float = 0.005,
) -> dict:
    """One contracts/providers.schema.json $defs.prices document. status
    "unset" forces effective_date/source to null, mirroring config/prices.yaml
    ("Prices are never invented: status stays unset ... every price, the
    date and the source stay null until the user copies them in.")."""
    return {
        "status": status,
        "effective_date": effective_date if status == "set" else None,
        "source": source if status == "set" else None,
        "currency": "USD",
        "credit_usd": credit_usd,
        "profiles": copy.deepcopy(profiles),
    }


def write_prices_file(tmp_path: pathlib.Path, name: str, prices: dict) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(prices, sort_keys=False), encoding="utf-8")
    return path


# Two versions of the same fake "widget" profile at different effective
# dates, for FR-MTR-01's "ledger uses the new price from its effective
# date" acceptance test.
PRICES_V1: dict = prices_version(
    effective_date="2026-01-01",
    source="Fake price sheet v1 for tests.",
    profiles={"widget": {"input": 1.0, "output": 2.0}},
)

PRICES_V2: dict = prices_version(
    effective_date="2026-06-01",
    source="Fake price sheet v2 for tests.",
    profiles={"widget": {"input": 3.0, "output": 6.0}},
)


# ---------------------------------------------------------------------------
# config/metering.yaml (local stub for contract-change issue #7; se-spec.md
# "Config files (new)" fixes the shape and the demo defaults from PRD
# 14.1 / 14.5: 300 credits per run, $15 soft / $25 hard daily spend).
# ---------------------------------------------------------------------------


def metering_config(
    *,
    reserve_margin: float = 0.15,
    request_at: float = 0.80,
    run_credits: float | None = 300,
    user_day_credits: float | None = 1500,
    org_day_credits: float | None = None,
    daily_usd_soft: float = 15,
    daily_usd_hard: float = 25,
    tolerance: float = 0.10,
    billing_services: list[str] | None = None,
) -> dict:
    return {
        "treasury": {"reserve_margin": reserve_margin, "request_at": request_at},
        "caps": {
            "run_credits": run_credits,
            "user_day_credits": user_day_credits,
            "org_day_credits": org_day_credits,
        },
        "spend": {"daily_usd_soft": daily_usd_soft, "daily_usd_hard": daily_usd_hard},
        "reconciliation": {"tolerance": tolerance, "billing_services": billing_services or []},
    }


def write_metering_config(tmp_path: pathlib.Path, config: dict, name: str = "metering.yaml") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def build_treasury(
    tmp_path: pathlib.Path,
    *,
    prices: dict | None = None,
    **config_overrides,
) -> tuple[Treasury, InMemoryFlagStore]:
    """A Treasury wired to a throwaway single-version PriceBook (fake
    numbers, PRICES_V1 by default) and a temporary config/metering.yaml, for
    tests that exercise reserve/commit/release/grant/caps directly rather
    than multi-version pricing (that is FR-MTR-01's own test file). Returns
    (treasury, flags) so a test can inspect the kill switch directly."""
    prices_path = write_prices_file(tmp_path, "prices.yaml", prices or PRICES_V1)
    book = PriceBook.load(prices_path)
    config_path = write_metering_config(tmp_path, metering_config(**config_overrides))
    config = MeteringConfig.load(config_path)
    flags = InMemoryFlagStore()
    return Treasury(config=config, prices=book, flags=flags), flags
