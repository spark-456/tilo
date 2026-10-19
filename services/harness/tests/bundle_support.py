"""Shared, non-test support for the FR-MEM-10 run bundle acceptance tests (PRD 13.4 emergency fallback, 13.5 FR-MEM-10
"Export and re-import a run; replay is identical"). Not a test module (no `test_` prefix), so pytest never collects it.

THE INTERFACE THESE TESTS PIN is written down in API_FR_MEM_10.md next to this file (the builder may override it and
then updates the tests in the same PR, saying so in the review). In short:

    tilo_harness.run_bundle.export_run(*, events, artifacts, scope, archive, run_id, redact, clock,
                                       limits=DEFAULT_LIMITS) -> bytes      (a ZIP; deterministic; read-only)
    tilo_harness.run_bundle.import_run(bundle, *, writer, artifacts, scope, archive_store, redact,
                                       expected_sha256=None, limits=DEFAULT_LIMITS) -> ImportResult
    tilo_harness.run_bundle.{BundleError, BundleRefused, Limits, DEFAULT_LIMITS, ImportResult}
    tilo_memory.artifacts.ArtifactStore.import_version(scope, record, content) -> StoredVersion

Like the other support files, nothing from the new feature is imported at module level: every helper that needs
`tilo_harness.run_bundle` imports it lazily, so this file always imports and each test fails on the missing feature only
(a ModuleNotFoundError for `tilo_harness.run_bundle`), never on a typo in the test.

Everything here is a fake: in-memory stores, a LocalDirStore under tmp_path, injected clocks, a fake redactor and
screener, no network and no model call. Fake secrets are assembled at runtime (root CLAUDE.md).

"""

from __future__ import annotations

import copy
import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from agt_output_support import (
    ARTICLE,
    CSV,
    JSON_DOC,
    ORG,
    OWNER,
    RUN,
    SECRET,
    WORLD,
    Clock,
    FakeSafety,
    Ran,
    Redactor,
    add_tool_call,
    created_ref,
    make_rig,
    outcome,
    run_units,
    sha,
    unit_output,
)

__all__ = [
    "ARTICLE",
    "CSV",
    "JSON_DOC",
    "ORG",
    "OWNER",
    "RUN",
    "SECRET",
    "WORLD",
    "Clock",
    "FailingRedactor",
    "FakeSafety",
    "GarbledSafety",
    "Redactor",
    "sha",
]

DEST_ORG, DEST_WORLD, DEST_OWNER = "org_replay", "w_replay", "u_reviewer"
EXPORTED_AT = datetime(2026, 10, 7, 8, 0, 0, tzinfo=UTC)
NOTE = "Firm Faa reported revenue of 45 million."
CLAIM = {"id": "cl_1", "location": "slide1/cell:B2", "text": NOTE, "source_ids": ["src_a"], "verified": False}
BUNDLE_JSON = "bundle.json"
EVENTS = "events.jsonl"
ARCHIVE = "archive.jsonl"


# --- the feature, imported lazily ----------------------------------------------------------------------------------


class FailingRedactor:
    """A secret redactor that always raises: every scan must fail closed."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        raise RuntimeError("the redactor is down")


class GarbledSafety(FakeSafety):
    """A screener whose answer is not a verdict ({"flagged": "yes"}): no verdict, so never clean."""

    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> Any:
        super().check(text, content=content, mime_type=mime_type)
        return {"flagged": "yes", "reason": None}


def rb() -> Any:
    """`tilo_harness.run_bundle`, imported on first use so a missing module fails the test, not the collection."""
    import tilo_harness.run_bundle as module

    return module


def refused_type() -> type[BaseException]:
    return rb().BundleRefused  # type: ignore[no-any-return]


# --- the source run: a real executor run on the store ---------------------------------------------------------------


@dataclass
class Src:
    ran: Ran
    rig: Any
    layout: dict[str, Any]
    events: list[dict[str, Any]]
    art_ids: dict[str, str]  # name -> artifact id: brief (md, versions 1..3), prices (csv), table (json)
    archive_ref: str
    archive_dir: Path | None = None

    @property
    def scope(self) -> Any:
        return self.rig.scope

    def refs(self) -> list[dict[str, Any]]:
        """Every version the world recorded, in event order."""
        return [dict(e["data"]["artifact"]) for e in self.events if e["type"] in RECORDING]

    def read(self, ref: dict[str, Any]) -> bytes:
        return bytes(self.rig.store.read(self.rig.scope, ref))

    def archive_lines(self) -> list[str]:
        """The run's raw-archive JSONL as stored, in order."""
        from tilo_archive import LocalDirStore

        return LocalDirStore(self.archive_dir).read_lines(ORG, RUN) if self.archive_dir else []


