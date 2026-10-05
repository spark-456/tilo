"""Shared, non-test support for the FR-AGT-02 unit-output acceptance tests (ADR-0018 section 5 "ticket 3", T3).
Not a test module (no `test_` prefix), so pytest never collects it.

THE INTERFACE THESE TESTS PIN (the ADR names the pieces; the exact keywords are chosen here and may be overridden by
the builder, who then updates these tests in the same PR and says so in the review):

    tilo_harness.executor.UnitOutput(media_type, content, label=None, parent=None, sources=(), claims=())
        frozen dataclass. `content` is `bytes`; `parent` an artifact_ref of an earlier version in the run's scope;
        `sources` `[{"id": slug, "archive_ref": "<run_id>/<seq>"}]`; `claims` manifest claims
        `{"id", "location", "text", "source_ids", "verified"}`.
    UnitOutcome.outputs: tuple[UnitOutput, ...] = ()   (new field, after the existing ones)
    UnitOutcome.artifact_refs                          (existing field): refs of versions that already exist
    run_plan(..., artifacts: ArtifactStore | None = None, scope: Scope | None = None,
             archive: RunArchive | None = None, redact: Callable[[str], str] | None = None)
        `artifacts` + `scope` (`tilo_memory.artifacts`): where outputs are put. The store itself holds the injected
        redactor, the SafetyProvider-shaped screener, the clock and the archive lookup (T2 API, API_FR_MEM_06.md).
        `archive` (`tilo_archive.RunArchive`): the run's raw archive; `archive.records()` and `archive.head()` are
        what `build_manifest` gets (FR-CON-10, #187). `redact`: the shared secret redactor, the same one the store
        got, passed on to `build_manifest` (MF-06); the store has no accessor for it. `artifacts` and `scope` are
        given together; `redact` is given with them.
    The idempotency key of an output is `<run_id>:<unit_id>:<attempt>:<index>` (AR-05), `run_id` the writer's.

Like agt_support, nothing from the new feature is imported at module level: every helper imports lazily, so this file
always imports and each test fails on the missing feature only (an ImportError for `UnitOutput`, a TypeError for
`UnitOutcome(outputs=...)`, or a wrong behaviour), never on a typo in the test.

Everything here is a fake: an in-memory store, an injected clock, a fake redactor and screener, a fake archive
lookup, no network and no model call. Fake secrets are assembled at runtime (root CLAUDE.md).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agt_support import (
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer

ORG, OWNER, RUN = "org_demo", "u_owner", "r_test_1"  # org and run are make_memory_writer's defaults
WORLD = "w_unit_out"
T0 = datetime(2026, 10, 5, 9, 30, 0, tzinfo=UTC)
TEXT_TYPES = ("text/markdown", "text/csv", "application/json")
ARTICLE = b"# Market brief\n\nThree suppliers quoted a price.\n"
CSV = b"item,price\nbolt,4\n"
JSON_DOC = b'{"rows": [1, 2, 3]}'
SECRET = "fake-secret-" + "".join(["0x", "DEAD", "BEEF"])  # assembled at runtime, never a literal secret


def sha(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


# --- the store's collaborators: all fakes ---------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


class Redactor:
    """Replaces SECRET. Counts and records its inputs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        return text.replace(SECRET, "[REDACTED]")


class FakeSafety:
    """SafetyProvider-shaped screener: `check(text, *, content, mime_type) -> {"flagged", "reason"}`."""

    def __init__(self, *, flagged: bool = False, error: BaseException | None = None) -> None:
        self.flagged, self.error = flagged, error
        self.calls: list[dict[str, Any]] = []

    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> Any:
        self.calls.append({"text": text, "content": content, "mime_type": mime_type})
        if self.error is not None:
            raise self.error
        return {"flagged": self.flagged, "reason": "fake" if self.flagged else None}


class FailingMeta:
    """Wraps a MetaBackend; `create` raises OSError for any document whose idempotency key names `fail_unit`."""

    def __init__(self, inner: Any, fail_unit: str | None = None) -> None:
        self.inner, self.fail_unit = inner, fail_unit

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def create(self, path: str, doc: dict[str, Any]) -> None:
        key = doc.get("idempotency_key") if isinstance(doc, dict) else None
        if self.fail_unit and isinstance(key, str) and key.split(":")[1] == self.fail_unit:
            raise OSError("the metadata backend is down")
        self.inner.create(path, doc)


