# FR-MEM-10: run export bundle and re-import. Interface pinned by the tests (overridable)

Acceptance test (PRD 13.5): "Export and re-import a run; replay is identical" (Should). PRD 13.4 emergency fallback: "any
run can be exported as a bundle (events, archive, artifacts, manifest) for incident review". PRD 13.3: exports carry a
provenance manifest. Sources: `contracts/artifact.rules.md` AR-01 to AR-08, `contracts/manifest.rules.md` MF-06 ("again
before an export or a run bundle carries one out of Tilo"), AR-06 ("routes, exports and run bundles drop `sources`"),
`contracts/event.rules.md` EV-10 to EV-15, `packages/archive` (FR-MEM-04).

No contract change is needed: the bundle is a library format with no schema of its own in `contracts/` (none exists), so
its layout is pinned here and in the tests. If the user wants it frozen as a contract, that is a separate decision (see
the report). These are the tests' assumptions, and the builder may override them: if a name or shape below changes, update
the tests in the same PR and say so in the review.

Tests: `uv run pytest services/harness/tests -k FR_MEM_10` and
`uv run pytest packages/memory/tests -k FR_MEM_10` (run each file on its own; the harness run takes minutes).
Helpers: `services/harness/tests/bundle_support.py`. Fakes only: in-memory stores, `LocalDirStore` under `tmp_path`,
injected clocks, a fake redactor and screener, network blocked. The fake secret is assembled at runtime.

## New code

- `packages/memory/src/tilo_memory/artifacts.py`: `ArtifactStore.import_version(scope, record, content)`.
- `services/harness/src/tilo_harness/run_bundle.py` (the harness already depends on `tilo-archive` and `tilo-memory`).
- Possibly a read accessor on `WorldWriter` (for example `last_seq`), which is harness-internal and not a contract change:
  the importer must know whether the world is fresh before it writes anything.
- A route in tilo-api (S-22 "Settings: data, export") is out of this ticket; it would call these two functions.

## `tilo_memory.artifacts.ArtifactStore.import_version`

```python
def import_version(self, scope: Scope, record: dict, content: bytes) -> StoredVersion
```
Places one version from an untrusted bundle under the IMPORTER's Scope. `put` cannot do it: it mints the id, version,
hash, screening and `created_at` itself (AR-02, AR-07), so ids, versions and times would differ from what the run's events
name (EV-15). `record` is an `ArtifactVersion` as the bundle carries it. Rules (all `ArtifactRefused`, nothing stored: no
blob, no record, no version number used; scope errors are `ValueError` before any backend call):

- AR-03: `org_id`, `world_id`, `owner` are overwritten from `scope`. A record naming another scope is stored under
  `scope` and nothing is ever written under the named one. `sources` is set to `[]` (AR-06: they never leave Tilo).
- AR-01: `content_sha256` and `size_bytes` must match the bytes, hashed with the store's `hasher` over the object it was
  given and `len()` of that object (like `put`, so the tests' size-only `bytes` fake works).
- AR-04: kind and caps are checked before anything is hashed, the world's 200,000,000 bytes included (the import counts).
- Schema: the rewritten record validates against `artifact.schema.json` (the same `record_validator` as `put`).
- AR-02: version 1 has `parents == []`; version n continues one earlier version of the same id that the Scope already
  holds, with no gap. The same (id, version) with the same hash is the same version (returned, nothing written); with
  another hash it is refused and never overwritten.
- AR-05: `idempotency_key` is kept. A key held by another version in the Scope is refused. (ASSUMPTION, PRD silent: a
  restarted unit of the same run then still gets its imported version back.)
- AR-07: text and JSON must survive the store's redactor unchanged, else refused (never silently redacted: the bytes would
  no longer match the hash); a redactor error refuses. `redacted` is kept as it is.
- AR-07 screening is the importer's. A `clean` claim is never copied: the importer's screener judges the exact bytes (text
  and JSON through `check(text)`, files through `check("", content=, mime_type=)`), `screened_at` is that verdict's time; no
  screener, an error or an unreadable verdict gives `unscreened` with `screened_at` null. An `unscreened` or `flagged`
  claim is kept as it is, `screened_at` included, and the screener is not called for it.
- `created_at`, `origin`, `parents`, `run_id` and the rest are kept. The put-time check "screened_at not after created_at"
  does not apply to an import (the version is older than the verdict).
- A backend failure leaves nothing: a failed blob create deletes the blob and the record, as `put` does.

## `tilo_harness.run_bundle`

```python
BUNDLE_FORMAT = "tilo.run-bundle"; BUNDLE_VERSION = "1.0"

@dataclass(frozen=True)
class Limits:        # every field defaults to its DEFAULT_LIMITS value; Limits() == DEFAULT_LIMITS
    max_bundle_bytes: int; max_uncompressed_bytes: int; max_entries: int
    max_events: int; max_archive_records: int; max_versions: int
DEFAULT_LIMITS: Limits          # finite, positive ints; max_uncompressed_bytes >= 200_000_000 (a full world, AR-04)

class BundleError(Exception)
class BundleRefused(BundleError, ValueError)   # every refusal of a bundle or of an export; messages never hold content

@dataclass(frozen=True)
class ImportResult:
    run_id: str; org_id: str; world_id: str
    events: int; versions: int; manifest_revisions: int; archive_records: int
    already_imported: bool

def export_run(*, events: Sequence[dict], artifacts: ArtifactStore, scope: Scope, archive: RunArchive | None,
               run_id: str, redact: Callable[[str], str], clock: Callable[[], datetime],
               limits: Limits = DEFAULT_LIMITS) -> bytes

def import_run(bundle: bytes, *, writer: WorldWriter, artifacts: ArtifactStore, scope: Scope,
               archive_store: tilo_archive.archive.Store, redact: Callable[[str], str],
               expected_sha256: str | None = None, limits: Limits = DEFAULT_LIMITS) -> ImportResult
```

### Export

- `events` is the world's whole stream of this run (`store.read_events(org, world)`): non-empty, one `world_id`, every
  `run_id == run_id`, `seq` exactly 1..n with no gap and in order; else `BundleRefused`.
- The versions exported are exactly those the events record (`artifact.created`, `.versioned`, `.rolled_back`), read through
  `scope` (another world's, org's or owner's version reads as absent, so the export is refused); a missing version, a corrupt
  blob (AR-01) or a manifest read failure is `BundleRefused`. A version the store holds that no event recorded is not exported.
- `archive` is the run's `RunArchive` (or `None`: no records); a broken chain or another run's records is refused.
- Secrets: `redact` is run over every string of every event, every archive payload, every manifest and every text or JSON
  blob (decoded UTF-8). If it would change one, or raises, the export is refused and no bytes are produced (MF-06).
- Read-only on every store: no `exported` manifest revision, no event, no write. Two exports of the same run with the same
  clock are byte-identical (a deterministic ZIP: sorted names, fixed timestamps, canonical JSON). (Ambiguity, see report:
  AR-06 lists the stage `exported`, "when the version leaves Tilo"; a read-only export cannot add it.)
- `limits` apply to the bundle that would come out (`BundleRefused` over a cap, exactly at a cap passes).

### Bundle layout (a closed set of entries; ZIP, deflate)

```
bundle.json
events.jsonl                                        one event per line, as written by the world, in seq order
archive.jsonl                                       the run's raw-archive lines, verbatim (empty file when none)
artifacts/<artifact_id>/v<NNNNNN>/record.json       the store's record, `sources` emptied to []
artifacts/<artifact_id>/v<NNNNNN>/content           the stored bytes
artifacts/<artifact_id>/v<NNNNNN>/manifests.json    the manifest revisions, ascending n (a JSON array, [] when none)
```
`bundle.json` (canonical JSON): `{"format": "tilo.run-bundle", "version": "1.0", "run_id", "exported_at" (RFC 3339, three
fractional digits, from `clock`), "counts": {"events", "archive_records", "versions", "manifest_revisions"},
"archive_head": {"seq", "hash"} (seq 0 and 64 zeros when there are no records), "entries": {<every other entry name>:
<lower-case SHA-256 hex of its bytes>}}`. It holds no scope identity. Events keep the source `world_id` and records keep the
source `org_id`, `world_id` and `owner` as stored; the importer rewrites them.

### Import: untrusted input, validated in full before the first write

1. Not a ZIP, truncated, or any ZIP error: `BundleRefused` (never `BadZipFile`, `zlib.error`, `KeyError`,
   `UnicodeDecodeError`, `RecursionError`). Entry names must match the closed set above exactly (artifact ids and the
   six-digit version fully matched); `..`, absolute paths, backslashes, drive letters, NUL, empty segments, leading or
   trailing space or newline, directory, symlink and device entries, duplicate names (even identical bytes), and unlisted
   entries are refused. Sizes are read from the central directory and bounded (`max_uncompressed_bytes` is checked against
   the declared total before anything is inflated; a 64 MB zero run that deflates to 64 KB is refused without allocating it).
2. Caps (`Limits`): bundle bytes, uncompressed total, entries, events, archive records, versions. Exactly at a cap passes.
3. JSON: bad UTF-8, a non-object where an object is required, NaN or Infinity, and nesting that exhausts the stack are
   `BundleRefused`. `bundle.json` must have every key with the right type; `format` and `version` must be exactly the two
   constants (another format or version is refused; `1.0` is the only version now); `run_id` matches the run-id pattern.
4. Integrity: `entries` lists exactly the other entries, each hash matches; `counts` equal the real counts; the archive
   chain verifies (`tilo_archive.verify_chain`) with `archive_head` as the expected head and every record's `run_id` the
   bundle's; events are one run (`run_id` equals `bundle.json`'s) of one world, non-empty, `seq` 1..n in order; every version
   directory has all three entries; the set of versions equals the set the events record; each `artifact.created`'s
   `content_sha256` equals its record's; manifest revisions are numbered 1..k.
5. `expected_sha256` (optional, lower-case hex, from a trusted side channel) must equal the SHA-256 of the bundle bytes. It is
   the only defence against a forger who edits events and recomputes the index (events are not chained): see the report.
6. Secrets: `redact` is run over every event string, archive payload, manifest string and text or JSON blob. Anything it
   would change, or an error, refuses the whole bundle; the message never repeats the string.
7. Scope and world: `scope.org_id` and `scope.world_id` must equal `writer.org_id` and `writer.world_id`, else refused. The
   world must be fresh, or already hold exactly a prefix of this run's events (retargeted): any other event refuses.
   Importing the world's own run again is a no-op.
8. A dry run: every version and manifest revision through a scratch store with the same rules, and every event through a
   scratch `WorldWriter` with the importer's layout (EV-01 to EV-15: an unknown actor, district or `vis`, a skipped
   version, a duplicate id, an unknown cause, a schema error are all refusals found before any write).

