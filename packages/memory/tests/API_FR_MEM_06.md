# FR-MEM-06 (with FR-MEM-12, FR-AGT-10 idempotency, FR-MEM-09 retention): public API pinned by the tests (overridable)

Acceptance tests (PRD 13.2, 13.4, 15.1): FR-MEM-06 "Restore v2: v3 is identical to v2" (a restore is a new version);
FR-MEM-12 the artifact contract and store; FR-AGT-10 a restarted unit gets its version back (AR-05); FR-MEM-09 the
`gcs_artifacts` retention adapter (AR-08). Sources: `docs/adr/0018-artifact-output-and-store.md` sections 1 to 4 and
the T1 notes, `contracts/artifact.rules.md` AR-01 to AR-08, `contracts/artifact.schema.json`,
`contracts/manifest.rules.md` MF-01 to MF-06, `packages/memory/src/tilo_memory/{retention,erasure}.py`.

These are the tests' assumptions, and the builder may override them. If a name or shape below changes, update the tests
in the same PR and say so in the review. The tests import only what is listed here. No contract change is needed.
New module: `packages/memory/src/tilo_memory/artifacts.py` (a package `artifacts/` is fine). Runtime dependencies:
stdlib, `jsonschema`, `referencing` and `tilo-contracts` only. Tests: `uv run pytest packages/memory/tests -q -k FR_MEM_06`.
Fakes and helpers live in `packages/memory/tests/_artifact_testlib.py`.

## Names

```python
from tilo_memory.artifacts import (
    ArtifactStore,
    Scope,
    NewVersion,
    Origin,
    StoredVersion,
    ArtifactError,
    ArtifactNotFound,
    ArtifactCorrupt,
    ArtifactRefused,
    MemoryMetaBackend,
    MemoryBlobBackend,
    LocalDirBlobBackend,
    validate_record,
    validate_revision,
)
```

- `class ArtifactError(Exception)`; `ArtifactNotFound(ArtifactError, LookupError)`; `ArtifactCorrupt(ArtifactError)`;
  `ArtifactRefused(ArtifactError, ValueError)`. Messages hold ids and rule names only, never content or secrets.
- `Scope(org_id, world_id, owner)`: frozen dataclass from the run, never from a request. Each id must `fullmatch` its
  `common.schema.json` pattern (`org_`, `w_`, `u_` prefixes). A bad id raises `ValueError` (on construction or on the
  first store call, either) before any backend call or key.
- A ref is the contract's `artifact_ref` as a plain dict `{"artifact_id": "art_...", "version": 1}` (a `label` key is
  allowed and ignored). A malformed ref (id not a full match, `/`, trailing newline; version below 1) raises `ValueError`
  before any backend call. `Origin(kind, unit=None, agent=None)`: frozen dataclass, `kind` in `unit render upload restore`.
- `NewVersion(media_type, content, run_id, origin, sources=(), idempotency_key=None, parent=None, label=None)`: frozen
  dataclass. `sources` are `{"id": slug, "archive_ref": "<run_id>/<seq>"}` dicts. `parent` is a ref (the earlier version
  this one continues; `None` mints a new `art_<ULID>` id). There is no field for `artifact_id`, `version`, `screening`,
  `redacted` or `content_sha256`: the store sets those (a keyword for them is a `TypeError`).
- `StoredVersion`: frozen dataclass with `.record` (the `ArtifactVersion` dict, a fresh copy on each access), `.ref`
  (`{"artifact_id", "version"}`), `.artifact_id`, `.version`. Equal records compare equal.

## `ArtifactStore`

```python
ArtifactStore(meta, blobs, *, clock, redactor, archive_lookup, alert_sink,
              screener=None, hasher=None, record_validator=None, new_id=None)
```
- `clock() -> aware datetime` (all times in records are UTC with exactly three fractional digits, `...000Z`).
  `redactor`, `clock`, `archive_lookup` and `alert_sink` are required keywords (a missing one is a `TypeError`: nothing
  is stored unredacted or unscreened by omission). `screener` may be `None`.
- `redactor(text: str) -> str`: the shared secret redactor. May raise.
- `screener.check(text, *, content=None, mime_type=None) -> {"flagged": bool, "reason": str | None}`: same shape as
  `tilo_providers.SafetyProvider.check`. For text and JSON the store calls `check(<stored bytes decoded as UTF-8>)`; for a
  file it calls `check("", content=<stored bytes>, mime_type=<media type>)`. It may raise (error, timeout). `screened_at`
  is `clock()` read right after the verdict returns. Anything but a dict with a bool `flagged` is treated as no verdict.
