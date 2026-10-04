# CHN-WIRE-1: public API pinned by the person-approved Send tests (overridable)

CHN-WIRE-1 (FR-CHN-11; issue #307 plan ticket 1, issue #256 gate 3, BQ-152, BQ-158, BQ-184). Scope: the person-approved
L1 and T3 path only. Not here: the L2 / policy path (ADR-0013, tickets 4 and 5), the `tilo-api` route that records the tap
(ticket 2), the WhatsApp PIN for autopilot previews (ticket 3). Sources: PRD 10.3, 10.4, 11.4, SEC-06;
`contracts/outbox.rules.md` OB-01, OB-04, OB-05; `contracts/events/data/approval.requested.schema.json`,
`approval.resolved.schema.json`; `tilo_policy.check_entry` (crossref.py) and `opens_gate` (coverage.py).

**No contract change.** Every id the gate needs can be derived in services (the mapping below), so the ticket needs no
ADR and no schema change. If the builder finds otherwise, stop and report "needs contract change: ...".

The tests run the real `Drafter`, the real `Autopilot` in production mode, the real `tilo_connectors.Outbox` and
`GmailAdapter`, and the REAL `tilo_policy.check_entry` (the `outbox_skips_ob01_evidence` monkeypatch is not used by these
files). If a name or shape below changes, update the tests in the same PR and say so.

## `tilo_channels.autopilot_gate` (new module): the id mapping

```python
def gate_card_id(autopilot_card_id: str) -> str   # a ULID (common.schema.json ulid) for approval.*'s card_id
def gate_id_for(autopilot_card_id: str) -> str    # "G<n>", 1 to 4 digits (common.schema.json gate_id)
```

Deterministic functions of the autopilot card id (`"apc_" + sha256(user + "\n" + instruction_id)[:32]`) alone: no clock,
no randomness, no store. Suggested: `gate_card_id` encodes the first 128 bits of `sha256("tilo-gate-card-v1\n" + id)` as a
26-character Crockford ULID (its first character is then 0 to 7); `gate_id_for` is `"G" + str(n)` from other bytes of the
same digest. The tests pin the shape, determinism and that distinct cards get distinct `card_id`s (2000 sampled), not the
digits. `gate_id` may repeat across cards (1 in 9999): OB-01 always matches the gate, card and outbox ids together, so a
repeat opens nothing. The ULID's time bits are hash bits, not a timestamp; no contract reads them.
The reverse lookup (gate card id back to the autopilot card) is not needed here: `Autopilot.send` is given the autopilot
card id; routing the tap to it is ticket 2.

## `tilo_channels.autopilot` (changed)

```python
class Autopilot:
    def __init__(self, *, ..., fake_evidence: bool = False) -> None   # keyword-only, default False

    def approval_requested(self, user_id: str, card_id: str) -> dict | None
        # the card's stored approval.requested part {type, authz: None, data}, or None (no part for this card);
        # a deep copy; the same answer from any instance and after a restart.

    def send(self, user_id: str, card_id: str, approval: dict | None = None) -> Outcome
```

**Preview (a).** When a card is created at L1 with a ready, sendable T2 or T3 draft (not an L2 policy card, not a card
without a Send option), the Autopilot reserves the entry id (a ULID, `ulid(ms)`) as the card's `outbox_id` (so
`Preview.outbox_id` is that id from the preview on; it was `None` at L1) and records, in the card doc, one
`approval.requested` part:

```python
{"type": "approval.requested", "authz": None, "data": {
    "gate_id": gate_id_for(card_id), "card_id": gate_card_id(card_id), "outbox_id": <the reserved id>,
    "action_type": "send_email", "risk_tier": doc["tier"],        # "T2" | "T3"
    "irreversible": True, "item": doc["item"],                     # {"artifact_id", "version"}
    "approver": None, "team_lead": None}}                          # the owner alone may answer (BQ-226)
```

It is emitted once, through `emit`, by the instance whose atomic create of the card won; a replay, a restart, a second
instance or a lost create race emits nothing and returns the same card. Same contract as every event: valid against
its data schema, no mail text in it (no subject, body, address). A redraft after Edit is a new card with its own part.

