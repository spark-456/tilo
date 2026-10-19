"""The live-e2e harness's own stand-ins for tilo-api's run seams (ADR-0018 T4; PL-LIVE-E2E).

tilo-api's production seams `get_artifact_store`, `get_redactor` and `get_run_archive` refuse until their real backends
exist (BQ-AGT02-T4-1), so no run starts without them. The eval harness wires these in-memory ones as explicit
dependency overrides on its own private app, and only there. They are NOT `tilo_api.dev_run`'s: those refuse under
`LIVE=1`, which the live run itself sets, and they are not made permissive for the harness. Nothing here reads the
environment, a network or a model; it holds nothing outside the process; dev mode is never set.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from tilo_archive import RunArchive
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend

_SECRET = re.compile(r"ya29\.[\w.-]+|AIza[\w-]{20,}|(?:sk-|ghp_|xox[abp]-)[0-9A-Za-z_-]{16,}")


def redact(text: str) -> str:
    """The shared redactor's stand-in (FR-MEM-05 is not built): masks well-known key shapes in a unit's text."""
    return _SECRET.sub("[REDACTED]", text)


class _NoLines:
    """The run's raw-archive store: the e2e units read no source, so it holds nothing and takes nothing."""

    def append_line(self, org_id: str, run_id: str, line: str) -> None:
        raise RuntimeError("the e2e run archives nothing")

    def read_lines(self, org_id: str, run_id: str) -> list[str]:
        return []


def _no_payloads(payload: Any) -> Any:
    raise RuntimeError("the e2e run archives nothing")  # never an identity redactor (BQ-109)


def open_archive(*, org_id: str, run_id: str) -> RunArchive:
    return RunArchive(_NoLines(), org_id=org_id, run_id=run_id, redactor=_no_payloads)


def artifact_store() -> ArtifactStore:
    """One in-memory store for the whole run: unscreened, no archive sources."""
    return ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: datetime.now(UTC),
        redactor=redact,
        archive_lookup=lambda scope, archive_ref: None,
        alert_sink=lambda alert: None,
    )


def overrides() -> dict[Callable[..., Any], Callable[[], Any]]:
    """The `dependency_overrides` entries for the three seams, over one store shared by the run and its readers."""
    from tilo_api import deps  # noqa: PLC0415

    store = artifact_store()
    return {
        deps.get_artifact_store: lambda: store,
        deps.get_redactor: lambda: redact,
        deps.get_run_archive: lambda: open_archive,
    }