- `archive_lookup(scope, archive_ref) -> str | None`: the raw-archive record's text, or `None` when the archive holds no
  such record for that Scope's org and world (the injected function owns the run-to-world check). Every archive read the
  store makes passes the version's own Scope (AR-03).
- `alert_sink(alert: dict)`: called once per failed read with
  `{"type": "alert.raised", "world_id", "run_id", "artifact": <ref>, "summary": str, "data": {"alert_id": <ULID>, "card_id": None}}`
  (`data` validates against `events/data/alert.raised.schema.json`; the harness adds the envelope). No content in it.
- `hasher(data: bytes) -> str` (lower-case hex SHA-256; default `hashlib.sha256`). Used for every hash the store takes, on
  put and on read. Caps and kinds are checked before it is ever called.
- `record_validator(record: dict) -> None` (default `validate_record`; raises on an invalid record). Called with the full
  `ArtifactVersion` dict before it is stored, for a put and for a restore; a raise refuses the call and stores nothing.
- `new_id() -> str` (default: `art_` plus a ULID). Tests never rely on it.

```python
def put(self, scope: Scope, new: NewVersion) -> StoredVersion
def head(self, scope, ref) -> StoredVersion | None              # metadata only: reads no blob
def read(self, scope, ref) -> bytes                              # re-hashes; ArtifactNotFound / ArtifactCorrupt
def versions(self, scope, artifact_id: str) -> list[StoredVersion]   # ascending; ArtifactNotFound when none in scope
def restore(self, scope, ref, *, by: Origin) -> StoredVersion    # by.kind must be "restore" (else ArtifactRefused)
def add_manifest(self, scope, ref, manifest: dict, *, stage: str, cause: str | None) -> int
def manifest(self, scope, ref) -> dict                           # the Manifest document of the latest revision
def manifest_revisions(self, scope, ref) -> list[dict]           # [{"n", "stage", "cause", "manifest"}], ascending n
def source_texts(self, scope, ref) -> dict[str, str]             # {source id: archive text} through archive_lookup(scope, ...)
def retention(self) -> RetentionStore                            # FR-MEM-09 adapter
```
- Absent means: no version of that ref in that Scope (never existed, or another org, world or owner). `head` returns
  `None`; `read`, `versions`, `restore`, `add_manifest`, `manifest`, `manifest_revisions`, `source_texts` and a `put` whose
  `parent` is absent raise `ArtifactNotFound`, with the same type and message as for an id that never existed.
  `manifest` and `manifest_revisions` with no revision yet also raise `ArtifactNotFound`. A source record that reads as
  absent (through the Scope) raises `ArtifactNotFound` from `source_texts`.
- Every refusal of a put, restore or add_manifest raises `ArtifactRefused` (a `ValueError`) and stores nothing: no blob,
  no record, no manifest revision, no version number or idempotency key used up.
- `put`: order is shape of ids, kinds and caps (no hashing), idempotency lookup (inside the Scope), redactor (text and
  JSON only), hash and screen the stored bytes, schema validation, create blob (create-only) then record, then
  `created_at = clock()`. The record's `owner`, `org_id`, `world_id` come from the Scope, `run_id` from `new`. A put
  whose `idempotency_key` already names a version in the Scope returns that stored version unchanged (the first stored
  bytes win, nothing is rewritten, no new version). The next version of `parent` is the highest version of that id plus
  one, with `parents == [parent]`; a first version has `parents == []`.
- `restore`: reads the copied version through the AR-01 re-hash, then stores a new version (highest + 1) with the copied
  bytes, `media_type`, `size_bytes`, `content_sha256`, `sources`, `screening`, `screened_at`, `redacted` and `run_id`;
  `parents == [ref]`, `origin == by`, `idempotency_key is None`, `created_at == clock()`. The redactor and screener are
  not called. It takes no `sources` argument. The world's 200,000,000 byte total counts the copy.
- World total (AR-04): the sum of `size_bytes` over all versions of the Scope's org and world, at most 200,000,000.
- `add_manifest`: validates the revision against `artifact.schema.json#/$defs/manifest_revision`
  (`validate_revision`), the manifest against MF-01, MF-02, MF-03 and MF-06 (the injected redactor, fail closed), that
  `manifest["artifact"]` is this ref and `manifest["content_sha256"]` is the record's, and that every record source id is
  a manifest source id (AR-06, "name sources of the manifest"). A restore's manifest must list the restored version in
  `parents`. Returns `n` (1, 2, 3, ... no gaps, atomic under threads). MF-04 and MF-05 need the run's events and skill
  pins and are the caller's (`build_manifest`), not tested here.
