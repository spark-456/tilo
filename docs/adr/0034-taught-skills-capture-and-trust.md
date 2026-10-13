# ADR-0034: Taught skills, capture and trust

- Status: **Accepted, overridable** (9 Oct 2026). The additions are all additive: a new `taught_skill` contract,
  six `skill.*` event types (registry 1.4.0) and two video media types in `common` 1.7.0. The supervisor ruled
  the additive contracts a GO under the user's 12:00 authority ("Handle it yourself, i have given u full authority
  and merge ability"). The one change to an existing frozen schema, `media_type` gaining `video/webm` and
  `video/mp4`, was approved by the user on 9 Oct ~17:00: "yes to video types". The user may override any decision
  here; decisions 4, 5 and 7 and the config change in 3 are the ones to check.
- Deciders: user (approval, the model role and its prices), architect (design)
- Requirements: FR-SKL-01 to FR-SKL-07 (Should, `docs/prd-supplement-design-2026-10-06.md` 1.1), FR-ACC-02;
  PRD 8.2, 8.3, 10.4, 15.1, 16.3, 23.5; HR-1, HR-7; BQ-DSN-05; ADR-0018, ADR-0027, ADR-0029
- Contract: `contracts/taught_skill.schema.json`, rules TS-01 to TS-12 in `contracts/taught_skill.rules.md`.
  Questions: BQ-TAUGHT-1 to BQ-TAUGHT-4.

## Context
1. The Skills page (WEB-8a to 8c) runs on canned copy. Nothing stores a skill a person teaches: no capture,
   no plan steps with "Ask me first", no trigger, no learning, trusted or paused state, no rating, fix or
   try-run result, and no event records any of it.
2. `skill.yaml` (`skill.schema.json` 1.1.0) is PRD 8.2's expert skill. It has an author and a reviewer, a
   semver version, and a folder under `skills/`. Any change to it is an FR-AGT-15 proposal that a domain
   expert approves. A skill a person teaches has no reviewer and changes with every fix.
