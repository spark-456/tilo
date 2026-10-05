# ADR-0018: Unit output and the artifact store

- Status: Accepted (2026-10-05, user decision: "yes to all as you think necessary", relayed by
  the supervisor; architect proposal; issue #283, BQ-218). Option A is chosen. The user approved
  the contract change (BQ-256) and the logged defaults BQ-257 to BQ-261. This ADR was first
  numbered ADR-0017 and was renumbered to ADR-0018 in approval order. This PR is docs only:
  `contracts/`, `config/`, `infra/` and code are changed by the tickets below (T1 for the
  contracts), not here. The ADR covers one new contract, an additive bump of a frozen event data
  schema and one event rule.
- Deciders: user (decision 2026-10-05), architect (proposal)
- Requirement: FR-MEM-06, FR-CON-09, FR-CON-10, FR-AGT-12, FR-MEM-09, HR-1 (PRD 8.1, 9.4, 12.4,
  13.1 to 13.4, 15.1, 15.3, 16.3, 16.5; S-12); FR-MEM-12 and FR-CON-15
  (`docs/prd-supplement-2026-10-05.md`); issues #283 and #329, PR #332; open questions
  BQ-256 to BQ-262 (all resolved, see the end)

## Context
1. Production `DefaultUnitRunner` (`services/harness/src/tilo_harness/executor.py:81`) calls the
   role's model and returns `UnitOutcome(success=bool(text), summary=...)`: the text is dropped
   and `artifact_refs` is empty. `run_plan` never emits `artifact.created`; it copies whatever refs
   a runner names into the handoff envelope.
2. `tilo_api.runs._GatedRunner` (`runs.py:455`) emits `artifact.created` for any ref a runner
   names. Its only checks are the ref's shape and `Run.foreign`, a scan of every other world's
   event stream for the id. Only `DevUnitRunner` names refs: `art_dev_<hex>`, with no content.
3. No store holds unit output. `tilo_planning.artifacts.InMemoryArtifactStore` (FR-INT-02 uploads)
   is in memory and unscoped; channels keep drafts in their own `DraftStore`; `tilo_render` returns
   bytes and stores nothing; the infra `artifacts` bucket (versioned, deletes at 365 days, render
   has `objectAdmin`) has no writer in code.
4. Consumers are waiting. The Verifier (#278) takes `load(ref) -> Deliverable(manifest, sources)`
   and records `unverified` without it. `build_manifest` (FR-CON-10) needs the version's bytes and
   the raw-archive records of its sources. `artifact.delivered` is written only on the gated path,
   so research-and-report plans end with 0 deliverables (#283, BQ-218). PR #332 (fixes #283) adds
   a final `deliver` unit that delivers `in_app` only the items its upstream units really made, and
   never mints one. With today's runner that is still 0, so #332 depends on the store this ADR
   decides. The render lane refused to mint empty artifacts and filed the gap as issue #329.
   Erasure names `gcs_artifacts` in `REQUIRED_STORES` with no adapter.
5. PRD: the Writer "produces deliverables from verified material" (8.1); every deliverable is
   versioned with a provenance manifest (12.4); artifact versions live in "Cloud Storage object
   versioning plus Firestore metadata" with content hashes (13.2); a restore is a new version
   (13.4, FR-MEM-06); Artifact and Version keep id, kind, versions, content hash and manifest for
   90 days (15.1); 15.3 has no artifact path. HR-1: a parcel at the Delivery Dock must stand for
   content that exists.

## Decision
### 1. A unit's output
- **Runners return content, never ids.** `UnitOutcome.outputs: tuple[UnitOutput, ...]`, where
  `UnitOutput(media_type, content: bytes, label, parent: artifact_ref | None, sources, claims)`.
  `sources` are `{id, archive_ref}` pointers to raw-archive tool calls and `claims` are manifest
  claims (FR-CON-10 inputs). The store mints `art_<ULID>` ids. `UnitOutcome.artifact_refs` stays
  only for existing versions a unit selects, and each is accepted only if the store holds it in
  the run's scope, else the unit fails. This replaces `Run.foreign`.
- **Three kinds, one closed media-type enum (9 values).** Text: `text/markdown` (prose, the
  `in_app` default) and `text/csv`. Structured: `application/json`, validated against the pinned
  skill's `outputs` schema when it declares one, or a render `DeliverableSpec`. File:
  `application/pdf`, PPTX, DOCX, XLSX, `image/png`, `image/jpeg`, made only by tilo-render or an
  intake upload, never by a model. Code picks the media type from the role and the pinned skill;
  a model never names one.
- **Who writes.** Specialists write their unit's text or structured output. The Writer writes the
  deliverable: Markdown for `in_app` and `markdown`, a `DeliverableSpec` for `pdf` and `pptx`.
  tilo-render turns a spec version into a new file artifact whose manifest `inputs` names that
  spec version. Intake uploads move onto the same store later (T8).
- **Size.** Content is at least 1 byte (text is not whitespace only). Text and structured outputs
  are at most 2,000,000 bytes, files at most 50,000,000 (intake's total, BQ-98), a unit has at most
  10 outputs and a world at most 200,000,000 bytes. Caps are checked before hashing; breaking one
  fails the unit, which then retries or escalates (FR-AGT-13). Defaults in BQ-257.

### 2. Where it lives
| Environment | Metadata | Bytes |
| --- | --- | --- |
| Tests and API dev mode (in-memory `Store`) | memory | memory |
| Local emulator (harness emulator suite) | Firestore emulator, `demo-` guard as `FirestoreStore` | local dir `TILO_ARTIFACT_DIR` (default `.tilo/artifacts/`, gitignored) |
| `tilo-dev` and production | Firestore | GCS `artifacts` bucket, `asia-southeast1` |

```text
orgs/{org}/worlds/{world}/artifacts/{artifact_id}/versions/{version:06d}                 ArtifactVersion
orgs/{org}/worlds/{world}/artifacts/{artifact_id}/versions/{version:06d}/manifests/{n:04d}  manifest revision
blob key: orgs/{org}/worlds/{world}/artifacts/{artifact_id}/v{version:06d}
```
Each version is one immutable object, created only if absent (GCS `if_generation_match=0`; local
`open(path, "xb")`). Bucket object versioning stays on as a guard against overwrites, but a
version's identity is its key and record, never a GCS generation (which cannot be chosen or
copied). Clients get no Firestore or Storage access to these paths (rules deny); every read goes
through tilo-api.

### 3. The store (`tilo_memory.artifacts`, pillar P7)
```python
class ArtifactStore:  # over MetaBackend (create-only docs, atomic next version) and BlobBackend
    def put(self, scope: Scope, new: NewVersion) -> StoredVersion: ...  # mints id, or next version of new.parent
    def head(self, scope: Scope, ref: ArtifactRef) -> StoredVersion | None: ...  # metadata only
    def read(self, scope: Scope, ref: ArtifactRef) -> bytes: ...  # re-hashes; ArtifactCorrupt on mismatch
    def versions(self, scope: Scope, artifact_id: str) -> list[StoredVersion]: ...
    def restore(self, scope: Scope, ref: ArtifactRef, *, by: Origin) -> StoredVersion: ...  # FR-MEM-06
    def add_manifest(self, scope: Scope, ref: ArtifactRef, manifest: dict, *, stage: str, cause: str | None) -> int: ...
    def manifest(self, scope: Scope, ref: ArtifactRef) -> dict: ...  # latest revision
    def retention(self) -> RetentionStore: ...  # FR-MEM-09 adapter, registered as gcs_artifacts
```
`Scope(org_id, world_id, owner)` comes from the run, never from a request. Backends are thin
(memory, local dir, Firestore, GCS); hashing, caps, scoping, versions and idempotency live once in
the store. Rules for a new `contracts/artifact.rules.md`:

| Rule | Rule |
| --- | --- |
| AR-01 | `content_sha256` is the SHA-256 of the stored bytes. Every `read` recomputes it; a mismatch raises `ArtifactCorrupt`, emits `alert.raised` and is never served. |
| AR-02 | Versions of an id run 1, 2, 3 with no gaps; a record or blob is never rewritten. `parents` are earlier versions of the same id; a restore's `parents` is the version it copies. |
| AR-03 | Every call is scoped: ids match `common.schema.json` patterns (no `/`), and a version of another org, world or owner reads as absent, so no call reveals that it exists. |
| AR-04 | The caps of section 1 hold for every put. |
| AR-05 | One version per idempotency key `<run_id>:<unit_id>:<attempt>:<index>`, so a restarted unit (FR-AGT-10) gets the same version back. |
| AR-06 | Each manifest revision passes `manifest.schema.json` and MF-01 to MF-06, names this version and carries its `content_sha256`. Revisions are append-only (`created`, `reviewed`, `sent`, `exported`); readers take the latest. |
| AR-07 | A version records `screening` (`clean`, `flagged`, `unscreened`; model output is screened, PRD 16.3 item 2) and `redacted` (secret redactor before put, SEC-01, BQ-258). Only `clean` versions leave Tilo. |
| AR-08 | Retention entity `artifact`, 90 days (PRD 15.1), `user_id` is the owner. A delete removes every blob generation, the record and its manifests. |

### 4. Contracts (contract change approved by the user 2026-10-05, BQ-256; made by T1)
- **New `contracts/artifact.schema.json` 1.0.0, title `ArtifactVersion`**, the record above (read
  by the harness, tilo-api, tilo-render and erasure). Required, `additionalProperties: false`:
  `v` (`"1.0"`), `artifact` (`artifact_ref`), `org_id`, `world_id`, `run_id`, `owner` (`user_id`),
  `media_type`, `size_bytes` (1 to 50,000,000), `content_sha256` (`^[0-9a-f]{64}$`), `parents`
  (`artifact_ref`s), `origin` (`{kind: unit | render | upload | restore, unit: unit_id | null,
  agent: agent_id | null}`), `sources` (`[{id: slug, archive_ref: "<run_id>/<seq>"}]`, kept for
  the Verifier, never exported), `screening`, `redacted`, `idempotency_key` (pattern above, or
  null for uploads and restores), `created_at`. `$defs/manifest_revision`: `{n, stage, cause:
  ulid | null, manifest: Manifest}`. No blob path field: the key is derived from the ids.
- **`common.schema.json`: new `$defs/media_type`** (the 9 values), minor bump.
- **`events/data/artifact.created.schema.json` 1.0.0 to 1.1.0, additive:** optional
  `content_sha256`, `media_type` and `size_bytes`. Optional, so events already in the ledger and
  the intake and channels producers stay valid. Every producer that goes through the store sets
  all three from the stored record, so the Trace shows the hash the store holds.
- **EV-15 (`event.rules.md`; `EventValidator` and `scripts/contracts_events.py`):** an
  `artifact.created` names version 1. An `artifact.reviewed`, `artifact.delivered`,
  `artifact.versioned` (with its `previous_version`) or `artifact.rolled_back` (with its
  `restored_version`) names a version that an earlier `artifact.created`, `artifact.versioned` or
  `artifact.rolled_back` of the same world recorded.
- No change to `artifact.delivered`, `artifact.reviewed`, `manifest`, `envelope` or `outbox`.

### 5. Consumers
- **Executor (harness).** After the runner returns and before `agent.handoff`, each output is put
  under the run's scope. One `artifact.created` per stored version follows (actor the worker,
  cause `agent.working`, data copied from the record, the unit's credits on the first as today),
  then a `created` manifest revision from `build_manifest`. The envelope's `artifact_refs` are the
  stored refs. If a put or the manifest fails, the unit fails and no event is written. The
  `_GatedRunner` in tilo-api stops emitting `artifact.created` and keeps only the gate.
- **Verifier load callback** (#278), so its fingerprint check compares archive text:
  ```python
  def load(ref):
      version = store.head(scope, ref) or raise_lookup(ref)  # absent, or another scope: unverified
      sources = {p.id: archive.source_text(p.archive_ref) for p in version.sources}
      return Deliverable(manifest=store.manifest(scope, ref), sources=sources)
  ```
  After the review, the Verifier's manifest (claims' `verified` recomputed) is appended as the
  `reviewed` revision, with `artifact.reviewed` as its cause.
- **Render.** Reads a spec version (`application/json`, parsed by `DeliverableSpec`), puts the PDF
  or PPTX as a new artifact (`origin.kind` render, manifest `inputs` the spec, claims re-located to
  slide or cell). It never mints ids or writes to the bucket directly.
- **Delivery and S-12.** The `deliver` unit of #332 records one `artifact.delivered` (`in_app`,
  `outbox_id` null) per deliverable version (BQ-259), only if `head` finds it and `read` passes
  AR-01. Its cause is the version's `artifact.reviewed`, or `artifact.created` with no Verifier.
  `GET /worlds/{id}/delivery` adds `media_type` and `size_bytes`. New
  `GET /worlds/{id}/artifacts/{artifact_id}/versions/{version}` (bytes) and `.../manifest`
  (latest revision) serve the owner and, per ADR-0012, a scoped viewer whose district saw the
  creating event. Gated sends keep their path; the outbox entry pins the version (OB-05).

### 6. Honesty (HR-1, HR-2)
- `artifact.created` is written only after the store has committed bytes and record; its data
  comes from the record, so a runner can name neither id nor hash.
- Empty or over-cap content fails the unit: no event, so nothing appears in the world.
- EV-15 means no stamp, parcel, version badge or rewind for a version that was never created.
- Every read re-hashes; a mismatched version is never served or delivered.
- S-12 shows "0 deliverables" only when no version qualifies (wording is the web ticket's).
- A version stored but never announced (the event write failed) is invisible, because worlds and
  lenses are event-driven. The idempotency key returns it on retry, and retention purges it.

### 7. Security
- **Untrusted content stays data.** Stored bytes are never instructions. They reach a model only
  as delimited, neutralised data (`untrusted.neutralise`, PRD 16.3 item 1), and code never parses
  them to decide an action. The media type comes from the record, never from sniffing or a
  model-written file name.
- **Serving.** `X-Content-Type-Options: nosniff`, `Content-Disposition: attachment` for files, and
  CSP `default-src 'none'`. S-12 renders Markdown without raw HTML and without remote images or
  auto-fetched links, closing an exfiltration path (PRD 16.2). No signed URLs in this release.
- **Caps** before hashing (AR-04). The secret redactor runs before put (AR-07). Model output is
  screened, and only `clean` versions are sent.
- **Owner scoping.** The store mints every id, every call is scoped (AR-03), and runner refs are
  checked against the scope. tilo-api checks the principal on every read. Reading another user's
  artifact returns 404, never 403.
- **IAM (BQ-261).** The harness, API and render get `objectCreator` and `objectViewer` on
  `artifacts`; only the retention and erasure identity deletes. Infra today gives render
  `objectAdmin`. The user applies this infra change (with the 90-day lifecycle); no builder or
  agent applies it.

## Options
| Option | What | Effort | Main files | Why or why not |
| --- | --- | --- | --- | --- |
| **A (chosen)** | One P7 store: bytes in local dir or GCS, metadata in Firestore, the contracts above | 8 tickets, about 2,300 hand-written lines | `contracts/artifact*`, `common`, `artifact.created`, `event.rules.md`; `packages/memory/.../artifacts*.py`; `executor.py`, `validator.py`; `runs.py`, `dev_run.py`, new routes; S-12 | One place for hashes, caps, scope, versions and erasure; matches PRD 13.2 and 15.1 |
| B | Content inside events or Firestore docs (`artifact.created.data.content`) | 2 tickets, about 500 lines | `artifact.created` (breaking), `runs.py`, S-12 | Rejected: 1 MiB doc limit, no PDF or PPTX, content kept 365 days in the ledger instead of 90, copied into every redacted view, no versions or restore |
| C | Each producer keeps its own store (today's pattern, extended) | 4 tickets, about 1,200 lines | `runs.py`, `dev_run.py`, render, planning, channels | Rejected: four copies of hashing and scoping, four erasure adapters, one Verifier loader per producer, cross-world checks stay event scans |

## Option chosen and tickets
Option A, chosen by the user on 2026-10-05. The tickets run in this order. Each starts test-first (the test-writer writes
`tests/<ID>`) and stays under 400 hand-written lines, not counting fixtures and generated types.
1. **T1 (architect; BQ-256 approved).** `artifact.schema.json`, `artifact.rules.md` AR-01 to AR-08,
   fixtures, `common` `media_type`, `artifact.created` 1.1.0, EV-15 with its fixtures, regenerated
   types. About 250 lines.
2. **T2 FR-MEM-06 (intelligence-builder).** `tilo_memory.artifacts`: `ArtifactStore` with memory
   and local-dir backends, restore, manifest revisions and the retention adapter. Tests: AR-01 to
   AR-08, and "restore v2, v3 is identical". About 350 lines.
3. **T3 FR-AGT-02 / FR-MEM-06 (intelligence-builder).** `UnitOutput`; the executor puts outputs and
   emits `artifact.created` from the record; refs are checked against the scope;
   `DefaultUnitRunner` returns its text as `text/markdown`; EV-15 in `EventValidator`. About 300.
4. **T4 CL-INT (tilo-api).** `runs.py` and `dev_run.py` on the store (memory backend in dev
   mode); `_GatedRunner` no longer mints or emits; `Run.foreign` goes; `DevUnitRunner` returns
   synthetic Markdown; credits stay on the first `artifact.created`. About 250.
5. **T5 FR-CON-10 / FR-AGT-12 (after #278).** `created` manifest at put; the Verifier's `load` from
   the store and archive; `reviewed` revision. About 250.
6. **T6 BQ-218, FR-CON-15 (BQ-262; CL-INT, after #332).** #332's `deliver` unit checks each version
   with `head` and `read` (BQ-259, BQ-260); content and manifest routes; `/delivery` fields. About
   250. With T1 to T4, this makes #283 and #329 deliver real content.
7. **T7 (world-builder).** S-12 shows the in-app deliverable (safe Markdown), Open and download,
   and empty-state wording. About 300.
8. **T8 (reach-builder).** Firestore and GCS backends (fake clients in CI), every generation
   deleted on erase, wired as `gcs_artifacts`; the infra change (BQ-261) is applied by the user, never by a builder or an agent. Later:
   render on spec artifacts, and intake moved off `tilo_planning.artifacts`. About 300.

## Consequences
- Every completed run can deliver real, hashed, versioned content in Tilo, with no new outbound
  path. Sending and saving stay gated.
- One store serves the Verifier, render, S-12, restore (FR-MEM-06), provenance (FR-CON-10) and
  erasure (FR-MEM-09).
- CL-INT-2 and CL-INT-5 tests that expect runner-named ids or `art_dev_` ids change in T3 and T4.
  The test-writer updates them; their intent (credits on the first created item, no item of
  another world) is kept.
- Cost: storage and one hash per put and per read; no model calls. The local emulator path needs
  no cloud credentials (ADR-0003).
- Not covered: signed download URLs, cross-world artifact memory (13.1 "offered as a starting
  point"), DOCX and XLSX rendering, and Google Docs output.

## Open questions (logged in `docs/open-questions.md`, all resolved 2026-10-05)
- BQ-256 contract changes: approved by the user (new `artifact.schema.json`, `common`
  `media_type`, `artifact.created` 1.1.0, EV-15). The architect makes them under T1.
- BQ-257 size caps: 2 MB text, 50 MB file, 10 outputs per unit, 200 MB per world.
- BQ-258 secrets in model output: redacted before put and marked `redacted`.
- BQ-259 which outputs are deliverables: the deliver unit delivers its upstream units' stored
  versions.
- BQ-260 failed or unverified review: delivered in-app with the Verifier's result.
- BQ-261 bucket retention and IAM: lifecycle Delete at 90 days per PRD 15.1. The infra change is
  applied by the user, not by a builder or an agent; until then the retention adapter deletes at
  90 days in code.
- BQ-262 requirement ID: FR-CON-15 (`docs/prd-supplement-2026-10-05.md`).

## T1 notes (contract made 2026-10-05, PR #366; the contract wins where it is stricter)
- `artifact.created` 1.1.0 carries all three new fields or none. `parents` has at most one item.
- The record gains `screened_at` (the SafetyProvider verdict's time, null exactly when
  `unscreened`). A `unit` output is text or JSON only, a `render` output is a file only, and an
  upload has no `sources`. A `reviewed` or `sent` manifest revision names its cause.
- AR-03: sources come from the record's own run (a restore copies them), and archive reads go
  through the Scope. AR-05: the key lookup is inside the Scope. AR-06: record sources never
  leave Tilo. AR-07: the policy engine raises `safety_flag` for any version not `clean`, read from
  the record (BQ-264 asks for the matching outbox rule).
- EV-15 also requires `versioned` and `rolled_back` to record the next version and rejects a
  second `artifact.created` of a recorded id.

## T3 notes (executor, 2026-10-06; clarifications, no new decision)
- An output with a `parent` is the next version of that artifact and is announced with
  `artifact.versioned` (`previous_version` the parent's), not a second `artifact.created` (EV-15).
  The unit's credits ride on its first announced item, whichever type.
- Section 5's order is tightened so a manifest failure writes nothing: every put and its `created`
  revision are committed first, then the events. The revision's `cause` is null.
- Attempts in the idempotency key start at 0. Only `ArtifactCorrupt` starts a new attempt, at most
  `retries.max_attempts` in all. An item `label` must be 1 to 80 printable characters the secret
  redactor leaves unchanged, or the unit fails.
- Until T4, tilo-api passes no store: `_GatedRunner` drops `outputs` (as before T3), and refs
  without a store pass unchecked as before. A harness run with outputs and no store fails the unit.