- `source_texts` is the Verifier load's archive half (ADR-0018 section 5).

## Validation helpers

`validate_record(record: dict) -> None` validates an `ArtifactVersion` against `contracts/artifact.schema.json` with
`jsonschema` (Draft 2020-12 and a `referencing` registry of all of `contracts/`), not only the generated pydantic model,
and raises on failure (`jsonschema.ValidationError` or `ArtifactRefused`). `validate_revision(revision: dict)` does the same
for `#/$defs/manifest_revision`.

## Backends

```python
class MetaBackend(Protocol):                    # create-only documents, atomic next version
    def create(self, path: str, doc: dict) -> None      # FileExistsError if the path exists; never overwrites
    def get(self, path: str) -> dict | None
    def delete(self, path: str) -> None                 # idempotent
    def paths(self, prefix: str = "") -> list[str]
    # plus whatever atomic "next version of this artifact" operation the store needs (builder's choice)
class BlobBackend(Protocol):
    def create(self, key: str, data: bytes) -> None     # FileExistsError if the key exists; never overwrites
    def read(self, key: str) -> bytes                   # FileNotFoundError when absent
    def delete(self, key: str) -> None                  # idempotent; removes every generation of the key
    def keys(self, prefix: str = "") -> list[str]
```
- `MemoryMetaBackend()`, `MemoryBlobBackend()`, `LocalDirBlobBackend(root: Path)` (`.root`; creates parent directories
  lazily on the first `create`, writes with `open(path, "xb")`, refuses a key with `..`, a leading `/`, a backslash, a
  drive or an empty segment with `ValueError`). `LocalDirBlobBackend.from_env(environ)` reads `TILO_ARTIFACT_DIR`
  (default `.tilo/artifacts/`) and touches no disk.
- Record documents (ADR-0018 section 2): `orgs/{org}/worlds/{world}/artifacts/{artifact_id}/versions/{version:06d}`;
  manifest revisions `.../versions/{version:06d}/manifests/{n:04d}`; blob key
  `orgs/{org}/worlds/{world}/artifacts/{artifact_id}/v{version:06d}`. Keys and paths are built only from ids that
  already passed the full-match check.
- The tests also pass their own `BlobBackend` that keeps the object it is given as it is (`SizeOnlyBlobs`), so a size-only
  `bytes` subclass whose `len()` is large needs no real memory. The store must take `len(content)` of the object it
  is given for every cap, before copying or hashing it.
- Tests wrap `meta` and `blobs` in a recording proxy that forwards attribute access, so the backends are used only through
  the methods above.

## Retention adapter (AR-08, FR-MEM-09)

`store.retention()` is a `RetentionStore` with one record per stored version: `entity == "artifact"`, `record_id` unique
in the store and built from ids only, `created_at` the record's `created_at` (aware UTC), `user_id == owner`.
`delete(record_id)` is idempotent and removes that version's blob (every generation), its record and its manifest
revisions; other versions stay. Registered as `gcs_artifacts` in the erasure registry (`REQUIRED_STORES`).

## Assumptions the tests make where the contract is silent

Each is marked `# ASSUMPTION` in the test that makes it where it is a single test.

1. A repeated idempotency key returns the first stored version even when the new bytes differ (FR-AGT-10: restart).
2. A record whose blob is missing or altered is `ArtifactCorrupt` (with an alert), never `ArtifactNotFound`.
3. A restore's `run_id` is the copied version's, `by.kind` must be `restore`, and the copy counts toward the world cap.
4. `put(parent=ref)` makes highest + 1 with `parents == [ref]`, so a parent may be any earlier version of the id.
5. `versions`, `manifest` and `manifest_revisions` raise `ArtifactNotFound` (never return `[]`) when nothing is in scope.
6. AR-06 "`sources[].id` ... name sources of the manifest" is read as: every record source id is a manifest source id.
   A restore's manifest must list the restored version in `parents` (MF-02); other manifest parents are earlier
   versions of the same artifact.
7. A `cause` (and every id) is matched whole: a trailing newline is refused even though the schema's `$` would let it by.
8. After the last version of an artifact is deleted by the retention adapter the store keeps no document about it
   (no index, counter or idempotency entry), so `MetaBackend.paths()` is empty (FR-MEM-09 "removes their data").
9. Retention is one record per version (a 91-day-old v1 is purged while a 31-day-old v2 stays).
10. Screening a file the provider cannot screen (it raises) is `unscreened`, like any other provider error.