3. The event registry and `common` are frozen. `common.media_type` has no video. `providers` already
   accepts any role name and has `audio_input` (1.2.0). ADR-0029 (Accepted, PR #684) adds the `video`
   capability and `media_tokens`, and prices video tokens at `input`.

## Decisions
1. **A sibling record, not a change to `skill.yaml`.** `TaughtSkill` (`taught_skill.schema.json` 1.0.0) has
   `$defs` `try_run_result`, `rating`, `fix` and `helpers_report`. It never lives in `skills/`, the expert
   registry never loads it, and `skill.schema.json` is unchanged. Its version is an integer: 1 at
   creation, plus 1 for each fix. A run pins the version it starts with.
2. **Storage and retention.** Clients have no direct Firestore or Storage access; everything goes through
   tilo-api (TS-01, TS-02).

   | What | Where | Kept (PRD 15.1 defaults) |
   | --- | --- | --- |
   | Skill | `orgs/{org}/taught_skills/{id}` | a draft 90 days (Task); a saved skill until the owner deletes it or is deleted (Policy) |
   | Try runs | `.../{id}/try_runs/{try_run_id}` | 90 days (Run) |
   | Ratings, fixes | `.../{id}/ratings/{id}`, `.../{id}/fixes/{id}` | 1 year (Policy history) |
   | Capture media | ADR-0018 store, the owner's Desk world, origin `upload` | 90 days (Artifact) |

   Capture media obeys ADR-0018's caps: 50,000,000 bytes a file and 200,000,000 bytes for the Desk world,
   checked before any byte is stored. Erasure (FR-MEM-09) deletes a person's taught skills with them. A
   new `taught_skills` adapter covers the records, and `gcs_artifacts` covers the media.
3. **Capture to steps: a `skill_capture` role.** The four methods are `describe`, `upload`, `guided` and
   `record`. A recording is video only, with no sound, as `video/webm` or `video/mp4`. These two types are
   new in common 1.7.0, and only a capture upload stores them. The role is called twice: once to turn the
   media or text into captured steps, then once to turn the steps into Tilo's version. Tilo's version has
   plan steps that use only the owner's connected connectors' actions, and one question. Code then checks
   the result: the tool and action must exist in config, and the verb must be in the enum. Code also sets
   `must_ask`, `tool_access` and the estimates. The model's output is untrusted data (PRD 16.3): the
   person sees it before saving, and the policy engine still gates every side effect. A video cannot be
   screened or redacted, so it is stored as `unscreened` and never leaves Tilo except to the model.
   **What the user adds, as one change, after #684 merges** (#684 brings `video` and `media_tokens`):
   - `config/models.yaml`: the line
     `skill_capture: { primary: <P>, fallback: <F>, thinking: low, max_input_tokens: <N>, max_output_tokens: 4096 }`.
     P and F declare `json`, `vision`, `video` and `audio` and carry `media_tokens`. For example, P is
     flash-38 and F is lite-31. This is an example only: the user chooses.
   - `config/prices.yaml`: an `audio_input` rate for every profile the role names, because an uploaded
     video can have a sound track. lite-31 has 0.55. flash-38 has none (BQ-LW-8). There is no
     `video_input` field: ADR-0029 prices video tokens at `input`. A provider that bills video at its own
     rate needs a `providers` minor bump first.
   - `config/models.dev.yaml` gets the role on a fake profile, priced 0 in `prices.dev.yaml`.
   Until that change lands, the routes answer 503 `not_configured` for every method. The loader rule
   (`max_output_tokens` stated; the profiles have `vision` and `video`; and, while prices are set,
   `audio_input`) is a providers builder task. It goes into the `roles` description at the next
   `providers` bump, so it does not collide with #684's 1.3.0.
4. **Steps that always ask.** The `verb` enum is read, draft, write, send, post, pay, delete, share and
   book. Code sets `must_ask` for send, post, pay, delete, share and book, and for a T2 or T3 action. A
   `must_ask` step always has `ask_first`, even on a trusted skill (BQ-TAUGHT-1). While the skill is
   learning, every step that is not a read asks; while it is trusted, the steps the person switched on
   ask (TS-05). In a real run, an ask is a gate card that a person decides. A public post is T3 through
   `external_sharing`, so it needs one approval per post.
5. **Try runs.** The try run runs the current version in the owner's Desk world. Reads are real.
   - Writes go to a dry-run outbox: an outbox object that records intents and has no dispatcher. It is
     not a flag on the real outbox.
   - `side_effects` is `const 0`. A writer that finds a dispatched effect raises `alert.raised` instead.
   - An ask pauses on a question card, not a gate card, because a try run authorises nothing.
   - A sign-in page or a CAPTCHA raises a needs-you card and stops the run. Tilo never types a password
     or solves a CAPTCHA.
   - `match` is matched steps divided by total steps, computed by code. AGY-SKL-8's `match_percent` / 100
     maps to it.
   - Dev and CI use fake or replay providers (EFF-01).
6. **Fixes.** Only the owner fixes, and only the current version. A fix sets one step's text and
   `ask_first` and never its tool, action or verb. It makes version + 1, which the next run uses. A fix
   record and `skill.fixed` log it (TS-09). Teammates rate their own runs and name the wrong step
   (BQ-TAUGHT-2).
7. **Trust and pause.** `status` is `draft`, `learning` or `trusted`. `paused` is a separate flag, so
   Resume restores the status the skill had. Saving starts a skill as `learning`. Only the owner marks it
   `trusted`, and only once `good_runs` reaches the configured threshold. A good run is a finished run
   (never a try run) that the person whose run it was rated up (TS-08, BQ-TAUGHT-4). A paused skill
   never starts.
8. **Triggers.** A trigger is `on_demand`, `schedule` (a `/schedules` record id, FR-AGT-14) or `event`.
   An event trigger names an allow-listed type and at most three exact matches on id or enum fields, and
   fires only on the owner's own worlds, with no self-loops (TS-07, BQ-TAUGHT-3).
9. **Six events, ids and counts only.** The types are `skill.captured` (one per step, so the list grows
   only as steps are recorded, HR-1), `skill.version_proposed`, `skill.try_run` (one per try run, with no
   per-step event; the page shows the steps after it), `skill.state_changed` (saved, trusted, learning,
   paused, resumed: one type instead of four), `skill.rated` and `skill.fixed`. They go in the acting
   person's Desk world with owner-only `vis`, and none authorises anything (TS-11). Their data never
   holds step text, notes, file names, media or transcripts.
10. **Helpers report** (FR-SKL-07, BQ-DSN-05). It holds counts only: answers and fixes per person, with
    mistakes counted for the whole org. It is served only while the org opts in, and it is sorted by user
    id, never by a count (TS-12).

## `config/skills.yaml` (shape only; the builder creates it, and its loader checks it)
```yaml
trust: { good_runs: 5 }                    # FR-SKL-06; 5 is the design's number
capture: { max_steps: 20, max_recording_seconds: 300, max_file_bytes: 50000000 }
prior: { credits_per_step: <from replay>, seconds_per_step: <from replay> }   # estimates before any run
try_run: { max_credits: <set by the user>, max_seconds: 600 }
triggers: { event_types: [meeting.minuted, work_item.created, world.completed], max_runs_per_day: 20 }
helpers_report: { opt_in: false }          # per org, off until an Owner turns it on (BQ-DSN-05)
```

## Not built here (deliberately)
- **The run engine for a saved skill's real runs.** This means the world it runs in, how it shows there
  (`skill.loaded` takes an expert id and a semver), the schedule tick's skill target (a store field, not a
  contract), and an event-triggered start that is not a web `world.requested` (OB-01 would read that as
  an L2 instruction). This needs its own ADR before the trigger can run anything.