RECORDING = ("artifact.created", "artifact.versioned", "artifact.rolled_back")


def build_source_run(tmp_path: Path, *, safety: Any = "default", secret_in_brief: bool = False) -> Src:
    """One run: U1 writes a brief (md, with a source in the raw archive and a claim) and a prices csv; U2 writes version
    2 of the brief and a json table; the owner then restores version 1 (a new version 3) and the world records the
    rollback. The raw archive holds the source read. So the stream has artifact.created, .versioned and .rolled_back,
    manifests (`created` revisions), a restore without a manifest, `sources` on records, and an archive chain."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    rig = make_rig(tmp_path / "archive", safety=safety)
    archive_ref = add_tool_call(rig, NOTE)
    add_tool_call(rig, "A second page was read.", "https://example.com/two")
    add_tool_call(rig, "A third page was read.", "https://example.com/three")  # a chain of three records
    brief = ARTICLE + SECRET.encode() if secret_in_brief else ARTICLE
    first = unit_output(
        brief, label="Market brief", sources=({"id": "src_a", "archive_ref": archive_ref},), claims=(CLAIM,)
    )

    def second(unit: dict[str, Any], context: Any, events: list[dict[str, Any]]) -> Any:
        parent = created_ref(events, "A_s0", 0)
        return outcome(
            [
                unit_output(
                    b"# Market brief v2\n\nThree suppliers quoted a price.\n", label="Market brief", parent=parent
                ),
                unit_output(JSON_DOC, "application/json", label="Table"),
            ]
        )

    ran = run_units(
        tmp_path,
        {"U1": outcome([first, unit_output(CSV, "text/csv", label="Prices")]), "U2": second},
        depends={"U2": ["U1"]},
        skills={"U1": ["web_research"]},
        rig=rig,
    )
    created = ran.of("artifact.created")
    brief_id = created[0]["data"]["artifact"]["artifact_id"]
    ref1 = {"artifact_id": brief_id, "version": 1}
    from tilo_memory.artifacts import Origin

    restored = rig.store.restore(rig.scope, ref1, by=Origin(kind="restore"))
    versioned = ran.of("artifact.versioned")[0]
    ran.writer.emit(
        type="artifact.rolled_back",
        actor=OWNER,
        target=brief_id,
        level="L1",
        district="D1",
        summary="The market brief was restored to version 1 as version 3.",
        data={"artifact": restored.ref, "restored_version": 1},
        cause=versioned["id"],
    )
    events = ran.events
    ids = {}
    for event in created:
        name = {"Market brief": "brief", "Prices": "prices", "Table": "table"}[event["item"]["label"]]
        ids[name] = event["data"]["artifact"]["artifact_id"]
    return Src(ran, rig, ran.layout, events, ids, archive_ref, tmp_path / "archive")


def build_random_run(tmp_path: Path, units: list[list[tuple[str, bytes]]]) -> Src:
    """A run with one unit per entry of `units`, each writing the given (media type, bytes) outputs, and one source read
    in the raw archive. Used by the property tests."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    rig = make_rig(tmp_path / "archive")
    archive_ref = add_tool_call(rig, NOTE)
    script = {
        f"U{i + 1}": outcome([unit_output(content, media) for media, content in outputs])
        for i, outputs in enumerate(units)
    }
    ran = run_units(tmp_path, script, rig=rig)
    return Src(ran, rig, ran.layout, ran.events, {}, archive_ref, tmp_path / "archive")


def build_plain_run(tmp_path: Path) -> Src:
    """A run with no artifact store and no archive (nothing to carry but events)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    ran = run_units(
        tmp_path,
        {"U1": outcome([]), "U2": outcome([])},
        depends={"U2": ["U1"]},
        with_store=False,
    )
    return Src(ran, ran.rig, ran.layout, ran.events, {}, "")


# --- the importing side ---------------------------------------------------------------------------------------------


class Spy:
    """Forwards every attribute of `inner` and records each method call as (name, args)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args))
            return attr(*args, **kwargs)

        return call

    def called(self, name: str) -> list[tuple[str, tuple[Any, ...]]]:
        return [c for c in self.calls if c[0] == name]

    def mentions(self, needle: str) -> bool:
        return needle in repr(self.calls)


