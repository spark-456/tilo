# CHN-WIRE-4: public API pinned by the policy-port tests (overridable)

CHN-WIRE-4 (FR-CHN-11; issue #307 plan ticket 4 "Policy port for L2", issue #325 follow-ups, issue #256 gate 3; BQ-242 to
BQ-248). Scope: replace the autopilot's `AutonomyPolicy.level(user_id, ACTION_TYPE)` hint with a real decision through
`tilo_policy.decide`, in `services/channels` only, landing BEHIND `coverage.L2_ACTION_RECORDED = False`: against the real
engine an L2 candidate still always degrades to L1 until the user approves ADR-0013 (Proposed; BQ-57; these tests never
flip the flag and never assume the ADR). Not here: the OB-01 policy-path evidence for the outbox (ticket 5: the real
`check_entry` still refuses the L2 policy entry, and a test pins that), `action_type` on cards, the instruction event, the
production reader of policy records (the tests give the engine a thin pass-through in `_chn_wire4_lib.EnginePolicy`).

**No contract change, no ADR.** `policy.applied` (`contracts/events/data/policy.applied.schema.json`) already exists. If the
builder finds otherwise, stop and report "needs contract change: ...".

## The port (`tilo_channels.autopilot`)

```python
class AutonomyPolicy(Protocol):
    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision: ...  # new
    def level(self, user_id: str, action_type: str) -> tuple[str, str | None]: ...  # legacy hint, compat only
```

- **Compat (BQ-244).** A policy object with a callable `decide` is asked `decide` and NEVER `level` (a test object with both
  records `level` calls: none). One without `decide` is asked `level()` exactly as today and everything about that path is
  unchanged (all existing FR-CHN-11/12/13, CHN-GATE-A/B/C and CHN-WIRE-1 benches stay green with no helper edits).
- **The question.** For a ready, sendable T2 draft of the owner's own non-blank instruction with no modifier (as today: T3,
  a blank instruction, an unsendable draft and every redraft after Edit are never put to the policy and never L2), once, at
  decide time, `policy.decide(user_id, proposal)` with `user_id` the card's user (the world owner) and a
  `tilo_policy.Proposal` whose fields equal what the entry will say:
  `world_id` = the Autopilot's world; `action_type` "send_email"; `connector` = the Autopilot's connector (gmail);
  `district` = the new keyword below; `destination` = `thread_id`; `item` = `{"artifact_id", "version"}`;
  `facts` = `SideEffectFacts(recipients=tuple(dict.fromkeys(to + cc)), known_recipients=<the same>)` and every other fact
  false/empty (an L2 candidate has no new recipient, attachment, money term or safety flag, or it would be T3);
  `credits` >= 0 (0 until metering reaches the Autopilot); `instruction` is builder's choice (None until ticket 5).
- `Autopilot.__init__(..., district: str = "D1")`, keyword (BQ-242).
- **Usable decision (BQ-248).** Only `tilo_policy.Decision` with `outcome == "run_after_undo"`, `tier` equal to the card's
  (T2), `level == "L2"`, `modifiers == ()`, a valid `pol_...` `policy_id`, `authz == {"by": "policy", "ref": <policy_id>,
  "at": <valid UTC millisecond timestamp, not in the future beyond a few seconds of skew>}`, `undo_window_s` an int >= 1
  (not a bool). Everything else (a raise, None, a dict, any other object, a gate, draft_only, run, a different tier/level,
  person or team_lead authz, a ref that is not the policy id, a bad/unreadable/future `at`, a bad window, extra modifiers)
  gives an L1 card (below), never an exception out of `preview`.

## `Autopilot.policy_applied(user_id, card_id) -> dict | None`

The card's stored `policy.applied` part (a deep copy), the same from any instance and after a restart; None for a card with no
live decision (an L1 card, a dropped card, a legacy-hint card):

```python
{"type": "policy.applied", "authz": <the Decision's authz, copied>,
 "data": {"policy_id", "gate_id": gate_id_for(card_id), "outbox_id": <the card's reserved id>, "action_type": "send_email",
          "connector", "destination": thread_id, "district", "risk_tier": "T2", "level": "L2",
          "instruction_id": DraftContext.instruction_id, "undo_window_s": <the Decision's>, "item", "credits": >= 0}}
```

