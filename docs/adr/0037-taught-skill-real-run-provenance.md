# ADR-0037: Recorded provenance for real taught-skill runs

- Status: **Accepted by the user, 12 Oct 2026.** The contract lane's choices are the numbered decisions below.
  They are additive (`taught_skill.schema.json` 1.1.0) and the user may override any of them.
- Date: 12 Oct 2026.
- Requirements: FR-SKL-05, FR-SKL-06, FR-SKL-07.
- Predecessor: ADR-0034; rules TS-01, TS-08, TS-09, TS-11, TS-12. New rules: TS-13 to TS-17.

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

## The record and its open points (settled in "Decisions")

Define a real-run provenance record, separate from try_run_result and from
TaughtSkill. The fields are:

| Field | Evidence it records |
| --- | --- |
| org_id, skill | Existing org and taught-skill identifiers |
| version | Positive integer version pinned when the run starts |
| run_id, world_id | Existing real run and world identifiers |
| by | Verified principal whose run it is, set by the server |
| plan | Immutable snapshot of the pinned taught-skill plan |
| started_at | Server timestamp of the accepted start |
| finished_at | Nullable server timestamp of terminal completion |
| outcome | `completed` or `failed`, null until finished (decisions 2 and 3) |

The terminal enum, completion criterion, retention and snapshot shape are
settled in decisions 2 to 6. Storage is under the skill's real_runs
subcollection, with a server-owned index by caller/run for rateable-history
reads. No public route accepts provenance or completion stamps from the client.

For FR-SKL-07, record the association of an existing question-card answer
with org, taught skill, pinned version and real run. Reuse the card's recorded
decision actor and timestamp; do not copy answer text into helper metrics.
The link is a separate validated association, not a field of the card record
(decision 7).

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

## Required implementation checks

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

## Decisions (contract lane, 12 Oct 2026)

The contract: `contracts/taught_skill.schema.json` 1.1.0 (additive minor) gains `$defs`
`run_outcome`, `real_run` and `run_answer`; rules TS-13 to TS-17 are in `contracts/taught_skill.rules.md`.
Generated names: `TaughtSkillRealRun`, `TaughtSkillRunAnswer`, `TaughtSkillRunOutcome`.
No event type, registry entry, config key or other frozen schema changes.

1. **One record per run, keyed by the run id.** `real_run` is stored at
   `orgs/{org}/taught_skills/{skill}/real_runs/{run_id}`, so a run is recorded once. It holds exactly the
   fields of the table above and nothing a rating owns (no thumb, note or answer text). `by` is a user id
   set by the server: the owner for a schedule or event start.
2. **Terminal enum: `completed` and `failed`.** `outcome` and `finished_at` are null together until the
   run's own world commits `world.completed` (`completed`) or `world.failed` (`failed`), and are then set
   once together; `finished_at` is that event's `ts`. Pause all and the kill switch finish nothing, because
   BQ-90 makes Pause all final for the run and a terminal state must not be reopened. Such a run stays
   unfinished and is never rateable. A `stopped` value would be an additive minor bump if a later run-engine
   ADR makes a stop terminal.
3. **Completion criterion and rating eligibility.** A run is finished only by its own world's committed
   terminal event, never by a request, a rating or a model (TS-14). A rating is accepted only against a
   finished `real_run` of the same org, skill, version and run id whose `by` is the rater (TS-15). A thumbs
   up needs `completed`; a thumbs down is accepted on `completed` or `failed`. A run takes one rating and a
   second is refused. `good_runs` counts the runs whose one rating is an up on a `completed` run.
4. **Snapshot shape.** `plan` is the skill's `plan_step` list at the pinned version, copied verbatim
   (1 to 20 steps) and held to the same rules as the skill's plan, so a `must_ask` step keeps `ask_first`
   and `must_ask`. Nothing else of the skill is copied: name, scope, trigger, question, estimates,
   `tool_access` and captured steps stay mutable on the skill, and the runner reads the current
   `status`, `paused` and config at the start (TS-13) and again per step (TS-04, TS-05). A later fix changes
   neither the recorded `version` nor `plan`.
5. **Start guard.** The record is written in the same transaction that reads the skill's version, plan,
   `status` and `paused`; a draft or paused skill writes nothing (TS-13).
6. **Retention and reads.** One year, like the ratings and fixes that cite it (ADR-0034 table), and gone
   with the skill and with the person. The owner reads every record of their skill; anyone else reads
   only their own (TS-17).
7. **Answer association is its own record, not a field on the card.** `run_answer` is stored at
   `.../real_runs/{run_id}/answers/{card_id}` with org, skill, version, run, world, card, `by` and `at`.
   The card record is a closed, channel-facing contract shared by tilo-api and channels, and a skill link
   there would widen what channels see and need a card bump. `by` and `at` are copied once from the card's
   recorded answerer (a Decision's `answered_by.ref` for a person, `answered_by.user` for a Team Lead).
   Only a question card a person answered makes one; a gate, a consent card, a timeout default and a repeat
   answer from a Decision make none, and none is rebuilt from events. No text is copied (TS-16).
8. **Helpers report.** TS-12 counts `run_answer`, fix and rating records only, and says unavailable, not
   zero, for a month with no recorded source.

Questions logged: BQ-PROV-1 to BQ-PROV-3 in `docs/open-questions.md`.

## What builders do next

- Slice 1, store and verification: `real_runs` and `answers` in both taught-skill store adapters (the
  in-memory fake and the durable one) with a server-owned caller/run index, create-only writes, and the
  rating route's check against `real_run` (TS-13 to TS-15). Run the same
  `contracts/fixtures/taught_skill/crossref/` files; `tests/contracts/test_FR_SKL_05_real_run_provenance.py`
  holds the reference check.
- Slice 2: the answer link on the card-answer path (TS-16), then the helpers report over recorded sources
  (TS-12) and the run history bars (TS-17).
- Not here: the run engine and its start path (ADR-0034, "Not built here"). Until a runner writes
  `real_run`, history stays unavailable.

## Scope of this PR

Contracts only: the schema, rules, fixtures, generated types and acceptance tests named above. No runtime,
store, route, config, live transport, execution or deployment change.
