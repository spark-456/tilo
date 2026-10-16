"""A unit's outputs into the artifact store (FR-AGT-02, FR-MEM-06; ADR-0018 sections 1, 5 and 6).

`keep` puts each output under the run's Scope with the idempotency key `<run_id>:<unit_id>:<attempt>:<index>` (AR-05)
and stores a `created` manifest revision from `build_manifest` (FR-CON-10) for each version, before any event is
written: the executor announces a version only once its bytes, record and manifest are all committed (HR-1). The store
gets exactly the buffer's bytes (`bytes(memoryview(content))`), so a caller's `len()` or `__bytes__` is never trusted
(AR-04). A corrupt blob under a key never clears (AR-01), so that output (only) takes the next attempt number, at most
`retries.max_attempts` in all; the others keep their keys. Every other failure raises `OutputRefused` and the unit
fails with nothing announced. What a refused unit stored stays unannounced, so invisible (s6), and would put the
store's next version ahead of EV-15's (#393), so every refusal known before a put is checked first for every output:
kind, size and text (UTF-8, not blank), a parent the world recorded (then put as that checked ref), and a dry run of
the manifest (claims MF-01, MF-06, sources). Only refusals the store alone sees can still leave such a version (the
store has no purge API).
A PDF is the one file a unit may store, and only as a `RenderedPdf` (LW-10): `deliverable.render_output` makes it from a
validated DeliverableSpec by `tilo_render.pdf.render_pdf`, in process, and `keep` stores it with origin `render` (no
agent) under the same AR-05 key, up to `MAX_PDF` bytes. Any other `UnitOutput` stays text or JSON only (AR-04).
The store cannot redact a file, so `keep` runs the redactor over the spec's text (`spec_text`) and refuses the unit if
it would change anything (AR-07 for a file: a secret never reaches a stored PDF).
`existing` accepts refs of versions the store holds in the run's Scope (AR-03) and the world recorded (`recorded`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from tilo_connectors.provenance import build_manifest
from tilo_memory.artifacts import (
    MAX_TEXT,
    TEXT_TYPES,
    ArtifactCorrupt,
    ArtifactNotFound,
    NewVersion,
    Origin,
    StoredVersion,
)
from tilo_memory.website_check import check_website
from tilo_providers.diagnostics import log_caught

MAX_OUTPUTS = 10  # a unit's cap (BQ-257)
MAX_PDF = 20 * 1024 * 1024  # a rendered PDF's cap (LW-10); the store's own file cap is 50 MB
_LABEL_MAX = 80  # event.schema.json item.label
_DRY_REF = {"artifact_id": "art_preflight", "version": 1}  # the manifest dry run's stand-in for a new artifact


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
class RenderedPdf(UnitOutput):
    """A PDF that `tilo_render` made from a validated spec (LW-10). Only `deliverable.render_output` builds one; `keep`
    stores exactly this type (not a subclass) as origin `render`, and nothing else as a file. `spec_text` is the
    validated spec as JSON: what the PDF says, for the redactor."""

    spec_text: str = ""

    def __post_init__(self) -> None:
        if self.media_type != "application/pdf" or not isinstance(self.content, bytes):
            raise ValueError("a rendered PDF is application/pdf bytes")
        if not self.content.startswith(b"%PDF-") or len(self.content) > MAX_PDF:
            raise ValueError(f"a rendered PDF starts with %PDF- and is at most {MAX_PDF} bytes")


@dataclass(frozen=True)
class WebsiteHtml(UnitOutput):
    """One website HTML file (WEB-1, WS-01). Only `website.website_output` builds one, from a writer's `deliver` unit
    of a native website, after the static checker passed; `keep` stores exactly this type as `text/html` (origin
    unit) and refuses any other output that claims HTML. The store runs the checker again on the bytes it keeps."""

    def __post_init__(self) -> None:
        if self.media_type != "text/html" or type(self.content) is not bytes:
            raise ValueError("a website is text/html bytes")


@dataclass(frozen=True)
class Kept:
    version: StoredVersion
    label: str | None


OFFICE_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class RenderedOffice(UnitOutput):
    """Office bytes from the authenticated renderer; spec text is checked before storage."""

    spec_text: str = ""

    def __post_init__(self) -> None:
        if (
            self.media_type not in OFFICE_TYPES
            or type(self.content) is not bytes
            or not 4 < len(self.content) <= MAX_PDF
            or not self.content.startswith(b"PK\x03\x04")
        ):
            raise ValueError("a rendered Office file must be bounded OOXML bytes")


def existing(artifacts: Any, scope: Any, refs: Any, recorded: Callable[[str], int]) -> list[dict[str, Any]]:
    """Each ref as the store's own {artifact_id, version}; OutputRefused unless the store holds it in `scope` and the
    world announced it (`recorded(artifact_id)` is the highest version the world's stream recorded, EV-15)."""
    if not isinstance(refs, list | tuple):
        raise OutputRefused("artifact_refs is not a list")
    found = []
    for ref in refs:
        try:
            version = artifacts.head(scope, ref)
        except ValueError:
            version = None
        if version is None or not 1 <= version.version <= recorded(version.artifact_id):
            raise OutputRefused("a ref names no version this world recorded in this run's scope")
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
    recorded: Callable[[str], int],
) -> list[Kept]:
    """Stores every output and its manifest, or raises OutputRefused (see the module docstring)."""
    if not isinstance(outputs, list | tuple) or len(outputs) > MAX_OUTPUTS:
        raise OutputRefused(f"outputs must be a list of at most {MAX_OUTPUTS}")
    pages = [out for out in outputs if type(out) is WebsiteHtml]
    if pages and (len(pages) > 1 or unit.get("role") != "writer" or unit.get("unit_type") != "deliver"):
        raise OutputRefused("only a writer's deliver unit may output one website HTML file")  # WS-01
    for out in outputs:
        if not isinstance(out, UnitOutput) or not isinstance(out.content, bytes):
            raise OutputRefused("an output is not a UnitOutput with bytes content")
        label = out.label  # it reaches the event stream: plain, short and free of secrets, or the unit fails
        plain = type(label) is str and 0 < len(label) <= _LABEL_MAX and label.isprintable()
        if label is not None and not (plain and redact(label) == label):
            raise OutputRefused("an output label is not 1 to 80 characters free of secrets")
        if (
            type(out) in (RenderedPdf, RenderedOffice)
            and redact(cast(RenderedPdf | RenderedOffice, out).spec_text)
            != cast(RenderedPdf | RenderedOffice, out).spec_text
        ):  # a PDF cannot be redacted
            raise OutputRefused("a rendered report holds a secret")

    def manifest_of(out: UnitOutput, ref: Any, content: bytes, parents: Any, sources: Any) -> dict[str, Any]:
        return build_manifest(
            run_id=run_id,
            artifact=ref,
            content=content,
            parents=parents,
            agent={"agent_id": worker, "role": unit["role"], "model_role": None, "profile": None},
            inputs=[],
            sources=sources,
            claims=[dict(claim) for claim in out.claims],
            events=events,
            archive=archive.records() if archive is not None else [],
            redact=redact,
            archive_head=archive.head() if archive is not None else None,
        )

    kept: list[Kept] = []
    try:
        # every output's known refusals before the first put (#393); each parent as the store's own ref, used as is
        parents = [_preflight(artifacts, scope, out, recorded, manifest_of) for out in outputs]
        for i, (out, parent) in enumerate(zip(outputs, parents, strict=True)):
            for attempt in range(max_attempts):
                try:
                    kept.append(_put(artifacts, scope, out, parent, run_id, unit, worker, f"{attempt}:{i}"))
                    break
                except ArtifactCorrupt:  # never clears under that key (AR-01): only this output takes a new key
                    continue
            else:
                raise OutputRefused("every attempt found a corrupt version")
        for item, out in zip(kept, outputs, strict=True):
            _manifest(artifacts, scope, item.version, out, manifest_of)
    except Exception as error:  # a refused put or manifest, a backend error: the unit fails, nothing announced
        log_caught(error, __name__, locals())
        raise OutputRefused(type(error).__name__) from None
    return kept


