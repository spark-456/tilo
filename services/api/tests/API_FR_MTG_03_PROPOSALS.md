# FR-MTG-03/04/05 proposed-item preparation

`meeting_proposals.prepare_proposed_items` prepares schema-valid `proposed` work-item
records from the meeting owner's exact stored minutes and transcript versions.
It is an internal read-only seam: no item or artifact is written, no minutes link is
changed, no confirmation stamp, event, recipient, card or outbox entry is created.

Access, world ownership, both retention deadlines and artifact integrity are checked
before extracting actions. The minutes must name the same meeting and transcript pin.
Duplicate action IDs and unsupported verified evidence refuse the whole batch.
Unverified actions, unresolved/no-longer-visible identities, already-linked actions
and actions exceeding work-item title/evidence limits stay in the minutes unchanged.
Current directory matching must agree with the pinned resolved owner. Due values
are preserved from the internal analyst's deterministic resolution; this seam never
accepts a client Minutes document or model output. Safety flags from either artifact
or the minutes propagate to every prepared item.

The batch carries the captured meeting version and both artifact pins, with a final
access/version check after reads. IDs include org, meeting, action and exact pins.
The persistence caller MUST recheck these guards at its write boundary and retain
owner-only review plus the existing separate confirmation flow. Preparation does not
establish atomic persistence, idempotent minutes linking or confirmation integration.

Remaining: guarded persistence/linking, public owner-only mode/spend integration,
confirmed-minutes follow-up API integration, recorded provider-quality evaluation.

Offline validation: `uv run --package tilo-api pytest
services/api/tests/test_FR_MTG_03_proposed_items.py -q -p no:cacheprovider`.
