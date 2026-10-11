# Run-scoped upload storage (I2, FR-INT-02)

Deployed Thinking intake uses the existing configured artifact and raw-archive
stores after the Director succeeds. Its file references resolve in the new run's
server-generated org/world/principal scope. Native and converted file bytes use
the artifact contract's existing limits and authoritative stored screening.
Flagged or unscreened versions are excluded from brief sources. Archive entries
contain redacted upload metadata and hashes; artifact.created traces cite them.
Upload artifact versions have no archive sources (AR-03).
If archival cannot preserve an originally flagged/unscreened verdict, intake
refuses rather than publishing an upgraded artifact record.

Completed versions are cleaned up after an archive/task persistence failure.
Archive attempt metadata is append-only. Partial backend puts and failed cleanup
retain the store's existing repair/retention semantics; this is not a cross-store
transaction or a deletion feature. Dev and anonymous demo uploads stay in memory;
Quick mode opens no stores. KnowledgeItems and source-erasure policy await ADR0036.
