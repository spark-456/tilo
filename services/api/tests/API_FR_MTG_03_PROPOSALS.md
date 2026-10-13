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

`persist_proposed_items` is the internal owner-only persistence seam. It rebuilds
the snapshot from both pinned artifacts and requires exact equality, then checks
meeting version, access, retention and world ownership around item writes and
before linking. Confirmed minutes refuse further linking. Prepared/stored creator
and history stamps use the fixed internal agent `A_meeting_minutes`; creates pass
the people write oracle with the current source meeting. PE-12 creation events go
to each assignee's verified Desk with bounded retries through `WorkEvents`.

Linked minutes are a new screened, read-back-verified immutable artifact; the old
pin remains readable. The meeting pointer changes by CAS without confirming it.
On failure, only this call's unchanged item versions are deleted and its meeting
write is undone by CAS. Racing confirmations/edits survive. A linked pin adopted
by a concurrent meeting write (including a lost acknowledgement) keeps its items
and artifact. Acknowledged creation events remain historical facts after later
compensation; no cross-store atomicity or distributed isolation is promised.
Ambiguous item creation/storage failures may leave proposed records for recovery;
deterministic ID collisions refuse rather than overwrite an existing record.
No public route, approval, recipient, card, external send or outbox is introduced.

Remaining: public owner-only mode/spend integration,
confirmed-minutes follow-up API integration, recorded provider-quality evaluation.

Offline validation: `uv run --package tilo-api pytest
services/api/tests/test_FR_MTG_03_proposed_items.py -q -p no:cacheprovider`.