class FailingBlobs:
    """A BlobBackend whose `create` raises on the `fail_on`-th call (1-based); every other call is forwarded."""

    def __init__(self, inner: Any, fail_on: int) -> None:
        self.inner, self.fail_on, self.creates = inner, fail_on, 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def create(self, key: str, data: bytes) -> None:
        self.creates += 1
        if self.creates == self.fail_on:
            raise OSError("the blob backend is down")
        self.inner.create(key, data)


class FailingArchiveStore:
    """An archive Store whose `append_line` raises on the `fail_on`-th call (1-based)."""

    def __init__(self, inner: Any, fail_on: int) -> None:
        self.inner, self.fail_on, self.appends = inner, fail_on, 0

    def append_line(self, org_id: str, run_id: str, line: str) -> None:
        self.appends += 1
        if self.appends == self.fail_on:
            raise OSError("the archive store is down")
        self.inner.append_line(org_id, run_id, line)

    def read_lines(self, org_id: str, run_id: str) -> list[str]:
        return self.inner.read_lines(org_id, run_id)


def flaky_event_store(fail_seq: int | None) -> Any:
    """A MemoryStore whose commit of the event with `seq == fail_seq` raises OSError (an outage); later calls work
    again once `fail_seq` is set to None."""
    from tilo_harness.store import MemoryStore

    class Flaky(MemoryStore):
        fail: int | None = fail_seq

        def transact(self, org_id: str, world_id: str, fn: Any) -> Any:
            def wrapped(head: dict[str, Any]) -> Any:
                out = fn(head)
                if out[1] is not None and out[1]["seq"] == self.fail:
                    raise OSError("the event store is down")
                return out

            return super().transact(org_id, world_id, wrapped)

    return Flaky()


@dataclass
class Dest:
    org: str
    world: str
    owner: str
    scope: Any
    layout: dict[str, Any]
    events: Any  # the harness event store
    writer: Any
    artifacts: Any
    meta: Spy
    blobs: Spy
    archive_store: Any
    archive_root: Path
    redactor: Redactor
    safety: FakeSafety | None
    clock: Clock
    extra: dict[str, Any] = field(default_factory=dict)

    def stream(self) -> list[dict[str, Any]]:
        return self.events.read_events(self.org, self.world)

    def view(self, scope: str) -> list[dict[str, Any]]:
        return self.events.read_view(self.org, self.world, scope)

    def archive_lines(self, run_id: str = RUN) -> list[str]:
        return self.archive_store.read_lines(self.org, run_id)

    def archive_files(self) -> list[str]:
        return sorted(p.relative_to(self.archive_root).as_posix() for p in self.archive_root.rglob("*") if p.is_file())

    def snapshot(self) -> dict[str, Any]:
        """Everything an import could have written, to compare before and after a refusal or a re-import."""
        return {
            "events": copy.deepcopy(self.stream()),
            "views": {s: copy.deepcopy(self.view(s)) for s in self.view_scopes()},
            "meta": {p: copy.deepcopy(self.meta.inner.get(p)) for p in self.meta.inner.paths()},
            "blobs": {k: bytes(self.blobs.inner.read(k)) for k in self.blobs.inner.keys()},
            "archive": self.archive_files(),
            "archive_lines": self.archive_lines(),
        }

    def view_scopes(self) -> list[str]:
        from tilo_harness.views import scopes_for

        return scopes_for(self.layout)