- **"When an invoice arrives":** no registered event marks an inbound mail (BQ-TAUGHT-3).
- **The guided walkthrough's interactive browser session.** The `guided` value is reserved.
- Sound in recordings, per-step try-run events, teammates' fixes, per-person mistakes, rankings, and
  promoting a taught skill to an expert `skill.yaml`.

## Consequences
- **Versions.** `taught_skill` 1.0.0 and six data schemas 1.0.0 are new. `registry.yaml` goes from 1.2.0
  to 1.4.0, because 1.3.0 is ADR-0028's #671; `registry.schema.json` is unchanged, since the `skill`
  family exists. `common` goes from 1.5.0 to 1.7.0, because 1.6.0 is #684's. When the two merge, take
  1.7.0: its `media_type` text already holds #684's. Python, TypeScript and
  `apps/web/src/world/registry.generated.ts` are regenerated.
- **Tests.** New: `tests/contracts/test_FR_SKL_taught_skill_contracts.py`. Changed:
  `test_FR_MEM_12_media_type_is_a_closed_enum` (11 types).
- **Builder tickets** (after the user's yes):
  - (1) tilo-api store, routes and events for TS-01 to 03, 08, 09, 11 and 12, plus the org opt-in;
  - (2) `tilo_memory.artifacts` accepts the two video types for `upload` only, checking leading bytes
    (WebM `1A 45 DF A3`, MP4 `ftyp` at offset 4);
  - (3) the providers loader rule of decision 3;
  - (4) the harness try runner and dry-run outbox (TS-04, 05, 10);
  - (5) the Skills page on the live routes.
  Tickets 1 and 4 need the security review.

## Alternatives considered
- **Extend `skill.schema.json`.** Rejected: it requires a reviewer and semver, and it is loaded by path
  from `skills/`.
- **`paused` as a status.** Rejected: Resume would have to remember the earlier status.
- **The real outbox with a dry-run flag.** Rejected: one bug in the dispatcher's filter would send.
- **Keyframe images instead of video.** Rejected: picking frames in the browser loses the order of
  clicks, and browsers record video natively.
- **A gate card in a try run.** Rejected: a gate's yes is an authorisation, and a try run has nothing to
  authorise.
