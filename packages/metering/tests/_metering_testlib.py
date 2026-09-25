"""Shared helpers for packages/metering tests. Not conftest.py: prepend import mode needs unique basenames."""

import pathlib

import yaml

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


def metering_config(*, daily_usd_soft: float, daily_usd_hard: float) -> dict:
    """The stub config/metering.yaml document (local stub for issue #7) with the given spend caps."""
    doc = yaml.safe_load(METERING_STUB.read_text(encoding="utf-8"))
    return doc | {"spend": {"daily_usd_soft": daily_usd_soft, "daily_usd_hard": daily_usd_hard}}