**Send (b).** `approval` is the `approval.resolved` part `tilo-api` recorded for the person's tap, supplied by the caller
(never built by the Autopilot, never taken from the model or the card):

```python
{"type": "approval.resolved",
 "authz": {"by": "person", "ref": <owner user id>, "at": <the tap time>},
 "data": {"gate_id", "card_id", "outbox_id", "option": "approve", "channel": "web" | "mobile_web" | "whatsapp",
          "pin_verified": bool}}
```

- The entry written is the card's one entry under the key `autopilot:<card id>`, with `id` = the reserved outbox id and
  **`authz` equal to `approval["authz"]`, copied, never re-stamped** (so `authz.at` is the tap time; `created_at` is the
  enqueue time). Replace `authority | {"at": created}` in `autopilot_state.Ledger.enqueue`.
- The evidence passed to `Outbox.enqueue` is the gate path of `check_entry`:
  `{"reserved_by": <the stored approval.requested part, never rebuilt at send time>, "authorised_by": <the approval>,
  "world_owner": <the card's user_id>, "policy": None, "team_lead": None, "instruction": None, "earlier_applied": []}`
  (`None` is also accepted for `instruction` and `earlier_applied`; the fixtures use `null` on a gate path).
  The tests read it through a spy on `enqueue` and run the real `check_entry` on it.
- No `approval` (None, or the old two-argument call), or one that does not open the gate (see below): `send` returns
  `Outcome("refused", None)`; it creates no entry, calls no connector, and does NOT consume the card (the decision slot
  `#decision` is claimed only for a Send that is going to enqueue), so the owner's proper approval afterwards still
  queues exactly one entry. It never raises for a bad approval (`OutboxRefused` from the outbox, which tilo-channels
  cannot import, is also accepted by the tests, by class name; nothing else).
- Replays (repeated taps, a second instance, eight racing threads) return `Outcome("queued", <reserved id>)` and leave one
  entry and one email (OB-03). A later approval for a card that already has its entry changes nothing.
- A cancelled or superseded card (existing CHN-GATE-A semantics) never gets an entry, whatever approval arrives.
- A policy part (`policy.applied`) is never an approval: refused for T2 and T3 alike (OB-04; the policy path is not built).

What the real `check_entry` refuses, and the Autopilot must therefore refuse or let the outbox refuse (the tests assert
only "no entry"): another `gate_id`, `card_id` or `outbox_id`; `option` other than `approve`; `authz.ref` that is not the
card's owner (no Approver or Team Lead is assigned on an autopilot gate); `authz.by` of `team_lead` or `policy`; a T3
card answered on `whatsapp` without `pin_verified` true; an approval whose parts break their contracts (email channel,
missing field, bad timestamp, extra field); and OB-05: an entry whose `action_type`, `risk_tier` or `item` differs from the
stored `approval.requested` (the tests change the card doc after preview).

**`fake_evidence=True` (c), tests only, never production.** The FR-CHN-11, -12, -13 and CHN-GATE-A benches send with no
approval, over a fake outbox or a `check_entry` accept-all. They opt into the old behaviour with this explicit keyword:
no `approval.requested` is built or emitted, `send` needs no approval, `Preview.outbox_id` stays `None` at L1, and the
entry is built as before (`authz` stamped now, evidence `{instruction_id, level}`). The helper
`_chn11_lib.fake_evidence_kwargs()` passes it when the parameter exists, so those benches are green before and after the
ticket; remove its `inspect` guard when this lands. The default is `False`, production wiring never passes it, and it is
not a bypass: with the REAL outbox the old evidence is refused (OB-01), as the tests assert. **Flag for the security
reviewer:** the flag must stay keyword-only, default False, and unreferenced outside tests and this ticket's docs;
consider failing construction when it is set and the outbox is a real `tilo_connectors.Outbox`.

## Not pinned (builder's choice)

How `tilo_policy` is reached from tilo-channels (it is not a dependency of the service today: add it, or validate
the approval with local checks and leave `check_entry` to the outbox), as long as every case above ends in no entry.
