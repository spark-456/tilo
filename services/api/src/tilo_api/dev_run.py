"""Local dev stand-ins for the run's seams (CL-INT-5c, EFF-01; PRD 10.3, 10.4): a unit runner that makes one synthetic
artifact per unit, an action resolver with one fixed fake recipient, and mock connector adapters that only record. They
let a dev run reach its gate card and, once the owner approves, a FAKE send through the real outbox and policy engine;
nothing leaves the machine. `tilo_api.dev.install` wires them as dependency overrides, so request input never selects
them, and each one refuses when deployed or live (the rule dev mode itself uses)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from tilo_connectors.mock import MockConnector
from tilo_harness.executor import UnitOutcome

from tilo_api import deps

DEV_DESTINATION = "thread-dev-1"  # destination.schema: letters, digits, underscore and hyphen only
DEV_RECIPIENT = "dev.recipient@example.com"  # never a known recipient, so the policy engine sees a new one (T3)


def _refuse() -> None:
    from tilo_api.dev import refuse_if_unsafe  # noqa: PLC0415 (dev imports this module)

    refuse_if_unsafe()


class DevUnitRunner:
    """No model call: each unit succeeds with one synthetic artifact (a fresh id per call, so two dev worlds never
    claim the same item)."""

    async def run(self, unit: Mapping[str, Any], context: Any) -> UnitOutcome:
        _refuse()
        ref = {"artifact_id": f"art_dev_{uuid.uuid4().hex[:20]}", "version": 1}
        return UnitOutcome(success=True, summary=f"Finished {unit['title']}.", artifact_refs=(ref,))


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
