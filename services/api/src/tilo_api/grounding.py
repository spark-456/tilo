"""Per-account grounding in tilo-api (ADR-0049 decision 7, RT-01 to RT-10): the stores' answer to "may this person still
read this source", the embed role behind the SEC-16 meter, and the indexer hooks (pins, confirmed minutes, a run's
deliverables, uploads). Off unless `TILO_RETRIEVAL=1`. Every hook is best effort: a failure is logged by type and never
changes the request that triggered it (RT-06). Notes (MI-02) index through `index_note` once the memory store exists.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Collection, Mapping
from typing import Any

from tilo_memory.artifacts import ArtifactError, Scope
from tilo_memory.chunks import ChunkBackend, ChunkConfig, ChunkError, ChunkStore, SourceDoc
from tilo_memory.chunks_backends import FirestoreChunkBackend, MemoryChunkBackend
from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores
from tilo_people.world_share import in_force, share_id
from tilo_providers.interfaces import EmbedRequest, EmbedResponse
from tilo_providers.memory_config import load_memory_config

from tilo_api import deps, events
from tilo_api.access import enforced

logger = logging.getLogger("tilo_api.grounding")
_TEXT_TYPES = ("text/", "application/json")
_MEMORY = MemoryChunkBackend()  # dev and replay: one process-wide store (demo sessions index nothing)


def enabled() -> bool:
    return os.environ.get("TILO_RETRIEVAL") == "1"


def _backend() -> ChunkBackend:
    """Firestore (the process's one guarded client, `prod.firestore_client`) for `TILO_CHUNKS_STORE=firestore`, else
    the process-wide in-memory store. A client that cannot be opened raises: the caller's hook logs it and skips."""
    project = os.environ.get("TILO_FIRESTORE_PROJECT") or ""
    if os.environ.get("TILO_CHUNKS_STORE") != "firestore" or not project:
        if enforced():  # deployed: a per-process dict would lose chunks on every instance change, so grounding is off
            raise RuntimeError("chunks need TILO_CHUNKS_STORE=firestore when deployed")
        return _MEMORY
    from tilo_api import prod  # noqa: PLC0415

    return FirestoreChunkBackend(prod.firestore_client(project))


class RouterEmbedder:
    """The `embed` role through the Router (PL-01); a MeteredRouter makes each call a SEC-16 unit on the uid ledger."""

    def __init__(self, router: Any, profile: str, dimensions: int, batch_max: int, budget: float | None = None) -> None:
        self._router, self.profile, self.dimensions, self._batch = router, profile, dimensions, batch_max
        self.budget = budget  # what is left of the caller's credit budget; it falls by each call's price (PL-03)

    def embed(self, texts: Any, task: Any) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            request = EmbedRequest(texts=list(texts[i : i + self._batch]), task=task, dimensions=self.dimensions)
            call = getattr(self._router, "metered_embed", None) or self._router.embed  # a MeteredRouter's unit, SEC-16
            result = call("embed", request, **({} if self.budget is None else {"budget": self.budget}))
            if self.budget is not None and result.budget is not None:
                self.budget = result.budget
            answer = result.embedding
            if not isinstance(answer, EmbedResponse) or answer.profile_id != self.profile:
                raise ChunkError("the embed role answered with another profile")  # vectors are never mixed (RT-05)
            out.extend(answer.vectors)
        return out


class ApiSourceRules:
    """RT-03 / RT-07: the source's own read rule, asked of the stores at the moment of the query."""

    def __init__(
        self, people: PeopleStores, worlds: Any, artifacts: Any, notes: Callable[[str, str, str], bool] | None = None
    ) -> None:
        self._people, self._worlds, self._artifacts, self._notes = people, worlds, artifacts, notes

    def _directory(self, org_id: str) -> Directory:
        return Directory.of(s.record for s in self._people.persons.list(org_id))

    def is_person(self, org_id: str, user_id: str) -> bool:
        return self._people.persons.get(org_id, user_id) is not None

    def member_teams(self, org_id: str, user_id: str) -> list[str]:
        now, directory = events.now(), self._directory(org_id)
        person = directory.record(user_id)
        found = [
            m["team"] for m in (person or {}).get("memberships", []) if directory.is_member(user_id, m["team"], now)
        ]
        return list(dict.fromkeys(found))

    def readable(self, org_id: str, caller: str, chunk: Mapping[str, Any]) -> bool:
        if chunk["org_id"] != org_id:
            return False
        exists, team_ok = self._state(org_id, chunk)
        team = chunk["team_id"]
        if not exists:
            return False
        if caller == chunk["owner"]:
            return True  # the owner keeps their own source even when its team scope has lapsed
        return team is not None and team_ok and team in self.member_teams(org_id, caller)

    def gone(self, org_id: str, chunk: Mapping[str, Any]) -> bool:
        try:
            return not all(
                self._state(org_id, chunk)
            )  # a lapsed team scope is deleted, then re-indexed on the owner's side
        except Exception:
            return False  # an unreadable store deletes nothing

    def _state(self, org_id: str, chunk: Mapping[str, Any]) -> tuple[bool, bool]:
        """(the source exists as indexed for its owner, its team scope is still the source's) now (RT-02/03)."""
        kind, sid, version = chunk["source"]["kind"], chunk["source"]["id"], chunk["source"]["version"]
        owner, team = chunk["owner"], chunk["team_id"]
        if kind == "memory_item":
            return team is None and self._notes is not None and self._notes(org_id, owner, sid), team is None
        if kind == "pin":
            stored = self._people.pins.get(org_id, sid)
            if stored is None or stored.record["status"] == "removed" or stored.record["flagged"]:
                return False, True
            pin, scope = stored.record, stored.record["scope"]
            if scope["kind"] == "team":  # moved to personal or to another team: the old team's chunks no longer match
                member = team is None or self._directory(org_id).is_member(owner, team, events.now())
                return pin["set_up_by"] == owner, team is None or (team == scope["team"] and member)
            return scope["user"] == owner, team is None
        if kind == "minutes":
            stored = self._people.meetings.get(org_id, sid)
            meeting = None if stored is None else stored.record
            ref = None if meeting is None else meeting["minutes"]
            return (
                meeting is not None and meeting["owner"] == owner and meeting["minutes_confirmed_by"] is not None
                and isinstance(ref, dict) and ref["version"] == version
            ), team is None  # fmt: skip
        world_id = chunk["world_id"]  # deliverable and upload
        world = self._worlds.load_world(world_id, settle=False) if isinstance(world_id, str) else None
        if world is None or world.owner != owner:
            return False, True
        try:
            head = self._artifacts.head(Scope(org_id, world_id, owner), {"artifact_id": sid, "version": version})
        except (ArtifactError, ValueError):
            return False, True
        if head is None or head.doc["screening"] != "clean":
            return False, True
        if team is None:
            return True, True
        share = self._people.world_shares.get(org_id, share_id(world_id, team))
        in_force_now = share is not None and in_force(share.record, owner, self._directory(org_id), events.now())
        return True, kind == "deliverable" and in_force_now


class Grounding:
    def __init__(self, store: ChunkStore, org_id: str, people: PeopleStores, worlds: Any, artifacts: Any) -> None:
        self.store, self._org, self._people, self._worlds, self._artifacts = store, org_id, people, worlds, artifacts

    @property
    def embedder(self) -> Any:
        return self.store.embedder

    def _safely(self, what: str, work: Callable[[], Any]) -> None:
        try:
            work()
        except Exception as exc:  # best effort: the request that triggered this never fails on it (RT-06)
            logger.warning("grounding %s not indexed (%s)", what, type(exc).__name__)

    def index_pin(self, pin: Mapping[str, Any]) -> None:
        def work() -> None:
            if pin["created_by"]["by"] != "person" or pin["flagged"] or pin["status"] == "removed":
                self.store.delete_for_source(self._org, "pin", pin["id"])
                return
            team = pin["scope"]["team"] if pin["scope"]["kind"] == "team" else None
            owner = pin["set_up_by"] if team else pin["scope"]["user"]
            text = "\n".join(t for t in (pin["title"], pin.get("body")) if t)
            self.store.index(SourceDoc(self._org, owner, team, None, "pin", pin["id"], None, pin["title"], text))

        self._safely("pin", work)

    def forget(self, kind: str, source_id: str) -> None:
        self._safely(kind, lambda: self.store.delete_for_source(self._org, kind, source_id))

    def index_minutes(self, meeting_id: str) -> None:
        def work() -> None:
            stored = self._people.meetings.get(self._org, meeting_id)
            meeting = None if stored is None else stored.record
            if meeting is None or meeting["minutes_confirmed_by"] is None or not meeting.get("world_id"):
                return
            ref, owner = meeting["minutes"], meeting["owner"]
            doc = json.loads(self._artifacts.read(Scope(self._org, meeting["world_id"], owner), ref))
            if doc.get("flagged"):
                self.store.delete_for_source(self._org, "minutes", meeting_id)
                return
            rows = [*doc["summary"], *doc["decisions"], *doc["action_items"]]
            text = "\n".join(r["text"] for r in rows if r.get("state") != "unverified")
            self.store.index(
                SourceDoc(self._org, owner, None, meeting["world_id"], "minutes", meeting_id, ref["version"],
                          meeting["title"], text, meeting.get("delete_minutes_after")),
            )  # fmt: skip

        self._safely("minutes", work)

    def index_deliverables(self, world_id: str, delivered: Collection[str]) -> int:
        """Run end (RT-09): the latest clean text version of each output the run delivered (`artifact.delivered`, not
        the intermediates of its units). Returns passages held."""
        held = [0]

        def work() -> None:
            world = self._worlds.load_world(world_id, settle=False)
            if world is None:
                return
            scope = Scope(self._org, world_id, world.owner)
            team = self._share_team(world_id, world.owner)
            for art_id in sorted(set(self._artifacts.artifact_ids(scope)) & set(delivered)):
                latest = self._artifacts.versions(scope, art_id)[-1]
                doc = latest.doc
                text = _text_of(doc, lambda: self._artifacts.read(scope, latest.ref))
                if doc["screening"] == "clean" and doc["origin"]["kind"] in ("unit", "render") and text:
                    held[0] += self.store.index(
                        SourceDoc(self._org, world.owner, team, world_id, "deliverable", art_id, latest.version,
                                  doc["origin"].get("unit") or "Result", text),
                    )  # fmt: skip

        self._safely("deliverables", work)
        return held[0]

    def _share_team(self, world_id: str, owner: str) -> str | None:
        directory, now = self._directory(), events.now()
        teams = sorted(
            s.record["team"] for s in self._people.world_shares.list(self._org, "world_id", world_id)
            if in_force(s.record, owner, directory, now)
        )  # fmt: skip
        return teams[0] if teams else None  # one chunk carries one team: the first sorted (follow-up: per-team copies)

    def _directory(self) -> Directory:
        return Directory.of(s.record for s in self._people.persons.list(self._org))

    def index_upload(self, owner: str, world_id: str, name: str, ref: Mapping[str, Any], text: str | None) -> None:
        if text:
            self._safely(
                "upload",
                lambda: self.store.index(
                    SourceDoc(
                        self._org, owner, None, world_id, "upload", ref["artifact_id"], ref["version"], name, text
                    )
                ),
            )

    def sweep(self) -> int:
        removed = [0]
        self._safely("sweep", lambda: removed.__setitem__(0, self.store.sweep(self._org)))
        return removed[0]


def _text_of(doc: Mapping[str, Any], read_bytes: Callable[[], bytes]) -> str:
    if not str(doc["media_type"]).startswith(_TEXT_TYPES):
        return ""
    raw = read_bytes().decode("utf-8", errors="replace")
    if doc["media_type"] != "application/json":
        return raw
    strings: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict | list):
            for item in value.values() if isinstance(value, dict) else value:
                walk(item)

    try:
        walk(json.loads(raw))
    except ValueError:
        return ""
    return "\n".join(strings)