def make_dest(
    tmp_path: Path,
    layout: dict[str, Any],
    *,
    org: str = DEST_ORG,
    world: str = DEST_WORLD,
    owner: str = DEST_OWNER,
    safety: Any = "default",
    name: str = "dest",
    events_store: Any = None,
    blobs: Any = None,
    redactor: Redactor | None = None,
    archive_wrapper: Callable[[Any], Any] | None = None,
) -> Dest:
    """A fresh world: an opened WorldWriter over an empty event store, an empty artifact store (spied backends) under
    the importer's Scope, and an empty archive directory. `layout` is the source run's, re-labelled for the new
    world."""
    from tilo_archive import LocalDirStore
    from tilo_harness.store import MemoryStore
    from tilo_harness.writer import WorldWriter
    from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, Scope

    dest_layout = copy.deepcopy(layout)
    dest_layout["world_id"] = world
    store = events_store or MemoryStore()
    writer = WorldWriter(store, org_id=org, world_id=world, run_id=RUN, layout=dest_layout, writer_id="importer")
    writer.open()
    meta, blob_backend = Spy(MemoryMetaBackend()), Spy(blobs if blobs is not None else MemoryBlobBackend())
    clock, red = Clock(), redactor or Redactor()
    screener = FakeSafety() if safety == "default" else safety
    scope = Scope(org_id=org, world_id=world, owner=owner)
    artifacts = ArtifactStore(
        meta,
        blob_backend,
        clock=clock,
        redactor=red,
        archive_lookup=lambda _scope, _ref: None,
        alert_sink=lambda _alert: None,
        screener=screener,
    )
    root = tmp_path / f"{name}_archive"
    inner = LocalDirStore(root)
    return Dest(
        org, world, owner, scope, dest_layout, store, writer, artifacts, meta, blob_backend,
        archive_wrapper(inner) if archive_wrapper else inner, root, red, screener, clock,
    )  # fmt: skip


_UNSET: Any = object()


def do_export(src: Src, **overrides: Any) -> bytes:
    kwargs: dict[str, Any] = {
        "events": src.events,
        "artifacts": src.rig.store,
        "scope": src.rig.scope,
        "archive": src.rig.archive,
        "run_id": RUN,
        "redact": src.rig.redactor,
        "clock": lambda: EXPORTED_AT,
    }
    kwargs |= overrides
    return rb().export_run(**kwargs)  # type: ignore[no-any-return]


def do_import(dest: Dest, bundle: bytes, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "writer": dest.writer,
        "artifacts": dest.artifacts,
        "scope": dest.scope,
        "archive_store": dest.archive_store,
        "redact": dest.redactor,
    }
    kwargs |= overrides
    return rb().import_run(bundle, **kwargs)


def limits(**changes: int) -> Any:
    import dataclasses

    return dataclasses.replace(rb().DEFAULT_LIMITS, **changes)


# --- the bundle as bytes: unpack, edit, repack ----------------------------------------------------------------------


