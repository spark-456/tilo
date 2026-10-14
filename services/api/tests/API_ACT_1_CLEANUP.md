# ACT-1b: called draft/card/stop cleanup

Meeting deletion drains all three policies after tombstone CAS; retries on the same
tombstone resume cleanup. Production PeopleStores injects a SAME-client erase hook:
erase_person tombstones its meetings, drains follow-up rows, then deletes the person.
Three bounded passes plus a fresh indexed read are required for erasure success.
The authenticated Scheduler branch calls a bounded expiry pass; task/forged callers
do not run it. Sweep failures log only exception type and are retried on a later tick.

Cards/stops are queried by collection group with org_id + retention_namespace filters;
owner/source/expiry filters narrow the query. Snapshot preconditions protect replacements.
Full reference paths must name the org's followup_autopilot cards/stops collections.
Offline tests cover called routes/hooks, deletion then unreadability, retained foreign
scope, and incomplete drains. Existing assertions remain unchanged; the fake SDK gained
collection-group and nested-field support.

Activation prerequisite: provision/verify collection-group indexes for cards/stops
(org_id, retention_namespace, owner[, source.meeting_id]) and
(org_id, retention_namespace, expires_at); followup_drafts needs owner/source and expiry
indexes too. No emulator/index provisioning is claimed by these offline tests.
ACT-1c must declare these indexes for infrastructure-owner review; do not activate yet.