def _preflight(
    artifacts: Any, scope: Any, out: UnitOutput, recorded: Callable[[str], int], manifest_of: Any
) -> dict[str, Any] | None:
    """Raises for what the store or the manifest would refuse that is known before a put: a unit's kind, size and
    text (UTF-8, not blank; AR-04), a parent the world never recorded, and a dry run of the manifest (claims, sources;
    MF-01, MF-06). Returns the parent as the store's own ref, or None."""
    if type(out) is RenderedPdf:  # frozen, but re-checked: the file kind is only ever the render path's
        if out.media_type != "application/pdf" or not 5 < len(out.content) <= MAX_PDF or out.content[:5] != b"%PDF-":
            raise OutputRefused("a rendered PDF is not %PDF- bytes of at most 20 MiB")
    elif type(out) is RenderedOffice:
        try:
            RenderedOffice.__post_init__(out)
        except ValueError:
            raise OutputRefused("a rendered Office file is not bounded OOXML bytes") from None
    elif type(out) is WebsiteHtml:
        if not check_website(bytes(memoryview(out.content))).ok:  # WS-09: the store checks again after the redactor
            raise OutputRefused("a website did not pass the static checks")
    elif out.media_type not in TEXT_TYPES or not 0 < memoryview(out.content).nbytes <= MAX_TEXT:
        raise OutputRefused("an output is not 1 byte to 2 MB of text or JSON")
    elif not bytes(memoryview(out.content)).decode("utf-8").strip():  # UnicodeDecodeError on bad UTF-8
        raise OutputRefused("an output's text is blank")
    parents = existing(artifacts, scope, [out.parent], recorded) if out.parent is not None else []
    ref = {"artifact_id": parents[0]["artifact_id"], "version": parents[0]["version"] + 1} if parents else _DRY_REF
    manifest_of(out, ref, b"", parents, [{"id": s["id"], "archive_ref": s["archive_ref"]} for s in out.sources])
    return parents[0] if parents else None


