# Artifact store rules beyond the schema (artifact.schema.json v1)

ADR-0018, FR-MEM-12 (`docs/prd-supplement-2026-10-05.md`). `artifact.schema.json` checks one
`ArtifactVersion` record and one manifest revision. The store (`tilo_memory.artifacts`, P7) holds
the rules below on every call, and its tests cover them; a rule that needs the bytes, other
versions or the run cannot have an invalid fixture. Rule ids are stable.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| AR-01 | `content_sha256` is the SHA-256 of the stored bytes. Every `read` recomputes it; a mismatch raises `ArtifactCorrupt`, emits `alert.raised` and is never served or delivered. | store | 13.2, HR-1 |
| AR-02 | Versions of an id run 1, 2, 3 with no gaps; a record or blob is never rewritten. `parents` is empty for version 1 and otherwise names one earlier version of the same id; a restore's `parents` is the version it copies (schema: at most one). | store (schema for the count) | 13.2, 13.4, FR-MEM-06 |
| AR-03 | Every call is scoped by `Scope(org_id, world_id, owner)` from the run, never a request: ids match `common.schema.json` patterns (no `/`, schema), and a version of another org, world or owner reads as absent, so no call reveals that it exists. | store (schema for id shapes) | 15.1, 16.5 |
| AR-04 | Caps, checked before hashing: content is at least 1 byte (text not whitespace only); text and JSON at most 2,000,000 bytes and files at most 50,000,000 (schema); a unit at most 10 outputs (schema: key index 0 to 9); a world at most 200,000,000 bytes. Breaking one fails the unit (FR-AGT-13). | store (schema for size and index) | BQ-257 |
| AR-05 | One version per idempotency key `<run_id>:<unit_id>:<attempt>:<index>`: its run and unit equal the record's `run_id` and `origin.unit`, and a restarted unit (FR-AGT-10) gets the same version back. Unit and render outputs have a key, uploads and restores have none (schema). | store (schema for presence and shape) | FR-AGT-10 |
| AR-06 | Each manifest revision passes `manifest.schema.json` and MF-01 to MF-06, names this version and carries its `content_sha256`. Revisions are append-only, `n` from 1 with no gaps (`created`, `reviewed`, `sent`, `exported`); readers take the latest. `sources[].id` are unique and name sources of the manifest. | store (schema for the shape) | 12.4, 13.3, FR-CON-10 |
| AR-07 | A version records `screening` (`clean`, `flagged`, `unscreened`; model output is screened, PRD 16.3 item 2) and `redacted` (the secret redactor runs before put, SEC-01, BQ-258; the stored bytes are its output). Only `clean` versions leave Tilo. | store; outbox | 16.1, 16.3, SEC-01 |
| AR-08 | Retention entity `artifact`, 90 days (PRD 15.1), `user_id` is `owner`. A delete removes every blob generation, the record and its manifests. | store (retention adapter) | 15.1, FR-MEM-09 |

Events: `artifact.created` is written only after the store committed bytes and record, with
`content_sha256`, `media_type` and `size_bytes` copied from the record (`artifact.created` data
1.1.0), and every artifact event names a version the world recorded (event rule EV-15).