class Sized(bytes):
    """One real byte that reports `len()` of `size`: a runner's object whose length lies (large)."""

    _size: int

    def __new__(cls, size: int, seed: bytes = b"x") -> Sized:
        obj = super().__new__(cls, seed)
        obj._size = size
        return obj

    def __len__(self) -> int:
        return self._size


class Understated(bytes):
    """Real content of `len(real)` bytes that reports a `len()` of 1: the store's caps must not trust it."""

    def __new__(cls, real: bytes) -> Understated:
        return super().__new__(cls, real)

    def __len__(self) -> int:
        return 1


@dataclass
class Rig:
    store: Any
    meta: Any
    blobs: Any
    clock: Clock
    safety: FakeSafety | None
    redactor: Redactor
    alerts: list[dict[str, Any]]
    scope: Any
    archive: Any = None  # a tilo_archive.RunArchive, or None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def lookup(self, scope: Any, archive_ref: str) -> str | None:
        """The store's archive_lookup: the text of this run's `tool_call` record, only for this Scope's org."""
        run, _, seq = archive_ref.partition("/")
        if self.archive is None or run != RUN or scope.org_id != ORG or scope.world_id != WORLD:
            return None
        for record in self.archive.records():
            if record["seq"] == int(seq) and record["kind"] == "tool_call":
                return str(record["payload"]["content"])
        return None

    def blob_key(self, ref: dict[str, Any]) -> str:
        base = f"orgs/{self.scope.org_id}/worlds/{self.scope.world_id}/artifacts/{ref['artifact_id']}"
        return f"{base}/v{ref['version']:06d}"

    def tamper(self, ref: dict[str, Any], data: bytes = b"tampered") -> None:
        self.blobs.delete(self.blob_key(ref))
        self.blobs.create(self.blob_key(ref), data)


def make_rig(
    archive_dir: Path | None = None,
    *,
    world_id: str = WORLD,
    safety: Any = "default",
    fail_unit: str | None = None,
) -> Rig:
    from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, Scope

    archive = None
    if archive_dir is not None:
        from tilo_archive import LocalDirStore, RunArchive

        archive = RunArchive(
            LocalDirStore(archive_dir),
            org_id=ORG,
            run_id=RUN,
            redactor=lambda p: p,
            clock=lambda: datetime(2026, 10, 5, 9, 0, 0, tzinfo=UTC),
        )
    meta, blobs = FailingMeta(MemoryMetaBackend(), fail_unit), MemoryBlobBackend()
    clock, redactor, alerts = Clock(), Redactor(), []
    screener = FakeSafety() if safety == "default" else safety
    rig = Rig(None, meta, blobs, clock, screener, redactor, alerts, Scope(org_id=ORG, world_id=world_id, owner=OWNER))
    rig.archive = archive
    rig.store = ArtifactStore(
        meta,
        blobs,
        clock=clock,
        redactor=redactor,
        archive_lookup=rig.lookup,
        alert_sink=alerts.append,
        screener=screener,
    )
    return rig


def add_tool_call(rig: Rig, text: str, ref: str = "https://example.com/note") -> str:
    """Puts one source-read record in the run's raw archive; returns its archive_ref (`<run_id>/<seq>`)."""
    payload = {"tool": "fetch", "source": {"kind": "web", "ref": ref}, "content": text}
    return str(rig.archive.append("tool_call", payload))


# --- outputs, outcomes, runners -------------------------------------------------------------------


def unit_output(content: bytes = ARTICLE, media_type: str = "text/markdown", **kw: Any) -> Any:
    from tilo_harness.executor import UnitOutput

    return UnitOutput(media_type=media_type, content=content, **kw)


def outcome(
    outputs: Any = (),
    *,
    refs: Any = (),
    credits: float | None = None,
    success: bool = True,
    summary: str = "Finished.",
) -> Any:
    """A UnitOutcome with `outputs`. With `credits`, a subclass carrying them (like tilo_api's MeteredOutcome)."""
    from tilo_harness.executor import UnitOutcome

    kwargs: dict[str, Any] = {
        "success": success,
        "summary": summary,
        "outputs": tuple(outputs),
        "artifact_refs": tuple(refs),
    }
    if credits is None:
        return UnitOutcome(**kwargs)

    @dataclass(frozen=True)
    class Metered(UnitOutcome):
        credits: float = 0.0

    return Metered(**kwargs, credits=credits)


