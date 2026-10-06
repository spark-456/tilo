---
name: schedule-channel-fr-agt-14
description: FR-AGT-14 added channel `schedule` (common 1.4.0, world.requested 1.1.0); why actor is the owner not system, the version-claim clash with PR #401, and the shared-enum widening
metadata:
  type: project
---

2026-10-06: FR-AGT-14 (scheduled runs) added `schedule` to `common.schema.json` `channel` (common 1.4.0) and a scheduled-run note to `world.requested` (1.1.0), fixture `world.requested--scheduled.json`, BQ-AGT14-1.

**Actor is the schedule's owner, never `system`.** The brief said `system`. OB-01 takes the world's owner from the actor of the world's first `world.requested`, and the crossref validator requires `world_owner` to match `^u_`. A `system` owner means nobody can open a T3 gate in the scheduled world. Orchestrator briefs can be wrong about this; check OB-01 before writing any "actor system" into a contract.

**Why 1.4.0, not 1.3.0:** open PR #401 (CC-PEOPLE-3) already claims common 1.3.0 (`record_ref.kind` gains `mail`). Before bumping a shared schema, scan open branches: `for r in $(git for-each-ref --format='%(refname)' refs/remotes/origin); do git grep -h '"x-version"' $r -- contracts/common.schema.json; done`. Two tests pinned common to exactly 1.2.0; I loosened them to `>= (1,2,0)` in the same form #401 uses, so the merge conflict is trivial.

**Shared enum widening:** `common` `channel` is `$ref`'d by `card.answer_channels` (needs-you/blocked cards are not narrowed per kind), `world.paused.channel` and `policy.notify_channel`, so `schedule` is now schema-valid there. Nothing reads it there (every consumer uses a positive list: `SIGNED_IN`, `_ANSWER_CHANNELS`, the API's local `Channel` Literal). The cleaner fix, if asked: a `request_channel` def used only by `world.requested`, or inline-narrow the three refs (no accepted-set change, one more minor bump).

How to apply: when a task says "add a value to a shared enum", list every `$ref` of it first (`grep 'defs/channel"' contracts`), and say in the BQ row what else widened.
