# FR-MTG-08 scoped preview factory

`deps.get_followup_autopilot_factory(owner)` requires the existing Firestore outbox
and API client door. It creates no client, provider, thread reader or dispatcher.
New meeting emails remain T3/L1; retries keep the first scoped card. The emit must
carry M2's `before_publication` hook, also passed inside durable card/stop writes.
Fresh owner/world/run/UID/pause guards deny stale scopes and demo publication.
The public caller remains 503 pending M2/M4 integration and whole-chain review;
cross-store atomicity, source erasure and actual delivery are not proved here.
