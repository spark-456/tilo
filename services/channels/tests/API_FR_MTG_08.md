# FR-MTG-08: public API pinned by the minutes-email and nudge tests (overridable)

FR-MTG-08 (`docs/prd-addendum-people-agents.md`, Must for drafting, Should for the send per the 5 Oct supplement):
"After confirmation the agent drafts (never sends) a minutes email to attendees the Owner picks and a nudge per open
item, with the FR-CHN-10 drafter. Sending is T3: card, Owner approves, outbox." Acceptance: "Property test (FR-HIL-04):
no outbox entry without an approving `approval.resolved`; 0 invented commitments". The full interface and behaviour list
are in the docstring of `test_FR_MTG_08_minutes_email_and_nudges.py`; the doubles are in `_mtg08_lib.py` on top of the
CHN-WIRE-1 line (`_chn_wire1_lib.py`). If a name or shape changes, update the tests in the same PR and say so.

```python
# services/channels/src/tilo_channels/meeting_followup.py (new module)
class MeetingFollowUp:
    def __init__(self, *, meetings, minutes, work_items, directory, model, safety, drafts, autopilot, mailbox, clock,
                 emit=...) -> None
    def draft_minutes_email(self, user_id: str, meeting_id: str, *, recipients: Sequence[str], request_id: str) -> Preview | None
    def draft_nudges(self, user_id: str, meeting_id: str, *, request_id: str) -> list[Preview]
```

Ports (read only; each returns the contract record or None): `meetings.get(user_id, meeting_id)` (`meeting.schema.json`),
`minutes.get(user_id, artifact_id, version)` (`minutes.schema.json`), `work_items.get(user_id, work_item_id)`
(`work_item.schema.json`), `directory.address(person_id)` (resolved by tilo-api, PE-09 / PE-20).

No contract change is needed: the Autopilot already carries a thread-less new email (`DraftContext.mode` "new",
`Draft.thread_id` None, so the outbox entry has `destination` null, which `contracts/outbox.schema.json` and the Gmail
adapter allow); it is T3 by `new_recipients` (FR-CHN-12). The FR-CHN-10 `Drafter` itself is thread-bound (it reads a
thread and replies), so the follow-up reuses its pieces (`Draft`, `DraftResult`, `Checker`, the "autopilot" role through
`ModelProvider`, `SafetyProvider`, the draft store) rather than calling `Drafter.draft`.

Defaults taken where the text is silent or two sources pull apart (proposed `docs/open-questions.md` rows; the merger
allocates ids):

| ID | Question | Default taken in these tests | Source |
| --- | --- | --- | --- |
| BQ-TBD | Which module owns it, and what are its inputs? | `tilo_channels.meeting_followup.MeetingFollowUp`, ports as above; tilo-api's meeting actions call it with the Owner's picks and a request id. | FR-MTG-08, FR-PA-09 |
| BQ-TBD | What does "after confirmation" mean? | The meeting is `minuted`, `minutes_confirmed_by` is set by the meeting Owner, and the minutes artifact names this meeting. Anything else (or a caller who is not the Owner): None / [] with nothing drafted. | FR-MTG-06, PE-05, PE-07, PE-19 |
| BQ-TBD | "Attendees the Owner picks": by what? | Person ids of attendees that have a `user` (`attendees[].user`); an outsider with `user` null cannot be picked (no address Tilo may use). A pick that is no attendee, an empty pick, or one with no resolved address gives no card (the Owner's audience is never changed silently). | PE-09, PE-20, meeting.schema |
| BQ-TBD | What is a "confirmed open item"? | A `verified` action item whose work item is `open`, `confirmed_by` the meeting Owner and whose `source.ref` is `<meeting>#<item id>`. `proposed`, `done`, `dropped` and unlinked items get no nudge and no line in the email; an `unverified` decision is not confirmed content. | FR-MTG-04, FR-MTG-06, PE-03, PE-07, PE-19 |
| BQ-TBD | Who gets a nudge? | The item's assignee (`action_items[].owner`), resolved by the directory, whether or not the Owner picked them for the minutes email; one T3 card per item, each Owner-approved. A nudge carries its own item only (an assignee reads nothing else of the meeting). | PE-05, FR-MTG-08 |
| BQ-TBD | How is "0 invented commitments" tested when a model writes the body? | The FR-CHN-10 checker runs on every body with the confirmed text as its only sources, and a body that repeats text the Owner did not confirm is refused; a refused body is `needs_you` (Edit and Cancel only) or no card, never sendable. A scripted faithful model gives a ready card. | FR-CHN-10, PRD 11.4 Content |
| BQ-TBD | Flagged minutes or items? | T3 with `safety_flag` (already T3 here; the modifier is shown on the card). | PE-21, SEC-04 |
| BQ-TBD | Edit on these cards? | Not pinned: `Autopilot.edit` redrafts reply formats only, so a changed draft is a new request id. | FR-CHN-11 |

## FR-MTG-08b: wiring checklist for tilo-api (what the module does NOT do)

`MeetingFollowUp` trusts its caller for these; tilo-api's meeting actions must do each before calling it:

- [ ] `user_id` comes from the signed-in session (auth), never from the request body; the module also refuses anyone who is not the meeting's Owner and any `user_id` the Autopilot's world does not belong to.
- [ ] `request_id` is minted by the server (or validated: a short opaque id the server issued for this tap). The idempotency key is a JSON array of (kind, meeting, request id, picked addresses / work item), so any text is safe, but a client that picks the id can only replay its own draft.
- [ ] The `Autopilot` is built for the Owner's meeting / Desk world (PE-12): `world_id`, `world_owner`, the card store and the outbox are that world's; never a shared or another person's world.
- [ ] A per-Owner rate limit on both methods (each call may make a model call per item, at most 60 items, and a screen of up to 100,000 characters).
- [ ] Check `meeting.minutes_confirmed_by.at` against the time of the request (PE-07, PE-19): the confirmation is no later than now and the minutes artifact version the meeting names is the one confirmed. The module checks `by`, `status` and the artifact's `meeting_id`, not the timestamp.
- [ ] The readers are scoped to the Owner (PE-05) and the directory resolves addresses server side (PE-09, PE-20); the `recipients` the Owner picks are person ids of attendees.
- [ ] Sending is only `Autopilot.send` with the Owner's recorded `approval.resolved` (CHN-WIRE-1); there is no send path in this module.