def open_grounding(
    *,
    router: Any,
    budget: float | None = None,
    people: PeopleStores,
    worlds: Any,
    artifacts: Any,
    redact: Callable[[str], str],
    org_id: str = deps.ORG_ID,
) -> Grounding | None:
    """None unless `TILO_RETRIEVAL=1` and the embed role is configured. The caller supplies its request's own
    (metered) router, so a live embedding is a unit on the person's ledger."""
    if not enabled():
        return None
    try:
        embed_role = deps.providers_config().roles.get("embed")
        memory = load_memory_config()
        if embed_role is None:
            return None
        embedder = RouterEmbedder(router, embed_role.primary, memory.vector.dimensions, memory.embed.batch_max, budget)
        config = ChunkConfig(
            memory.vector.k, memory.vector.chunk_chars, memory.vector.per_source, memory.vector.per_person,
            memory.embed.batch_max, memory.vector.max_distance,
        )  # fmt: skip
        rules = ApiSourceRules(people, worlds, artifacts)
        store = ChunkStore(_backend(), embedder, rules, config=config, redact=redact)
        return Grounding(store, org_id, people, worlds, artifacts)
    except Exception as exc:
        logger.warning("grounding unavailable (%s)", type(exc).__name__)
        return None


Opener = Callable[[], Grounding | None]


