# ADR-0037: Recorded provenance for real taught-skill runs

- Status: Accepted (user, 12 Oct 2026); builders start after the architect's contract PR merges.
- Date: 12 Oct 2026.
- Requirements: FR-SKL-05, FR-SKL-06, FR-SKL-07.
- Predecessor: ADR-0034; rules TS-01, TS-08, TS-09, TS-11, TS-12.

## Problem

On phase0-stack `7df8056a`, the taught-skill store persists `TaughtSkill`
documents only. Its interface has put, get, list_for_owner and list_visible.
Neither adapter reads or writes ratings, fixes or real-run provenance.
`GET /v1/learn` explicitly returns an empty needs_rating list and null helpers.

The accepted rating contract identifies a skill, integer version, run_id and
person. It does not establish that the named run belongs to that person,
finished, or ran that version of that taught skill. A request body cannot
provide that evidence. TaskRecord holds owner, world_id and run_id but no
taught-skill/version association. The harness SkillRegistry loads and pins
expert skill.yaml files, not records from the taught-skill store.

Consequently, a world.completed event alone cannot make a run rateable as a
taught-skill run. A try-run result cannot substitute for a real run (TS-08).
Unrecorded history must remain unavailable rather than becoming zero bars.

## Proposed addition requiring contract-lane review

Define a real-run provenance record, separate from try_run_result and from
TaughtSkill. Proposed fields are:

| Field | Evidence it records |
| --- | --- |
| org_id, skill | Existing org and taught-skill identifiers |
| version | Positive integer version pinned when the run starts |
| run_id, world_id | Existing real run and world identifiers |
| by | Verified principal whose run it is, set by the server |
| plan | Immutable snapshot of the pinned taught-skill plan |
| started_at | Server timestamp of the accepted start |
| finished_at | Nullable server timestamp of terminal completion |
| outcome | Terminal enum and its relationship to rating eligibility need review |

The contract lane must settle the terminal enum, completion criterion,
retention and exact snapshot shape before builders write this record.
Proposed storage is under the skill's real_runs subcollection, with a
server-owned index by caller/run for rateable-history reads. No public route
accepts provenance or completion stamps from the client.

For FR-SKL-07, record the association of an existing question-card answer
with org, taught skill, pinned version and real run. Reuse the card's recorded
decision actor and timestamp; do not copy answer text into helper metrics.
The contract lane must decide whether the provenance link belongs in the
card record or a separate validated association. Do not change either here.

## Existing contracts that do not need replacement

- Rating and fix records, and skill.rated / skill.fixed data already exist.
  Durable adapters may use ADR-0034's ratings and fixes subcollections.
- Fixes can be independent of a rating (`rating: null`); their owner-only
  current-version mutation is implementable on existing contracts.
- Status and paused fields and skill.state_changed already exist. Owner-only
  pause/resume and Keep learning mutations need no new schema. Positive trust
  requires verified, deduplicated good-run ratings rather than seeded counts.
- config/skills.yaml may add ADR-0034's trust.good_runs = 5 and helpers_report
  opt_in = false. The report remains unavailable while opt-in is off or its
  sources are not recorded. Counts must not imply missing sources are empty.

## Required implementation checks after review

Tests first: another person cannot rate a run; an unfinished, unknown,
foreign-org or try run is refused; the pinned version survives a later fix;
each finished run contributes at most once to good_runs. Fix/version/log writes
must be atomic and reject concurrent stale versions. Events contain only the
existing ids/counts/enums and follow TS-11's owner Desk envelope.

Before any taught-skill runner starts, it must read current paused/status and
refuse a draft or paused skill. Pausing a skill record alone does not prove
that start guard. No runner, trigger, try-run or replay work is introduced here.

Helpers tests require org opt-in, sorted user ids, no content or ranking,
org-wide mistakes and recorded answer/fix sources. History and live UI writes
must show persisted server results and honest unavailable states on failures.

## Scope of this PR

Proposal only. No frozen contracts, event registry, runtime, config, live
transport, execution or deployment changes. The 05:00 supervisor NOTICE
requires an ADR before missing schema additions; this draft provides the
specific prerequisites without treating them as accepted decisions.
