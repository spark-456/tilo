"""Per-account grounding: the chunk store (ADR-0049 decision 7, RT-01 to RT-08, contracts/retrieval_chunk.rules.md).

Passages of records a person may read are embedded and stored at `orgs/{org}/chunks/{id}`; `search` returns the nearest
few to that person only. Rules that keep it safe:
- `search(org, caller, ...)` refuses a blank, wildcard or foreign caller before any query. The readable scopes (the
  caller's own chunks and each team they are a current member of, from `SourceRules`) are filters INSIDE each vector
  query, never applied after ranking; hits are merged by score, then every hit is re-checked against its source as the
  source's own read rule says now (`SourceRules.readable`) and a failure is dropped without a trace.
- Only text the caller's code already screened reaches `index`; text is cleaned, secret-redacted and screened again
  (a flagged or unscreenable text is never stored) before it is embedded. A chunk dies with its source version.
- No model call here: `Embedder` is injected (the API wires `packages/providers`, the `embed` role; tests a fake).
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from .retention import USER_ID_PATTERN

MAX_TEAMS = 10  # RT-03: at most this many team scopes per query
_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}")
_TEAM = re.compile(r"tm_[0-9a-z_]{1,48}")
_SOURCE_ID = {
    "deliverable": re.compile(r"art_[0-9A-Za-z_]{1,48}"),
    "upload": re.compile(r"art_[0-9A-Za-z_]{1,48}"),
    "minutes": re.compile(r"mt_[0-9A-Za-z_]{1,48}"),
    "pin": re.compile(r"pb_[0-9A-Za-z_]{1,48}"),
    "memory_item": re.compile(r"mem_[0-9A-Za-z_]{1,48}"),
}
_NO_TEAM = frozenset({"upload", "minutes", "memory_item"})  # RT-02 / schema: these are never team chunks
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class ChunkError(ValueError):
    """A request the store refuses (bad ids, a team on a personal kind). The message never holds passage text."""


class Embedder(Protocol):
    profile: str
    dimensions: int

    def embed(self, texts: Sequence[str], task: Literal["document", "query"]) -> list[list[float]]: ...


class SourceRules(Protocol):
    """What the stores know and the store must not: people, teams, shares, pins, artifacts (RT-02, RT-03, RT-07)."""

    def is_person(self, org_id: str, user_id: str) -> bool: ...
    def member_teams(self, org_id: str, user_id: str) -> Sequence[str]: ...  # current, accepted memberships only
    def readable(self, org_id: str, caller: str, chunk: Mapping[str, Any]) -> bool: ...  # the source's read rule now
    def gone(self, org_id: str, chunk: Mapping[str, Any]) -> bool: ...  # source deleted, or team scope lapsed


class ChunkBackend(Protocol):
    def put(self, org_id: str, doc: Mapping[str, Any]) -> None: ...  # `doc` holds `embedding`
    def delete(self, org_id: str, chunk_id: str) -> None: ...  # idempotent
    def for_source(self, org_id: str, kind: str, source_id: str) -> list[dict[str, Any]]: ...
    def count(self, org_id: str, field: str, value: str) -> int: ...
    def nearest(
        self, org_id: str, field: str, value: str, profile: str, vector: Sequence[float], limit: int
    ) -> list[tuple[float, dict[str, Any]]]: ...  # (dot product, doc without `embedding`), best first
    def scan(self, org_id: str) -> Iterator[dict[str, Any]]: ...  # every doc without `embedding`


@dataclass(frozen=True)
class ChunkConfig:  # config/memory.yaml `vector` and `embed` (RT-05)
    k: int = 5
    chunk_chars: int = 1200
    per_source: int = 200
    per_person: int = 2000
    batch_max: int = 64
    max_distance: float | None = None  # 1 - dot product; None keeps every hit that passes the re-check


@dataclass(frozen=True)
class SourceDoc:
    """One source version, as the indexer hook hands it over: text from a record already stored and screened clean."""

    org_id: str
    owner: str
    team_id: str | None
    world_id: str | None
    kind: str
    source_id: str
    version: int | None
    label: str
    text: str
    expires_at: str | None = None


@dataclass(frozen=True)
class Hit:
    id: str
    source: dict[str, Any]
    label: str
    text: str
    score: float


def clean_text(text: str) -> str:
    """RT-08: control characters except line break and tab, format characters and line or paragraph separators go."""
    text = text.replace("\r\n", "\n")
    kept = (
        c
        for c in text
        if c in ("\n", "\t") or unicodedata.category(c) not in {"Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"}
    )
    return re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def clean_label(label: str) -> str:
    one_line = " ".join(clean_text(label).split())
    return one_line[:120].strip() or "Untitled"


def split(text: str, max_chars: int) -> list[str]:
    """Passages of at most `max_chars` on paragraph, then sentence, then word boundaries (RT-01)."""
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        for sentence in _SENTENCE_END.split(paragraph.strip()):
            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                cut = cut if cut > 0 else max_chars
                pieces.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                pieces.append(sentence)
    passages: list[str] = []
    for piece in pieces:
        if passages and len(passages[-1]) + 1 + len(piece) <= max_chars:
            passages[-1] += " " + piece
        else:
            passages.append(piece)
    return passages


def chunk_id(org_id: str, kind: str, source_id: str, version: int | None, position: int, profile: str) -> str:
    raw = "\0".join([org_id, kind, source_id, str(version), str(position), profile])
    return "ch_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ChunkStore:
    def __init__(
        self,
        backend: ChunkBackend,
        embedder: Embedder,
        rules: SourceRules,
        *,
        config: ChunkConfig = ChunkConfig(),
        screen: Callable[[str], bool] | None = None,  # True = flagged (the safety provider's verdict)
        redact: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._backend, self._embedder, self._rules, self._cfg = backend, embedder, rules, config
        self._screen, self._redact, self._clock = screen, redact, clock

    def index(self, doc: SourceDoc) -> int:
        """Replace the chunks of one source version; returns the passages now held. 0 for empty, flagged text."""
        self._check_doc(doc)
        text = clean_text(doc.text)
        text = clean_text(self._redact(text)) if self._redact is not None else text
        if not text or (self._screen is not None and self._screen(text)):  # an unscreenable text raises: not stored
            self.delete_for_source(doc.org_id, doc.kind, doc.source_id)
            return 0
        held = self._backend.for_source(doc.org_id, doc.kind, doc.source_id)
        others = self._backend.count(doc.org_id, "owner", doc.owner) - len(held)
        room = max(0, min(self._cfg.per_source, self._cfg.per_person - others))
        passages = split(text, self._cfg.chunk_chars)[:room]
        profile, dims = self._embedder.profile, self._embedder.dimensions
        by_id = {d["id"]: d for d in held}
        shas = [hashlib.sha256(p.encode()).hexdigest() for p in passages]
        ids = [chunk_id(doc.org_id, doc.kind, doc.source_id, doc.version, i, profile) for i in range(len(passages))]
        known = {d["text_sha256"]: d["embedding"] for d in held if d["embed_profile"] == profile}
        todo = [
            i
            for i, (cid, sha) in enumerate(zip(ids, shas, strict=True))
            if by_id.get(cid, {}).get("text_sha256") != sha
        ]
        fresh = [i for i in todo if shas[i] not in known]  # same text and profile: the stored vector is reused
        for start in range(0, len(fresh), self._cfg.batch_max):
            batch = fresh[start : start + self._cfg.batch_max]
            vectors = self._embedder.embed([passages[i] for i in batch], "document")
            if len(vectors) != len(batch) or any(not _valid(v, dims) for v in vectors):
                raise ChunkError("the embedder returned an unusable result")
            known.update({shas[i]: v for i, v in zip(batch, vectors, strict=True)})
        now = _iso(self._clock())
        for i in todo:
            record = {
                "id": ids[i], "org_id": doc.org_id, "owner": doc.owner, "team_id": doc.team_id,
                "world_id": doc.world_id, "label": clean_label(doc.label), "position": i, "text": passages[i],
                "source": {"kind": doc.kind, "id": doc.source_id, "version": doc.version},
                "text_sha256": shas[i], "embed_profile": profile, "dimensions": dims, "screening": "clean",
                "created_at": now, "expires_at": doc.expires_at,
            }  # fmt: skip
            self._backend.put(doc.org_id, {**record, "embedding": list(known[shas[i]])})
        for stale in set(by_id) - set(ids):  # the older versions and positions this version no longer has
            self._backend.delete(doc.org_id, stale)
        return len(passages)

    def search(self, org_id: str, caller: str, query: str, *, k: int | None = None) -> list[Hit]:
        """The nearest readable passages for `caller`, best first; ChunkError for a caller it will not query for."""
        if type(org_id) is not str or _ORG.fullmatch(org_id) is None:
            raise ChunkError("a valid org is required")
        if (
            type(caller) is not str
            or USER_ID_PATTERN.fullmatch(caller) is None
            or not self._rules.is_person(org_id, caller)
        ):
            raise ChunkError("a valid caller of this org is required")
        want = min(max(1, k or self._cfg.k), self._cfg.k)
        teams = [t for t in self._rules.member_teams(org_id, caller) if _TEAM.fullmatch(t)][:MAX_TEAMS]
        scopes = [("owner", caller), *(("team_id", t) for t in dict.fromkeys(teams))]
        scopes = [s for s in scopes if self._backend.count(org_id, *s) > 0]
        if not query.strip() or not scopes:
            return []  # RT-06: no query embedding when there is nothing to find
        vectors = self._embedder.embed([clean_text(query)], "query")
        if len(vectors) != 1 or not _valid(vectors[0], self._embedder.dimensions):
            raise ChunkError("the embedder returned an unusable result")
        found: dict[str, tuple[float, dict[str, Any]]] = {}
        for field, value in scopes:  # one query per readable scope, the filter inside it (RT-03)
            for score, doc in self._backend.nearest(
                org_id, field, value, self._embedder.profile, vectors[0], min(want * 3, 20)
            ):
                if doc.get("org_id") == org_id and doc.get(field) == value and doc.get("id") not in found:
                    found[doc["id"]] = (score, doc)
        hits: list[Hit] = []
        for score, doc in sorted(found.values(), key=lambda pair: -pair[0]):
            if self._cfg.max_distance is not None and 1 - score > self._cfg.max_distance:
                continue
            if self._allowed(org_id, caller, doc):
                hits.append(Hit(doc["id"], dict(doc["source"]), doc["label"], doc["text"], score))
            if len(hits) == want:
                break
        return hits

    def _allowed(self, org_id: str, caller: str, doc: Mapping[str, Any]) -> bool:
        try:
            return bool(self._rules.readable(org_id, caller, doc))
        except Exception:
            return False  # fail closed: a hit that cannot be re-checked is dropped

    def delete_for_source(self, org_id: str, kind: str, source_id: str) -> int:
        docs = self._backend.for_source(org_id, kind, source_id)
        for d in docs:
            self._backend.delete(org_id, d["id"])
        return len(docs)

    def sweep(self, org_id: str) -> int:
        """RT-07: delete every chunk whose source is gone or whose team scope lapsed, or whose retention has passed."""
        now, removed = _iso(self._clock()), 0
        for doc in list(self._backend.scan(org_id)):
            expired = doc.get("expires_at") is not None and doc["expires_at"] <= now
            if expired or self._rules.gone(org_id, doc):
                self._backend.delete(org_id, doc["id"])
                removed += 1
        return removed

    def _check_doc(self, doc: SourceDoc) -> None:
        if (
            _ORG.fullmatch(doc.org_id) is None
            or USER_ID_PATTERN.fullmatch(doc.owner) is None
            or doc.kind not in _SOURCE_ID
            or _SOURCE_ID[doc.kind].fullmatch(doc.source_id) is None
            or (doc.kind in ("pin", "memory_item")) != (doc.version is None)
        ):
            raise ChunkError("not a valid source")
        if doc.team_id is not None and (doc.kind in _NO_TEAM or _TEAM.fullmatch(doc.team_id) is None):
            raise ChunkError("this kind of source is never a team chunk")  # RT-02
        if doc.team_id is not None and doc.kind == "deliverable" and doc.world_id is None:
            raise ChunkError("a team deliverable names its world")


def _valid(vector: Sequence[float], dims: int) -> bool:
    return len(vector) == dims and all(isinstance(x, int | float) and math.isfinite(x) for x in vector)


class ChunkRetention:
    """FR-MEM-09: the chunk collection as an erasure-registry store (`records`, `delete`), owner = `user_id`."""

    def __init__(self, backend: ChunkBackend, org_id: str) -> None:
        self._backend, self._org = backend, org_id

    def records(self) -> Iterable[Any]:
        for doc in self._backend.scan(self._org):
            yield _Record(doc["id"], datetime.fromisoformat(doc["created_at"].replace("Z", "+00:00")), doc["owner"])

    def delete(self, record_id: str) -> None:
        self._backend.delete(self._org, record_id)


@dataclass(frozen=True)
class _Record:
    record_id: str
    created_at: datetime
    user_id: str | None
    entity: str = "chunk"