def unpack(bundle: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def pack(entries: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, entries[name])
    return out.getvalue()


def raw_pack(items: list[tuple[str, bytes]], *, attrs: dict[str, int] | None = None) -> bytes:
    """A ZIP with exactly these (name, bytes) items in this order, names taken verbatim (duplicates, `..`, backslashes
    and drive letters included: `ZipInfo` would normalise them), for the hostile-input tests. `attrs` sets the external
    attributes (Unix mode in the high 16 bits) of a name, e.g. a symlink."""
    import warnings

    out = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        warnings.simplefilter("ignore")  # zipfile warns about duplicate names; that is the point here
        for name, data in items:
            info = zipfile.ZipInfo("placeholder", date_time=(1980, 1, 1, 0, 0, 0))
            info.filename = name
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (attrs or {}).get(name, 0o644 << 16)
            archive.writestr(info, data)
    return out.getvalue()


def jb(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def jsonl(items: list[Any]) -> bytes:
    return b"".join(jb(item) + b"\n" for item in items)


def lines_of(blob: bytes) -> list[str]:
    return [line for line in blob.decode("utf-8", "replace").split("\n") if line.strip()]


def meta_of(entries: dict[str, bytes]) -> dict[str, Any]:
    return json.loads(entries[BUNDLE_JSON])  # type: ignore[no-any-return]


def reindex(entries: dict[str, bytes]) -> dict[str, bytes]:
    """Makes `bundle.json`'s per-entry SHA-256 index agree with the entries, as a forger who edits an entry would."""
    meta = meta_of(entries)
    meta["entries"] = {name: sha(data) for name, data in entries.items() if name != BUNDLE_JSON}
    entries[BUNDLE_JSON] = jb(meta)
    return entries


def _revision_count(data: bytes) -> int:
    try:
        parsed = json.loads(data)
    except (ValueError, RecursionError):  # a forged, malformed entry: the importer must refuse it, not this helper
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


def recount(entries: dict[str, bytes]) -> dict[str, bytes]:
    """Makes `bundle.json`'s counts agree with the entries (events, archive records, versions, manifest revisions)."""
    meta = meta_of(entries)
    revisions = sum(_revision_count(data) for name, data in entries.items() if name.endswith("/manifests.json"))
    meta["counts"] = {
        "events": len(lines_of(entries[EVENTS])),
        "archive_records": len(lines_of(entries[ARCHIVE])),
        "versions": sum(1 for name in entries if name.endswith("/record.json")),
        "manifest_revisions": revisions,
    }
    entries[BUNDLE_JSON] = jb(meta)
    return entries


def edited(
    bundle: bytes, edit: Callable[[dict[str, bytes]], None], *, index: bool = False, count: bool = False
) -> bytes:
    """The bundle with `edit` applied to its entries; the index and counts are fixed up only on request."""
    entries = unpack(bundle)
    edit(entries)
    if index:
        reindex(entries)
    if count:
        recount(entries)
    return pack(entries)


def names(entries: dict[str, bytes], suffix: str) -> list[str]:
    return sorted(name for name in entries if name.endswith(suffix))


# --- comparing a replay with its source ----------------------------------------------------------------------------


def retarget(event: dict[str, Any], world_id: str) -> dict[str, Any]:
    """The only change an import makes to an event: it belongs to the importer's world."""
    return dict(event, world_id=world_id)


def scrub_screening(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if k != "screened_at"}


def assert_replayed_identically(src: Src, dest: Dest, *, bundle_refs: list[dict[str, Any]] | None = None) -> None:
    """Replaying the imported run gives the identical event stream, artifact bytes and hashes, manifests, archive and
    per-scope views (PRD 13.5 FR-MEM-10); only identity (world, org, owner) is the importer's."""
    from tilo_archive.archive import verify_chain

    assert dest.stream() == [retarget(e, dest.world) for e in src.events], "identical events but for the world"
    for ref in bundle_refs if bundle_refs is not None else src.refs():
        got = dest.artifacts.head(dest.scope, ref)
        want = src.rig.store.head(src.scope, ref)
        assert got is not None and want is not None, f"{ref} is imported"
        assert dest.artifacts.read(dest.scope, ref) == src.read(ref), "identical artifact bytes"
        assert got.record["content_sha256"] == want.record["content_sha256"] == sha(src.read(ref)), "identical hashes"
        identity = {"org_id": dest.org, "world_id": dest.world, "owner": dest.owner, "sources": []}
        assert scrub_screening(got.record) == scrub_screening(dict(want.record, **identity)), "the same record"
        want_revisions = revisions_of(src.rig.store, src.scope, ref)
        assert revisions_of(dest.artifacts, dest.scope, ref) == want_revisions, "identical manifest revisions"
    assert dest.archive_lines() == src.archive_lines(), "identical raw-archive records"
    assert verify_chain([json.loads(line) for line in dest.archive_lines()]) == []
    for scope in dest.view_scopes():
        want_view = src.ran.store.read_view(ORG, src.ran.world_id, scope)
        assert dest.view(scope) == [retarget(e, dest.world) for e in want_view], f"identical {scope} view"
    for artifact_id in {r["artifact_id"] for r in src.refs()}:
        assert dest.writer.recorded_version(artifact_id) == src.ran.writer.recorded_version(artifact_id)


def revisions_of(store: Any, scope: Any, ref: dict[str, Any]) -> list[dict[str, Any]]:
    from tilo_memory.artifacts import ArtifactNotFound

    try:
        return store.manifest_revisions(scope, ref)  # type: ignore[no-any-return]
    except ArtifactNotFound:
        return []


def assert_nothing_imported(dest: Dest) -> None:
    assert dest.stream() == [], "no event was written"
    assert all(dest.view(s) == [] for s in dest.view_scopes()), "no view was written"
    assert dest.meta.inner.paths() == [] and dest.blobs.inner.keys() == [], "no artifact record or blob was stored"
    assert dest.archive_files() == [] and dest.archive_lines() == [], "no raw-archive record was written"


def refused_and_nothing_written(dest: Dest, bundle: bytes, **kw: Any) -> BaseException:
    """The import is refused with BundleRefused and the importer's world, stores and archive are exactly as before."""
    before = dest.snapshot()
    with pytest.raises(refused_type()) as caught:
        do_import(dest, bundle, **kw)
    assert dest.snapshot() == before, "a refused import writes nothing"
    return caught.value