def opener(
    request: Any, *, mode: Any = None, meter: Any = None, router: Any = None, budget: float | None = None
) -> Opener:
    """A lazy `Grounding` for this request: its own mode and SEC-16 meter, the seams as the app wires them (overrides
    included). None when off, for a demo session, or when any seam refuses; it never raises."""

    def seam(getter: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return request.app.dependency_overrides.get(getter, getter)(*args, **kwargs)

    def open_() -> Grounding | None:
        if not enabled():
            return None
        try:
            if deps._demo(request) is not None:
                return None
            switches = seam(deps.get_switches, request, deps.get_flag_store())
            use = mode if mode is not None else seam(deps.get_work_mode, request, switches)
            use_router = router if router is not None else seam(deps.get_router, use, request, switches, meter=meter)
            artifacts = seam(deps.get_artifact_store, request, mode=use)
            return open_grounding(
                router=use_router,
                budget=budget, people=seam(deps.get_people_stores, request), worlds=seam(deps.get_store, request),
                artifacts=artifacts, redact=seam(deps.get_redactor, request),
            )  # fmt: skip
        except Exception as exc:
            logger.warning("grounding not opened (%s)", type(exc).__name__)
            return None

    return open_


_swept_day = ""


def sweep_daily(request: Any, stamp: str) -> None:
    """RT-07: once per UTC day per process (the sweep is idempotent, so a second instance only repeats it), delete the
    chunks whose source is gone or whose team scope or retention lapsed. Replay mode: a sweep embeds nothing."""
    global _swept_day
    if not enabled() or stamp[:10] == _swept_day or (opened := opener(request, mode="replay")()) is None:
        return
    opened.sweep()
    _swept_day = stamp[:10]


def forget_for(request: Any, kind: str, source_id: str) -> None:
    """A source was deleted: drop its chunks. Replay mode, so a spent cap or switch never keeps a deleted source's
    passages; deleting embeds nothing."""
    if enabled() and (grounding := opener(request, mode="replay")()) is not None:
        grounding.forget(kind, source_id)


def after_pin(request: Any, pin_id: str) -> None:
    """Called once a pin write has committed: index the pin as it now is, or drop its chunks when it was removed."""
    if not enabled() or (current := opener(request, mode="replay")()) is None:
        return
    try:
        stored = current._people.pins.get(deps.ORG_ID, pin_id)
    except Exception as exc:
        logger.warning("grounding pin not read (%s)", type(exc).__name__)
        return
    if stored is None or stored.record["status"] == "removed":
        current.forget("pin", pin_id)
    elif (indexing := opener(request)()) is not None:  # the embedding needs this request's own mode and meter
        indexing.index_pin(stored.record)


def after_minutes(request: Any, meeting_id: str) -> None:
    if enabled() and (grounding := opener(request)()) is not None:
        grounding.index_minutes(meeting_id)
