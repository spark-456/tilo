"""Shared fixtures for packages/metering tests (P8-01a; FR-MTR-01). Named
_metering_testlib.py, not conftest.py: prepend import mode needs unique basenames."""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def write_prices_file(tmp_path: pathlib.Path, name: str, prices: dict) -> pathlib.Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(prices, sort_keys=False), encoding="utf-8")
    return path


def _prices(effective_date: str, source: str, input_: float, output: float) -> dict:
    """A contracts/providers.schema.json $defs.prices document, fake numbers."""
    return {
        "status": "set",
        "effective_date": effective_date,
        "source": source,
        "currency": "USD",
        "credit_usd": 0.005,
        "profiles": {"widget": {"input": input_, "output": output}},
    }


PRICES_V1 = _prices("2026-01-01", "Fake price sheet v1 for tests.", 1.0, 2.0)
PRICES_V2 = _prices("2026-06-01", "Fake price sheet v2 for tests.", 3.0, 6.0)


def metering_config(*, daily_usd_soft: float, daily_usd_hard: float) -> dict:
    """A config/metering.yaml document (local stub for issue #7) with the given spend caps."""
    return {
        "treasury": {"reserve_margin": 0.15, "request_at": 0.80},
        "caps": {"run_credits": 300, "user_day_credits": 1500, "org_day_credits": None},
        "spend": {"daily_usd_soft": daily_usd_soft, "daily_usd_hard": daily_usd_hard},
        "reconciliation": {"tolerance": 0.10, "billing_services": []},
    }


def write_metering_config(tmp_path: pathlib.Path, config: dict, name: str = "metering.yaml") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path
