"""Shared helpers for packages/metering tests. Not conftest.py: prepend import mode needs unique basenames."""

import pathlib

import yaml
from tilo_metering import InMemoryFlagStore, MeteringConfig, PriceBook, Treasury

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
METERING_STUB = pathlib.Path(__file__).parent / "data" / "metering.stub.yaml"


def write_yaml(tmp_path: pathlib.Path, name: str, doc: dict) -> pathlib.Path:
    (path := tmp_path / name).write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _prices(effective_date: str, source: str, input_: float, output: float) -> dict:
    """A contracts/providers.schema.json $defs.prices document with fake numbers."""
    doc = {"status": "set", "effective_date": effective_date, "source": source, "currency": "USD"}
    return doc | {"credit_usd": 0.005, "profiles": {"widget": {"input": input_, "output": output}}}


PRICES_V1 = _prices("2026-01-01", "Fake price sheet v1 for tests.", 1.0, 2.0)
PRICES_V2 = _prices("2026-06-01", "Fake price sheet v2 for tests.", 3.0, 6.0)


def metering_config(  # the stub config/metering.yaml document (issue #7); PRD 14.1/14.5 demo defaults
    *, run_credits=300, user_day_credits=1500, org_day_credits=None, daily_usd_soft=15, daily_usd_hard=25
) -> dict:
    return {
        "treasury": {"reserve_margin": 0.15, "request_at": 0.80},
        "caps": {"run_credits": run_credits, "user_day_credits": user_day_credits, "org_day_credits": org_day_credits},
        "spend": {"daily_usd_soft": daily_usd_soft, "daily_usd_hard": daily_usd_hard},
        "reconciliation": {"tolerance": 0.10, "billing_services": []},
    }


def build_treasury(tmp_path: pathlib.Path, *, prices: dict | None = None, **config_overrides):
    """A Treasury wired to a throwaway PriceBook and metering.yaml; returns (treasury, flags)."""
    book = PriceBook.load(write_yaml(tmp_path, "prices.yaml", prices or PRICES_V1))
    config = MeteringConfig.load(write_yaml(tmp_path, "metering.yaml", metering_config(**config_overrides)))
    flags = InMemoryFlagStore()
    return Treasury(config=config, prices=book, flags=flags), flags
