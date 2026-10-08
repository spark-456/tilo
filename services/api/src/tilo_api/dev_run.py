"""Local dev stand-ins for the run's seams (CL-INT-5c, 5d, EFF-01; PRD 10.3, 10.4, 14.1): a unit runner that writes one
synthetic Markdown output per unit, paced by a delay and metered through the real PriceBook with a dev price file, one
in-memory artifact store with a stand-in secret redactor and an empty raw archive (ADR-0018 T4), an action
resolver with one fixed fake recipient, and mock connector adapters that only record. They let a dev run reach its gate
card and, once the owner approves, a FAKE send through the real outbox and policy engine; nothing leaves the machine.
`tilo_api.dev.install` wires them as dependency overrides, so request input never selects them, and each one refuses
when deployed or live (the rule dev mode itself uses)."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import cache
from typing import Any

from tilo_archive import RunArchive
from tilo_connectors.mock import MockConnector
from tilo_harness.outputs import UnitOutput
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend
from tilo_metering.prices import PriceBook, Usage
from tilo_providers.interfaces import GenerateResponse

from tilo_api import deps
from tilo_api.runs import MeteredOutcome

logger = logging.getLogger("tilo_api.dev_run")

DEV_DESTINATION = "thread-dev-1"  # destination.schema: letters, digits, underscore and hyphen only
DEV_RECIPIENT = "dev.recipient@example.com"  # never a known recipient, so the policy engine sees a new one (T3)
DELAY_ENV = "TILO_DEV_UNIT_DELAY_S"  # seconds each unit takes, so "watch the world" is paced, not a burst
DEFAULT_DELAY_S, MAX_DELAY_S = 1.5, 10.0
UNIT_USAGE = Usage("dev-unit", tokens_in=2000, tokens_out=600)  # fixed fake tokens, priced by config/prices.dev.yaml


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
    return round(_prices().credits(UNIT_USAGE, datetime.now(UTC)), 6)


class DevUnitRunner:
    """No model call: each unit waits `unit_delay_s()` (an asyncio sleep on the run's own thread, so cancelling the run
    ends it and no other request waits), then succeeds with one synthetic Markdown output, which the executor puts on
    the dev artifact store (the store mints its id, ADR-0018), and the metered cost of the unit."""

    async def run(self, unit: Mapping[str, Any], context: Any) -> MeteredOutcome:
        _refuse()
        if (delay := unit_delay_s()) > 0:
            await asyncio.sleep(delay)
        text = f"# {unit['title']}\n\nA synthetic dev draft: no model wrote this.\n"
        output = UnitOutput(media_type="text/markdown", content=text.encode("utf-8"))
        return MeteredOutcome(
            success=True, summary=f"Finished {unit['title']}.", outputs=(output,), credits=unit_credits()
        )


_DEV_SECRET = re.compile(r"(?:sk-|AIza|ghp_|xox[abp]-)[0-9A-Za-z_-]{16,}")  # a few well-known API key shapes


def dev_redact(text: str) -> str:
    """Dev mode's stand-in for the shared secret redactor, which is not built yet (FR-MEM-05, BQ-109): masks a few
    well-known key shapes. Dev units write synthetic text only; production has no redactor and starts no run."""
    _refuse()
    return _DEV_SECRET.sub("[REDACTED]", text)


class _NoArchiveLines:
    """The dev run's raw-archive store: dev units read no source, so it holds nothing and takes nothing."""

    def append_line(self, org_id: str, run_id: str, line: str) -> None:
        raise RuntimeError("the dev run archives nothing")

    def read_lines(self, org_id: str, run_id: str) -> list[str]:
        return []


def _no_payloads(payload: Any) -> Any:
    raise RuntimeError("the dev run archives nothing")  # never an identity redactor (BQ-109)


def open_dev_archive(*, org_id: str, run_id: str) -> RunArchive:
    _refuse()
    return RunArchive(_NoArchiveLines(), org_id=org_id, run_id=run_id, redactor=_no_payloads)


def dev_artifact_store() -> ArtifactStore:
    """One in-memory store (ADR-0018 T4, dev mode): unscreened, no archive sources, alerts logged."""
    return ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: datetime.now(UTC),
        redactor=dev_redact,
        archive_lookup=lambda scope, archive_ref: None,
        alert_sink=lambda alert: logger.warning("dev artifact store: %s", alert["summary"]),
    )


class DevClearModel:
    """No model call: every unit is judged clear (FR-AGT-05); only the deterministic rules may ask."""

    def generate(self, request: Any) -> GenerateResponse:
        _refuse()
        return GenerateResponse(text='{"ask": false}', profile_id="dev-clear")


def dev_send_policy(owner: str) -> dict[str, Any]:
    """The dev owner's L1 ("ask me each time") policy for send_email. It covers the action for FR-AGT-05 (PRD 8.3),
    so a dev run still goes straight to its gate card, and changes nothing else: at L1 the engine gates as with none."""
    stamp = {"by": owner, "at": "2026-09-29T09:30:00.000Z"}
    return {
        "id": "pol_dev_send", "owner": owner, "action_type": "send_email",
        "scope": {"connectors": sorted(deps.get_connector_registry().ids()), "recipients": [], "domains": [],
                  "districts": []},
        "limits": {"per_day": None, "credits": None},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": "L1", "undo_window_s": 60, "expiry": None, "notify_channel": "email", "team_lead_domains": [],
        "created_by": stamp, "changed_by": stamp, "history": [{**stamp, "change": "Created at L1", "level": "L1"}],
    }  # fmt: skip


def resolve_action(*, unit: dict, action_type: str, item: dict, brief: dict) -> dict:
    _refuse()
    return {"destination": DEV_DESTINATION, "recipients": [DEV_RECIPIENT], "known_recipients": []}


def mock_adapters() -> dict[str, MockConnector]:
    """One recording MockConnector per connector the shipped config declares (`sent` holds what was 'sent')."""
    registry = deps.get_connector_registry()
    return {connector_id: MockConnector(registry.get(connector_id)) for connector_id in registry.ids()}


def overrides() -> dict[Callable[..., Any], Callable[[], Any]]:
    """The `app.dependency_overrides` entries for the run seams, built once so the adapters keep what they record and
    the run and a reader share one artifact store."""
    runner, adapters, artifacts = DevUnitRunner(), mock_adapters(), dev_artifact_store()

    def get_artifacts() -> ArtifactStore:
        _refuse()
        return artifacts

    def get_redactor() -> Callable[[str], str]:
        _refuse()
        return dev_redact

    def get_archive() -> Callable[..., RunArchive]:
        _refuse()
        return open_dev_archive

    def get_runner() -> DevUnitRunner:
        _refuse()
        return runner

    def get_resolver() -> Callable[..., dict]:
        _refuse()
        return resolve_action

    def get_must_ask() -> dict[str, DevClearModel]:
        _refuse()
        return {role: DevClearModel() for role in ("specialist", "writer", "verifier")}

    def get_adapters() -> dict[str, Any]:
        _refuse()
        return adapters

    return {
        deps.get_unit_runner: get_runner,
        deps.get_action_resolver: get_resolver,
        deps.get_connector_adapters: get_adapters,
        deps.get_must_ask_providers: get_must_ask,
        deps.get_artifact_store: get_artifacts,
        deps.get_redactor: get_redactor,
        deps.get_run_archive: get_archive,
    }
