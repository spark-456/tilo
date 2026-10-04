# FR-CHN-13: public API pinned by the threaded-send tests (overridable)

FR-CHN-13 "Threaded send via Gmail through the outbox, exactly once". The acceptance test is "Retry storms never
duplicate a send" (PRD 11.6). Sources: PRD 11.2 (send in the same thread), 11.4 (Threading, Preview, Injection,
Formats, Undo), 10.4 (T3 always needs a person), 8.5 and FR-AGT-11 (outbox, exactly once), OB-02 to OB-05
(`contracts/outbox.rules.md`), BQ-154, BQ-157, BQ-174, BQ-182 to BQ-185.

The tests run the real send path end to end: the FR-CHN-10 `Drafter` (scripted model), the FR-CHN-11/12 `Autopilot`,
the real `tilo_connectors.Outbox` and `InMemoryOutboxStore`, and the real `tilo_connectors.adapters.GmailAdapter`.
Gmail itself is `_chn13_lib.FakeGmailApi` behind the adapter's `Transport` seam: no network, no real mail, a token
assembled at runtime. `tilo_policy.check_entry` is an accept-all while these tests run (BQ-184); the outbox's schema,
OB-02 and OB-03 checks still run. If a name or shape below changes, update the tests in the same PR and say so.

## `tilo_channels.autopilot_send` (new module)

```python
class DraftArtifacts:   # the ArtifactSource the Gmail adapter reads (tilo_connectors.adapters.ArtifactSource)
    def __init__(self, *, cards: CardStore) -> None      # the same card store the Autopilot writes
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]
        # {"kind": "email", "subject": Preview.subject, "body_text": Preview.body, ...}
        # the text the person saw: clean_text of the draft (CRLF, lone CR and other separators as "\n"; other
        # Cc and Cf characters removed). Same answer from a fresh instance over the same store.
        # KeyError for an unknown artifact id or version (the adapter refuses the send: entry failed).
```

tilo-channels still never imports `tilo_connectors` (BQ-158); the service wiring hands `DraftArtifacts` to the
`GmailAdapter` as `artifacts`.

## `tilo_channels.autopilot` (changed)

- The safety flag of the draft FR-CHN-10 stored for the instruction (`draft.safety_flag` or `flagged`) counts, even
  when the `DraftResult` passed to `preview` says clean (BQ-183). Either flag adds the `safety_flag` modifier: T3, L1,
  nothing scheduled. Read it through what the Autopilot already holds (for example a read-only lookup on the
  `Drafter`), so the constructor in `_chn11_lib.Bench.new_autopilot` keeps working; if it must change, change the lib.
- A result with no stored draft (the FR-CHN-11 tests build those) keeps its own flags.

## Behaviour the tests check

- **Threaded.** Every mail Gmail accepts carries the card's thread id, `In-Reply-To` = the Message-ID of the message
  replied to (the thread's last), `References` = that message's References plus its id, `Subject` = "Re: ...".
  Never a new email.
- **What is sent.** Body = `Preview.body`; no lone CR, control or format character reaches Gmail. To/Cc/Bcc =
  exactly the card's recipients, which come from the thread (and, for "known", contacts and the user's own sent mail),
  never from the model's answer; no Bcc, no Reply-To. A contact or draft address with U+212A never matches an ASCII
  address (BQ-174): a new recipient, T3.
- **T3 needs a person.** A T3 card (money/legal, safety flag, new recipient) sends nothing however long the clock runs;
  its owner's Send queues one entry with `authz` person and the modifiers, which then sends once.
- **Exactly once.** One outbox entry per card. Repeated, cross-instance and concurrent Send taps; Gmail 503s, dropped
  requests and lost answers; a dispatcher that dies right after Gmail accepted the send, then restarts; eight
  dispatcher instances racing; a cancel in the undo window followed by a storm: at most one mail, and exactly one
  once the storm is over unless the send was cancelled. A policy (L2) send never leaves before `created_at` + 60 s.
- **Property test.** Any interleaving of those operations keeps every invariant above.
