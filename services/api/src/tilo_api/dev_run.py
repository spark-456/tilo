"""Local dev stand-ins for the run's seams (CL-INT-5c, 5d, EFF-01; PRD 10.3, 10.4, 14.1): a unit runner that makes one
synthetic artifact per unit, paced by a delay and metered through the real PriceBook with a dev price file, an action
resolver with one fixed fake recipient, and mock connector adapters that only record. They let a dev run reach its gate
card and, once the owner approves, a FAKE send through the real outbox and policy engine; nothing leaves the machine.
`tilo_api.dev.install` wires them as dependency overrides, so request input never selects them, and each one refuses
when deployed or live (the rule dev mode itself uses)."""

from __future__ import annotations

import asyncio
import math
import os
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import cache
from typing import Any

from tilo_connectors.mock import MockConnector
from tilo_metering.prices import PriceBook, Usage

from tilo_api import deps
from tilo_api.runs import MeteredOutcome

DEV_DESTINATION = "thread-dev-1"  # destination.schema: letters, digits, underscore and hyphen only
DEV_RECIPIENT = "dev.recipient@example.com"  # never a known recipient, so the policy engine sees a new one (T3)
DELAY_ENV = "TILO_DEV_UNIT_DELAY_S"  # seconds each unit takes, so "watch the world" is paced, not a burst
DEFAULT_DELAY_S, MAX_DELAY_S = 1.5, 10.0
_UNIT_USAGE = Usage("dev-unit", tokens_in=2000, tokens_out=600)  # fixed fake tokens, priced by config/prices.dev.yaml


def _refuse() -> None:
    from tilo_api.dev import refuse_if_unsafe  # noqa: PLC0415 (dev imports this module)

    refuse_if_unsafe()


def unit_delay_s(env: Mapping[str, str] | None = None) -> float:
    """`TILO_DEV_UNIT_DELAY_S` clamped to 0..10 s; unset, empty or not a finite number means the default."""
    raw = (os.environ if env is None else env).get(DELAY_ENV, "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_DELAY_S
    return min(max(value, 0.0), MAX_DELAY_S) if math.isfinite(value) else DEFAULT_DELAY_S


@cache
def _prices() -> PriceBook:
    return PriceBook.load(deps._REPO_ROOT / "config" / "prices.dev.yaml")


def unit_credits() -> float:
    """What one dev unit costs: fixed fake token counts priced by the real PriceBook (HR-1: the meter sums events)."""
    return round(_prices().credits(_UNIT_USAGE, datetime.now(UTC)), 6)


class DevUnitRunner:
    """No model call: each unit waits `unit_delay_s()` (an asyncio sleep on the run's own thread, so cancelling the run
    ends it and no other request waits), then succeeds with one synthetic artifact (a fresh id per call, so two dev
    worlds never claim the same item) and the metered cost of the unit."""

    async def run(self, unit: Mapping[str, Any], context: Any) -> MeteredOutcome:
        _refuse()
        if (delay := unit_delay_s()) > 0:
            await asyncio.sleep(delay)
        ref = {"artifact_id": f"art_dev_{uuid.uuid4().hex[:20]}", "version": 1}
        return MeteredOutcome(
            success=True, summary=f"Finished {unit['title']}.", artifact_refs=(ref,), credits=unit_credits()
        )


def resolve_action(*, unit: dict, action_type: str, item: dict, brief: dict) -> dict:
    _refuse()
    return {"destination": DEV_DESTINATION, "recipients": [DEV_RECIPIENT], "known_recipients": []}


def mock_adapters() -> dict[str, MockConnector]:
    """One recording MockConnector per connector the shipped config declares (`sent` holds what was 'sent')."""
    registry = deps.get_connector_registry()
    return {connector_id: MockConnector(registry.get(connector_id)) for connector_id in registry.ids()}


def overrides() -> dict[Callable[..., Any], Callable[[], Any]]:
    """The `app.dependency_overrides` entries for the run seams, built once so the adapters keep what they record."""
    runner, adapters = DevUnitRunner(), mock_adapters()

    def get_runner() -> DevUnitRunner:
        _refuse()
        return runner

    def get_resolver() -> Callable[..., dict]:
        _refuse()
        return resolve_action

    def get_adapters() -> dict[str, Any]:
        _refuse()
        return adapters

    return {
        deps.get_unit_runner: get_runner,
        deps.get_action_resolver: get_resolver,
        deps.get_connector_adapters: get_adapters,
    }
