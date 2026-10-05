# packages/memory — `tilo_memory`

## Purpose
Pillar P7 memory (PRD 13.1, 13.2): result cache (`cache.py`), event ledger (`ledger.py`), retention
(`retention.py`), erasure (`erasure.py`), artifact store (`artifacts.py`, ADR-0018). Cache: a web, file or
email-body result is reused when fresh and a fit check and the Verifier accept it; each reuse is one
`memory.hit` event and the only thing credited as saved (PRD 14.3).

## Commands
- `uv run pytest packages/memory/tests -q` — acceptance and property tests (fakes only, network blocked)
- `just check` — full gate from the repo root

## Contracts
- Builds `memory.hit` (`contracts/events/data/memory.hit.schema.json`, EV-09: `saved` = `origin_cost` minus
  `lookup_cost`), validated with `tilo_contracts`. Returns events, never writes them: the harness is the
  single writer and owns `seq`. There is no `memory.miss` type (BQ-192): a miss is a `cache.log` record.
- Artifact records and manifest revisions are checked against `contracts/artifact.schema.json` with
  `jsonschema` (the pydantic model drops its conditional rules); AR-01 to AR-08 in `artifact.rules.md`.

## Config
- None yet. `lookup_cost` is a constructor argument; the 7-day web window is a constant (PRD 13.1).

## Local rules
- Cache key = kind + whitespace-normalised request + source fingerprint (no case folding, BQ-190). Web results
  are fresh 7 days; files until their fingerprint changes; email bodies are never stored.
- `fit_check` and `verifier` are injected `(request, value) -> bool`, wired through `packages/providers`
  (PL-01, role `verifier`); no model id or call here. A rejected entry is never served (BQ-193).
- Time comes only from the injected clock; nothing sleeps or touches the network.
- Ledger (FR-MEM-03): `EventLedger.ingest` keys on event `id`, first write wins, same id with other content is
  `conflict`, unreadable is `rejected` (BQ-194). No update/delete; `insert_if_absent` is atomic on the table.
- Erasure (FR-MEM-09): `erase_user` takes a validated `ErasureRequest`; blank/wildcard ids refused, ownerless
  records never deleted, incomplete registry refused before any delete, done = fresh re-read (`verify_erasure`).
- Artifacts (FR-MEM-06/12): `ArtifactStore` over create-only `MetaBackend`/`BlobBackend` (memory, local dir
  `TILO_ARTIFACT_DIR`). Ids matched whole (`fullmatch`) before any key; other scope reads as absent; caps
  before hashing; redactor error fails the put; screening only from the screener verdict; restore = exact
  copy; record is written before its blob (a blob always has a listed record); `retention()` is the
  `gcs_artifacts` adapter. Firestore/GCS backends are ticket T8.

## Requirement IDs
FR-MEM-01, FR-MEM-02, FR-MEM-03, FR-MEM-06, FR-MEM-09, FR-MEM-12.
