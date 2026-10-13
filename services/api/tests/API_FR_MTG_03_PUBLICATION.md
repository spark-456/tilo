# FR-MTG-03: offline minutes publication

`meeting_minutes.publish_minutes` is an internal seam for importing already analysed,
schema-valid Minutes into the ended meeting's owner-scoped artifact store. It is not
a public request body and does not call the meeting analyst or any provider.

Publication requires the meeting owner, an ended meeting, an unexpired transcript in
the same owned world and the exact stored transcript version. Evidence ids are checked
against that version. Existing work-item links are refused. The artifact store screens
and redacts the imported JSON; source safety flags propagate to the minutes.

The meeting becomes `minuted` with 90-day retention and no confirmation stamp. The
registered `meeting.minuted` event carries only artifact references, counts and flags.
A lost compare-and-set removes the newly created artifact. Event failure rolls back
only the publication's own record version, preserving concurrent writes.

The owner must still confirm minutes using the existing confirmation route. This seam
never creates or opens items, picks recipients, drafts email, or enqueues an outbox entry.
FR-MTG-08's existing `meeting_followup` drafter keeps its T3 approval/outbox guards.

Remaining integration: provider-backed analyst and semantic verifier, deterministic
owner/date resolution, proposed-item creation, and API wiring of the follow-up drafter.
The offline import seam does not establish FR-MTG-03's extraction recall/precision gate.

Validation: `uv run --package tilo-api pytest
services/api/tests/test_FR_MTG_03_minutes_publication.py -q -p no:cacheprovider`.
