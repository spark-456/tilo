# Run-scoped upload storage (I2, FR-INT-02)

Deployed Thinking intake uses the existing configured artifact and raw-archive
stores before the Director runs. Its file references resolve in the new run's
server-generated org/world/principal scope. Native and converted file bytes use
the artifact contract's existing limits and authoritative stored screening.
Flagged or unscreened versions are excluded from brief sources. Archive entries
contain redacted upload metadata and hashes; artifact.created traces cite them.
Upload artifact versions have no archive sources (AR-03).
If archival cannot preserve an originally flagged/unscreened verdict, intake
refuses rather than publishing an upgraded artifact record.

Invalid UTF-8 CSV, empty files, bad magic and extraction failures receive per-file
refusals before any put. Office versions record the converted-text safety verdict;
native media and CSV use the store's existing screening path, once per file.

Completed versions are cleaned up on pre-commit refusals. After a task persistence
failure, cleanup first reads the task/world: landed commits and failed reads retain
owned versions, as does cancellation during a commit. Abort invalidates prepared
references so a same-key retry rebinds and screens fresh versions.
Archive attempt metadata is append-only. Partial backend puts and failed cleanup
retain the store's existing repair/retention semantics; this is not a cross-store
transaction or a deletion feature. Dev and anonymous demo uploads stay in memory;
Quick mode opens no stores. KnowledgeItems and source-erasure policy await ADR0036.

Thinking accepts the existing optional Idempotency-Key protocol, scoped to the
principal, route and body (including file hashes). Warm retries return the first
response. Stable task/world/run ids prevent a duplicate after a lost commit reply
or limiter restart: a stored task returns 409 intake_already_committed before the
Director, with its task/world ids. The response cache itself remains in memory.

Follow-ups: channel_in attempt lines lack a run-to-owner erasure index, there is
no per-person durable byte cap, and this slice provides no upload/archive/brief
source delete path (ADR-0036). It is not a cross-store transaction.