class OutputRunner:
    """A UnitRunner double. `script[unit_id]` is a UnitOutcome or `callable(unit, context, events) -> UnitOutcome`,
    `events()` being the world's stream so far (so a later unit can name what an earlier one made)."""

    def __init__(self, script: dict[str, Any], events: Callable[[], list[dict[str, Any]]] | None = None) -> None:
        self.script, self.events = script, events or (lambda: [])
        self.ran: list[str] = []

    async def run(self, unit: dict[str, Any], context: Any) -> Any:
        self.ran.append(unit["id"])
        await asyncio.sleep(0)
        step = self.script[unit["id"]]
        return step(unit, context, self.events()) if callable(step) else step


@dataclass
class Ran:
    world_id: str
    rig: Rig
    writer: Any
    store: Any  # the harness MemoryStore of events
    result: Any
    layout: dict[str, Any]
    workers: dict[str, str]  # unit id -> its worker agent
    runner: Any

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.store.read_events(ORG, self.world_id)

    def of(self, *types: str, actor: str | None = None) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] in types and (actor is None or e["actor"] == actor)]

    def artifact_events_of(self, unit_id: str) -> list[dict[str, Any]]:
        worker = self.workers[unit_id]
        return [e for e in self.events if e["type"].startswith("artifact.") and e["actor"] == worker]


def run_units(
    tmp_path: Path,
    script: dict[str, Any],
    *,
    depends: dict[str, list[str]] | None = None,
    skills: dict[str, list[str]] | None = None,
    rig: Rig | None = None,
    with_store: bool = True,
    with_archive: bool = False,
    world_id: str = WORLD,
    verifier: Any = None,
    runner: Any = None,
    config_overrides: dict[str, Any] | None = None,
) -> Ran:
    """Runs one plan with a unit per key of `script` (worker A_s<i> for the i-th), all in district D1."""
    from tilo_harness.executor import run_plan

    depends, skills = depends or {}, skills or {}
    unit_ids = list(script)
    specialists = [f"A_s{i}" for i in range(len(unit_ids))]
    extra = [{"id": verifier.agent_id, "rank": "verifier"}] if verifier is not None else None
    layout = build_layout(
        world_id=world_id,
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": specialists, "unit_ids": unit_ids}],
        extra_agents=extra,
    )
    plan = build_plan(
        [build_unit(uid, depends_on=depends.get(uid), skills=skills.get(uid), district="D1") for uid in unit_ids]
    )
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml", **(config_overrides or {})))
    registry = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id=world_id)
    rig = rig or make_rig(tmp_path / "archive" if with_archive else None, world_id=world_id)
    runner = runner or OutputRunner(script, lambda: store.read_events(ORG, world_id))
    kwargs: dict[str, Any] = {"verifier": verifier} if verifier is not None else {}
    if with_store:
        kwargs |= {"artifacts": rig.store, "scope": rig.scope, "redact": rig.redactor}
        if rig.archive is not None:
            kwargs["archive"] = rig.archive
    result = asyncio.run(
        asyncio.wait_for(
            run_plan(plan, layout, writer=writer, config=config, skills=registry, runner=runner, **kwargs), 30
        )
    )
    return Ran(world_id, rig, writer, store, result, layout, dict(zip(unit_ids, specialists, strict=True)), runner)


def run_in_scratch(script: dict[str, Any], **kw: Any) -> Ran:
    """`run_units` in a throwaway directory (for property tests, which cannot take a function-scoped fixture)."""
    with tempfile.TemporaryDirectory() as tmp:
        return run_units(Path(tmp), script, **kw)


def seed_corrupt(rig: Rig, unit_id: str, worker: str, attempts: range) -> list[dict[str, Any]]:
    """A version already stored under each attempt's idempotency key of `unit_id` output 0, its blob then altered,
    and the clock moved past the store's GRACE: a restart finds a corrupt blob under that key (AR-01, AR-05)."""
    from tilo_memory.artifacts import NewVersion, Origin

    refs = []
    for attempt in attempts:
        stored = rig.store.put(
            rig.scope,
            NewVersion(
                media_type="text/markdown",
                content=b"seed " + str(attempt).encode(),
                run_id=RUN,
                origin=Origin(kind="unit", unit=unit_id, agent=worker),
                idempotency_key=f"{RUN}:{unit_id}:{attempt}:0",
            ),
        )
        rig.tamper(stored.ref)
        refs.append(stored.ref)
    rig.clock.advance(timedelta(minutes=10))
    return refs


def created_ref(events: list[dict[str, Any]], actor: str, index: int = 0) -> dict[str, Any]:
    """The ref of the `index`-th artifact.created the worker `actor` wrote."""
    mine = [e for e in events if e["type"] == "artifact.created" and e["actor"] == actor]
    return dict(mine[index]["data"]["artifact"])


def dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)
