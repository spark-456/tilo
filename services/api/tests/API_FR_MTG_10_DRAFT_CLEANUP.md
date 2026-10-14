# FR-MTG-10 follow-up draft deletion

`POST /v1/meetings/{id}/delete` retains the existing owner check, artifact purge and meeting CAS.
After the tombstone, the production dependency lazily opens the existing API store door and
drains the organization's draft collection using owner and source.meeting_id equality filters.
Each delete pins the snapshot update_time; changed replacements survive for a fresh pass.
Three passes of at most 200 documents each bound one request. A separate indexed read decides
completion. Remaining rows or unreadable storage refuse 503; the deleted-meeting retry drains
again. A source recheck before and after cleanup requires the same owner and deleted status.

Offline, demo and meetings without a world open no draft door. Body and marker envelopes share
the cleanup path. The operation does not authorize provider calls, cards, outbox entries or sends.
This is not cross-store atomicity: an in-flight SDK create can arrive after the final read; its
source is already deleted so normal draft reads/publication refuse, and a retry drains it.

Run `uv run pytest services/api/tests/test_FR_MTG_10_followup_cleanup.py -q`.
Acceptance covers owner isolation, fresh read, bounded incomplete/churn refusal, CAS ordering,
tombstone retries and the actual route/door with body and marker removal. Owner erasure and
periodic expiry cleanup remain separate integration requirements before minutes activation.