### Import: writes, in this order

1. Artifact versions through `import_version` in ascending version order, then their manifest revisions through
   `add_manifest(stage, cause)` (so revisions get `n` 1..k). A failure rolls back what this call stored (via
   `store.retention().delete`) and raises (a `BundleRefused` for a refusal, the backend's error or a `BundleError` for an outage).
2. The archive lines, verbatim (`archive_store.append_line(scope.org_id, run_id, line)`, so they land under the importer's
   org). Lines already stored must be an identical prefix of the bundle's chain (then the rest is appended); another chain
   already stored for that org and run refuses the import and is left untouched. A failure rolls the artifacts back.
3. The events, last, `writer.append(dict(event, world_id=writer.world_id))` one by one (an identical resend is a no-op,
   FR-HIL-07). The writer's own redaction builds the per-district views; nothing about views is in the bundle.

So a refusal found in validation writes nothing in any store; an outage in step 1 or 2 leaves no event and no readable
artifact; an outage in step 3 leaves a prefix of the replay (an append-only stream cannot be un-written) that a retry of
the same import completes without a duplicate. `already_imported` is true when the world already held every event.

### What "replay is identical" means in the tests

`dest.events.read_events(...) == [dict(e, world_id=dest.world) for e in source_events]` (every other field, `seq`, `id`,
`ts`, `cause`, `trace.archive_ref`, unchanged), each per-district view the same modulo `world_id`, every artifact's bytes and
`content_sha256` equal, records equal but for `org_id`, `world_id`, `owner`, `sources` and `screened_at`, manifest revisions
equal, archive lines equal, the chain verifying with the same head, and `writer.recorded_version` equal. Exporting the
imported run again gives the same blobs, manifests and archive and the same events but for the world id.

## Assumptions the tests make where the PRD is silent

Marked in the tests; each is listed in the report.

1. Run id is kept on import (it is not a scope identity; the archive chain hashes cover it). Only `world_id` on events and
   `org_id`/`world_id`/`owner` on records are rewritten. User ids that are actors or `authz` refs in events are history and
   stay.
2. The bundle drops record `sources` (AR-06) and keeps the idempotency key, `created_at` and `redacted`.
3. A bundle is one whole run of one world from seq 1; a partial run (the world holds other runs) is not exportable.
4. Export is read-only and adds no `exported` manifest revision.
5. Screening is re-judged by the importer; see `import_version`.
6. Bundle caps: the PRD names no number; the defaults are the builder's choice and are listed as a decision.
7. A bundle whose records name another scope is imported under the importer's scope, not refused.
8. The raw archive is keyed by org and run, so two worlds of one org that import the same run share one archive copy.