It validates against `policy.applied.schema.json` (the `instruction_id` must be a ULID, so a non-ULID instruction id means
the part is invalid and the card is L1, BQ-243). It is stored in the card doc by the same atomic create that fixes the card
(before any enqueue) and emitted through `emit` exactly once, by the instance whose create won (replay, restart, second
instance, a lost create race and eight racing instances emit nothing more); no `approval.requested` is raised for an L2
card. The Decision's own `authz` dict is copied (a later mutation of the stub's object changes nothing).

## The entry and the card at L2

- The entry's `authz` is the stored part's `authz`, copied, never `now`; `undo_window_s` is the stored decision's (30, 60, 90
  and 600 are tested, not only 60); `scheduled_at = created_at + undo_window_s` (OB-02); `id` = the reserved id;
  `Preview.undo_window_s`/`scheduled_at`/`outbox_id` match. A decision stamped before the enqueue (e.g. 5 s earlier) keeps
  its time in the entry's `authz.at`.
- **Binding (BQ-247).** The decision is bound to the facts it was made for (recipients as in the entry, destination, item,
  tier, modifiers). If the card, when first enqueued, says anything else (a Cc added, recipients replaced or removed, another
  thread, a new item version/artifact, tier T3), no entry is written: the card drops to L1.

## Late first enqueue (BQ-245, BQ-246)

`tilo_channels.autopilot.DECISION_MAX_AGE_S`: an int, `0 < value <= 60`. The tests read it and use `value - 1` and `value + 1`
(the boundary itself is builder's). Applies only before the card's entry exists (outbox key not stored, no recorded stop):

- age <= bound: the stored decision is used; the policy is not asked again.
- age > bound (or the policy state is unknown): `decide` is asked again with the stored proposal (equal to the first). A clean
  `run_after_undo` replaces the stored decision (its `policy.applied` is stored and emitted; the entry's authz is that new
  stored one, `authz.at` = the new decision's time; the undo window restarts). Anything else, or a raise: **drop to L1**.
  Concurrent late replays agree on one stored decision, and the entry never carries a losing one.
- Once the entry exists (even sent), a replay or Send any time later changes nothing and asks nothing.
- **Drop to L1:** same card id and reserved `outbox_id`; `level` "L1", `undo_window_s` 0, `scheduled_at` None;
  `policy_applied()` returns None; the card's `approval.requested` (CHN-WIRE-1 shape, the reserved id) is stored and emitted
  once by whoever records the drop; `send()` without the owner's approval is refused; no entry, nothing sent however long the
  clock runs; later replays from any instance neither ask again nor raise a second gate.
- A Cancel recorded before the late enqueue still wins (CHN-GATE-A unchanged): no entry ever, `stop_state` "cancelled".

## At the first decision: what is not L2

Every unusable answer above (same list) at decide time: an L1 card with `outbox_id` reserved, one `approval.requested`
(emitted once), no `policy.applied`, no entry. With the REAL `tilo_policy.decide` and a contract-valid L2 policy that covers
the send, while `L2_ACTION_RECORDED` is False the decision is `gate` / `l2_instruction_required`, so the card is L1 and the
outbox is empty; with a policy scoped to another district it is `gate` / `no_covering_policy` (the district really reaches the
engine). The world owner stays the trusted `world_owner` (a non-owner, a missing owner, a failing lookup: `PermissionError`
before the policy is asked or anything recorded). With the REAL outbox and the REAL `check_entry`, a fake engine's
`run_after_undo` still produces no entry and no mail (ticket 5 builds that evidence); whether `preview` raises
`OutboxRefused` or drops the card is builder's choice.

## Not pinned (builder's choice)

The production adapter (reads the owner's policy records, the owner's `policy.applied` parts across all worlds, the world
owner; calls `tilo_policy.decide` with `load_risk_table()`; any read failure raises, which the Autopilot turns into L1), the
freshness constant's value within (0, 60], the clock-skew allowance, the slot names used for the create-once decision, and
how a re-decision is serialised across instances.