def _put(
    artifacts: Any,
    scope: Any,
    out: UnitOutput,
    parent: dict[str, Any] | None,
    run_id: str,
    unit: Mapping[str, Any],
    worker: str,
    at: str,
) -> Kept:
    new = NewVersion(
        media_type=out.media_type,
        content=bytes(memoryview(out.content)),  # the buffer's bytes: never a subclass's len() or __bytes__
        run_id=run_id,
        origin=Origin(kind="render", unit=unit["id"], agent=None)
        if type(out) in (RenderedPdf, RenderedOffice)
        else Origin(kind="unit", unit=unit["id"], agent=worker),
        sources=tuple(dict(source) for source in out.sources),
        idempotency_key=f"{run_id}:{unit['id']}:{at}",
        parent=parent,  # the ref the preflight checked, never the runner's object again
    )
    return Kept(artifacts.put(scope, new), out.label)


def _manifest(artifacts: Any, scope: Any, version: StoredVersion, out: UnitOutput, manifest_of: Any) -> None:
    """The version's `created` revision; a restarted unit that gets its version back keeps the one it has."""
    try:
        if artifacts.manifest_revisions(scope, version.ref):
            return
    except ArtifactNotFound:
        pass
    record = version.record
    content = artifacts.read(scope, version.ref)  # the stored bytes, re-hashed (AR-01)
    manifest = manifest_of(out, version.ref, content, record["parents"], record["sources"])
    artifacts.add_manifest(scope, version.ref, manifest, stage="created", cause=None)
