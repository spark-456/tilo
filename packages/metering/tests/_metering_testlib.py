"""Shared fixtures and config/price builders for packages/metering
acceptance tests (ticket P8-01a; PRD 14.1 Credits / 14.5 FR-MTR-01;
se-spec.md "## P8-01"). Trimmed to what the P8-01a test files use; parts b
and c restore the Treasury-only helpers from `tests/P8-01`.

Named _metering_testlib.py (not conftest.py or _lib.py): pytest's default
"prepend" import mode has no package namespacing, so helper modules need
unique basenames across the repo (docs/parallel-sessions.md session SE
ticket spec, section 0).
"""

from __future__ import annotations

import copy
import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Prices (contracts/providers.schema.json $defs.prices, validated through
# tilo_contracts.ProvidersPrices -- PriceBook.load does that validation
# itself). Each fake prices file is one PriceBook "version". Numbers are
# obviously fake, never copied from a real provider price page.
# ---------------------------------------------------------------------------


def prices_version(
    *,
    profiles: dict[str, dict[str, float | None]],
    effective_date: str | None = None,
    status: str = "set",
    source: str | None = "Fake price sheet for tests, not a real provider price page.",
    credit_usd: float = 0.005,
) -> dict:
    """One contracts/providers.schema.json $defs.prices document."""
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
# config/metering.yaml (local stub for contract-change issue #7).
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
