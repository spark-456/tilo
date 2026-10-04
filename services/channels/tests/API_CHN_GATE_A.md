# CHN-GATE-A: outbox read port and stop sweeper (gates FR-CHN-11, issue #256)

Issue #256 "Before production wiring / real send (gates)", first two bullets. Both gate FR-CHN-11's acceptance test
"L2 send can be cancelled within 60 s; no send after cancel" (PRD 11.6, PRD 10.4 L2, 11.4 Undo "Cancel works until
then"; OB-02, OB-03, OB-05; BQ-170).

1. **A stop never creates an outbox entry.** Today the stop side (`autopilot_state.Ledger._settle`) looks an entry up
   by enqueueing the card's key again. If the preview's enqueue never stored the entry, the Cancel tap itself stores
   it; if the cancel of that entry then fails and nobody retries, the Cancel created a mail that is sent at 60 s.
2. **A sweeper settles unconfirmed stops** (`CancelPending`, BQ-170) before the entry's `scheduled_at`, and surfaces
   can show "not confirmed, retry".

These are the tests' assumptions (BQ-186 to BQ-188); the builder may override a name or shape, updating the tests in
the same PR and saying so in the review. The tests import only what is listed here. Doubles are in
`_chn_gate_a_lib.py` on top of `_chn11_lib.py`. Fake clock, fake outbox, fake Gmail only; no network, no paid call.
No contract (`contracts/`) changes: the read port and the revocation are methods of the Python outbox port, not schema.

## Outbox port (`tilo_channels.autopilot_state.Outbox`, and `tilo_connectors.Outbox`)

```python
class Outbox(Protocol):
    def enqueue(self, entry: dict, evidence: dict) -> dict: ...  # unchanged (OB-02, OB-03)
    def cancel(self, outbox_id: str) -> dict: ...  # unchanged: raises unless "scheduled"
    # new, read port: a copy of the stored entry or None; never writes, never calls tilo_policy.check_entry;
    # raises only when the outbox cannot be read. A world-scoped tilo_connectors.Outbox(world_id=w) never returns
    # another world's entry (None, as for an unknown one).
    def get(self, outbox_id: str) -> dict | None: ...
    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None: ...
    # new, revocation (issue #256: "check_entry must refuse creation after a revocation"): never creates an entry.
    # Entry stored under the key: a "scheduled" one becomes "cancelled"; the entry is returned (any state).
    # Nothing stored: the key is recorded as revoked and None is returned; from then on enqueue() of that
    # (world_id, idempotency_key) raises OutboxRefused and stores nothing. Idempotent. A world-scoped outbox
    # refuses (OutboxRefused) or ignores another world's key, and never changes another world's entry.
    def revoke(self, world_id: str, idempotency_key: str) -> dict | None: ...
```

Assumed (issue #256): the outbox never prunes idempotency keys or revocations, so a read by key, a repeated enqueue
and a revocation answer the same way however old the entry is.

## `tilo_channels.autopilot`

```python
SWEEP_INTERVAL_S: int        # how often production runs Autopilot.sweep(); 0 < SWEEP_INTERVAL_S <= UNDO_WINDOW_S / 4
                             # (BQ-187 default 10), so a stop gets several tries inside the 60 s window

class StopQueue(Protocol):   # the stops not yet confirmed; shared by every instance (Firestore in production)
    def add(self, user_id: str, card_id: str) -> None: ...      # idempotent
    def pending(self) -> list[tuple[str, str]]: ...              # (user_id, card_id) added and not removed
    def remove(self, user_id: str, card_id: str) -> None: ...   # idempotent

class Autopilot:
    def __init__(self, *, ..., stops: StopQueue | None = None) -> None   # FR-CHN-11 arguments unchanged;
        # None only for benches that never sweep (the FR-CHN-11 tests); production wiring passes one
    def sweep(self) -> dict[tuple[str, str], str]
        # Settles every pending stop: (user_id, card_id) -> "cancelled" | "too_late" | "pending".
        # "cancelled": the outbox confirmed no entry of the card can send (revoked, or shown "cancelled").
        # "too_late": the outbox showed the entry sending, sent or failed. "pending": the outbox could not
        # confirm; the stop stays queued for the next run. A failure on one card never stops the others and is
        # never raised. Never enqueues; never touches a card that has no recorded stop.
    def stop_state(self, user_id: str, card_id: str) -> str | None
        # None: no stop recorded. "pending": recorded, not confirmed (surfaces show "Not confirmed, retry";
        # Cancel is the retry). "cancelled" | "too_late": settled, as above.
```

## Behaviour the tests check

- **No stop creates an entry** (`test_CHN_GATE_A_FR_CHN_11_read_port_stop.py`). Cancel and Edit (and the sweeper)
  never call `enqueue`. Cancel on an L2 card whose preview never stored an entry leaves the outbox with 0 entries,
  whatever the outbox does (healthy, `cancel` down, every call down, an answer lost), and nothing is sent at 60 s or
  later even if nobody retries. With a healthy outbox that Cancel answers "cancelled" (BQ-186); otherwise it raises
  `CancelPending`. Once a stop is recorded (a Cancel or Edit answered, or raised `CancelPending`), no `enqueue` that
  starts later stores an entry for the card.
- **Cancel racing enqueue.** A Cancel or Edit landing while the preview's enqueue is in flight (before or after the
  outbox stores the entry, the enqueuing instance dying or not) answers "cancelled" with a healthy outbox, and no
  entry of the card is ever sent. If the outbox cannot confirm it raises `CancelPending`, never "cancelled".
- **Sweeper** (`test_CHN_GATE_A_FR_CHN_11_sweeper.py`). A stop the outbox did not confirm is listed in `StopQueue`
  and `stop_state` is "pending". A sweep from any instance with a healthy outbox before `scheduled_at` settles it
  "cancelled": the entry is cancelled, the queue empties, nothing is sent, and a later Cancel says "cancelled". While
  the outbox stays down each sweep answers "pending"; the first healthy sweep before `scheduled_at` settles it. If the
  entry was sent first, the sweep answers "too_late" and `stop_state` is "too_late", never "cancelled". A card with no
  stop is never touched (it sends at 60 s exactly once). A sweep never creates an entry, also for a never-enqueued
  card. Restart: the Cancel's instance or a sweeper's instance dying at any call leaves either no recorded stop or
  one the next sweep settles; a stop is recorded before the outbox is first called. Concurrent sweepers on four
  instances settle each card once, consistently, without errors.
- **Property tests.** Under random interleavings of replay / Send / Cancel / Edit / advance / dispatch (and sweep),
  with one-shot outbox faults (down, answer lost), instance deaths around outbox and card-store calls, and another
  owner's action landing while an enqueue is in flight: no stop calls `enqueue`; no enqueue that started after a
  recorded stop stores an entry; a confirmed stop is never followed by a send (without any sweep); "too_late" only
  when something was sent; one card, at most one entry. With sweeps, one healthy sweep before `scheduled_at` leaves
  every recorded stop "cancelled" and nothing sent.

Defaults taken where the issue and PRD are silent: BQ-186 to BQ-188 in `docs/open-questions.md`.
