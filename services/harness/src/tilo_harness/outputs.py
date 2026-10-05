"""A unit's outputs into the artifact store (FR-AGT-02, FR-MEM-06; ADR-0018 sections 1, 5 and 6).

`keep` puts each output under the run's Scope with the idempotency key `<run_id>:<unit_id>:<attempt>:<index>` (AR-05)
and stores a `created` manifest revision from `build_manifest` (FR-CON-10) for each version, before any event is
written: the executor announces a version only once its bytes, record and manifest are all committed (HR-1). The store
gets exactly `bytes(content)`, so a caller's `len()` is never trusted (AR-04). A corrupt blob under a key never clears
(AR-01), so it starts a new attempt, at most `retries.max_attempts` in all. Every other failure raises `OutputRefused`
and the unit fails with nothing announced; what a failed attempt stored stays unannounced, so invisible (s6).
`existing` accepts refs of versions the store holds in the run's Scope only (AR-03).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from tilo_connectors.provenance import build_manifest
from tilo_memory.artifacts import ArtifactCorrupt, ArtifactNotFound, NewVersion, Origin, StoredVersion

MAX_OUTPUTS = 10  # a unit's cap (BQ-257)
_LABEL_MAX = 80  # event.schema.json item.label


class OutputRefused(Exception):
    """The unit's outputs or refs cannot be stored or named; nothing was announced."""


@dataclass(frozen=True)
class UnitOutput:
    """What a runner made: content, never an id or a hash (the store mints both). `parent` is an artifact_ref of an
    earlier version in the run's scope; `sources` `{id, archive_ref}` and `claims` are the manifest's inputs."""

    media_type: str
    content: bytes
    label: str | None = None
    parent: Mapping[str, Any] | None = None
    sources: tuple[Mapping[str, str], ...] = ()
    claims: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class Kept:
    version: StoredVersion
    label: str | None


def existing(artifacts: Any, scope: Any, refs: Any) -> list[dict[str, Any]]:
    """Each ref as the store's own {artifact_id, version}; OutputRefused unless the store holds it in `scope`."""
    if not isinstance(refs, list | tuple):
        raise OutputRefused("artifact_refs is not a list")
    found = []
    for ref in refs:
        try:
            version = artifacts.head(scope, ref)
        except ValueError:
            version = None
        if version is None:
            raise OutputRefused("a ref names no version of this run's scope")
        found.append(version.ref)
    return found


def keep(
    outputs: Any,
    *,
    artifacts: Any,
    scope: Any,
    archive: Any,
    redact: Callable[[str], str],
    run_id: str,
    unit: Mapping[str, Any],
    worker: str,
    events: list[dict[str, Any]],
    max_attempts: int,
) -> list[Kept]:
    """Stores every output and its manifest, or raises OutputRefused (see the module docstring)."""
    if not isinstance(outputs, list | tuple) or len(outputs) > MAX_OUTPUTS:
        raise OutputRefused(f"outputs must be a list of at most {MAX_OUTPUTS}")
    for out in outputs:
        if not isinstance(out, UnitOutput) or not isinstance(out.content, bytes):
            raise OutputRefused("an output is not a UnitOutput with bytes content")
        label = out.label  # it reaches the event stream: plain, short and free of secrets, or the unit fails
        plain = type(label) is str and 0 < len(label) <= _LABEL_MAX and label.isprintable()
        if label is not None and not (plain and redact(label) == label):
            raise OutputRefused("an output label is not 1 to 80 characters free of secrets")
    for attempt in range(max_attempts):
        try:
            kept = [
                _put(artifacts, scope, out, run_id, unit, worker, f"{attempt}:{i}") for i, out in enumerate(outputs)
            ]
            for item, out in zip(kept, outputs, strict=True):
                _manifest(artifacts, scope, archive, redact, run_id, unit, worker, events, item.version, out)
        except ArtifactCorrupt:  # never clears under that key (AR-01): the next attempt uses new keys
            continue
        except Exception as error:  # a refused put or manifest, a backend error: the unit fails, nothing announced
            raise OutputRefused(type(error).__name__) from None
        return kept
    raise OutputRefused("every attempt found a corrupt version")


def _put(
    artifacts: Any, scope: Any, out: UnitOutput, run_id: str, unit: Mapping[str, Any], worker: str, at: str
) -> Kept:
    new = NewVersion(
        media_type=out.media_type,
        content=bytes(out.content),  # exact bytes: a bytes subclass's own len() is never what the caps see
        run_id=run_id,
        origin=Origin(kind="unit", unit=unit["id"], agent=worker),
        sources=tuple(dict(source) for source in out.sources),
        idempotency_key=f"{run_id}:{unit['id']}:{at}",
        parent=out.parent,
    )
    return Kept(artifacts.put(scope, new), out.label)


def _manifest(
    artifacts: Any,
    scope: Any,
    archive: Any,
    redact: Callable[[str], str],
    run_id: str,
    unit: Mapping[str, Any],
    worker: str,
    events: list[dict[str, Any]],
    version: StoredVersion,
    out: UnitOutput,
) -> None:
    """The version's `created` revision; a restarted unit that gets its version back keeps the one it has."""
    try:
        if artifacts.manifest_revisions(scope, version.ref):
            return
    except ArtifactNotFound:
        pass
    record = version.record
    manifest = build_manifest(
        run_id=run_id,
        artifact=version.ref,
        content=artifacts.read(scope, version.ref),  # the stored bytes, re-hashed (AR-01)
        parents=record["parents"],
        agent={"agent_id": worker, "role": unit["role"], "model_role": None, "profile": None},
        inputs=[],
        sources=record["sources"],
        claims=[dict(claim) for claim in out.claims],
        events=events,
        archive=archive.records() if archive is not None else [],
        redact=redact,
        archive_head=archive.head() if archive is not None else None,
    )
    artifacts.add_manifest(scope, version.ref, manifest, stage="created", cause=None)
