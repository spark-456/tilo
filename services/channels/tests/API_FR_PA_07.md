# FR-PA-07: public API pinned by the "Draft reply" tests (overridable)

FR-PA-07 (`docs/prd-addendum-people-agents.md`, Must): "A mail item on the plate offers 'Draft reply', which runs
FR-CHN-10, -11, -13 unchanged (tiers, undo, outbox). No new send path." Acceptance: "SEC-03 static check passes; EV-15
p95 <= 15 s holds." The full pinned interface and the behaviour list are in the docstring of
`test_FR_PA_07_draft_reply.py`; the doubles are in `_pa07_lib.py` on top of the FR-CHN-09/10/11/13 doubles. If a name or
shape changes, update the tests in the same PR and say so in the review.

```python
# services/channels/src/tilo_channels/plate_reply.py (new module)
class PlateReply:
    def __init__(self, *, triage: TriageStore, mail: MailReader, drafter: Drafter, autopilot: Autopilot,
                 mailbox: Callable[[str], str | None]) -> None
    def draft_reply(self, user_id: str, mail_id: str, *, request_id: str) -> Preview | None
```

Defaults taken where the text is silent or two sources pull apart (proposed `docs/open-questions.md` rows; the merger
allocates ids):

| ID | Question | Default taken in these tests | Source |
| --- | --- | --- | --- |
| BQ-TBD | FR-PA-07 says the tap "runs FR-CHN-11 unchanged (tiers, undo)"; PE-10 says `draft_reply` "makes a draft (T1), sends nothing and never takes the Autopilot path". Can a tap ride the L2 undo window? | No. A tap carries no instruction text (the `ui_action` has only a thread), and FR-CHN-11 already keeps a blank instruction off L2 (BQ-222). So the same `Autopilot.preview` gives an L1 card and a send only after the owner's approval; tiers (T2, T3 modifiers) and the undo window of an L2 send for a typed instruction are untouched. | PE-10, FR-PA-07, BQ-222, BQ-CHRM-2 |
| BQ-TBD | Which module owns it? | `tilo_channels.plate_reply.PlateReply`, a thin wrapper over the Drafter and the Autopilot; tilo-api's plate action (PPL-11a) and the panel's `draft_reply` call it. The plate builder is not built on this branch and `plate.schema.json` is not merged, so the tests start from the mail id of a row (`ref.kind` "mail"). | ADR-0021, FR-PA-16 |
| BQ-TBD | What is "on the plate" for the tap? | A triage result stored for exactly (user, message id) whose effective category is `needs_reply` (the person's label beats the model; a safety flag beats a label), still readable, and a connected mailbox of her own. "Already answered or dismissed" stays with the plate builder. | ADR-0021 decision 2, FR-CHN-09 |
| BQ-TBD | What is the idempotency key? | `request_id`, the id of the tap (tilo-api mints it); the builder derives the FR-CHN-10 `instruction_id` from it. A new tap on the same mail is a new draft. | FR-CHN-10, OB-01 |
| BQ-TBD | Reply mode? | `reply` (to the sender, no Cc). Reply-all, forward and new mail stay with typed instructions. | PRD 11.4 Formats |
