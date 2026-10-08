# ADR-0028: Meeting room with agent teams (user-requested addition)

- Status: **Proposed.** Written by the architect on 2026-10-08 from the user's request of 8 Oct, relayed
  by the supervisor. It is not in the PRD, so it is logged as a user-requested addition (BQ-MROOM-1),
  and it changes two frozen contracts (the event registry and `plan`), so nothing built on it merges
  until the user says yes. **The user should check decisions 3, 6, 7 and 9 and the questions at the end.**
- Deciders: user (approval), architect (proposal), supervisor (relay)
- Requirement: USER-MEETING-ROOM (user, 2026-10-08). Touches PRD 8.1, 9.1 (Meeting Hall), 9.4 (HR-1 to
  HR-7), 9.5, 10.1, 10.4, 14.1, 16.3, 18.3 (S-09 Meeting); FR-MTR-02 to 04, SEC-16, FR-TEAM-02,
  ADR-0026, ADR-0027.
- New questions: BQ-MROOM-1 to BQ-MROOM-12 (end of `docs/open-questions.md`).

## Context
1. **The request.** For a live or finished world, a person with a team role (for example a UI/UX
   designer) calls a lead agent and the agents it supervises into an animated meeting room. There they
   talk to the lead and the agents, ask what they did and why, and ask for specific changes they are not
   happy with. Clicking an agent gives it a halo in a lighter version of its body colour. Text first;
   voice (the meet-bot speech stack and ADR-0027's `speech` role) is a stretch phase.
2. **Design direction from the user** (8 Oct, relayed): it must look like a real meeting room. A table
   with the lead and its agents seated round it, and the person seated at the head, looking down the
   table: a first-person or over-the-shoulder view from the person's seat, not a top-down map. Bots keep
   their body colours. The tilo-kit/world isometric art style is reused for furniture and bots where it
   can be; new art is a design-export gap. A speaking agent shows a cue only while its reply event is
   on screen.
3. **What exists.** PRD 9.1 lists the **Meeting Hall** among the common buildings; the room is its
   interior. The `meeting` family already has `called`, `started`, `decision`, `ended` (agent-called
   meetings with a card, PRD 9.5 and 10.2) and `minuted` (external meetings, FR-MTG). The S-09 Meeting
   screen is Must, and `design/source/INDEX.md` says its exports are partial: the World Player's join
   card and meeting events, "no full meeting-room screen". `tilo-player.js` draws a small isometric
   meeting table (`TW.box`) at a building's seat centre; `tilo-world.js` has the Meeting Hall building
   (dome roof, arches, `people` icon) and the `lt(colour, t)` lighten helper, ported as
   `apps/web/src/world/art/color.ts` `lt`. There is no room interior, chair or seated-agent art.
4. **What is missing.** PRD 10.1 says "Scoped Contributors who talk to agents directly are roadmap"
   (23.1, 23.3), so letting a non-owner talk to agents pulls a roadmap item forward on the user's word.
   No plan amendment exists: `plan.schema.json` describes one compiled plan, the harness has no replan
   step, and a world record holds one `run_id` (ADR-0026), although its writer already reopens when the
   `run_id` changes. Artifact versions continue only within one world (EV-15). The assistant panel
   (`assistant.asked`/`replied`, PPL-11b) is the precedent for a person-facing model reply: text in the
   redacted archive, refs in the event, the cheapest role, a day cap.

## Decision 1: what the room is
1. A room is the **Meeting Hall's interior** for one world and one run (the run it discusses). It has a
   convener (one person), a lead (a district Lead, or the Director), up to `max_agents` attendees the
   lead supervises, a credit cap and a turn cap.
2. **An agent in the room is its record, not a process.** Its reply is one model call over what that
   agent recorded. It does no work, calls no tool, reads no connector and keeps no state between turns
   beyond the room's own events. The room says so in plain words ("Answers come from what this agent
   recorded"). A question about *why* is answered from recorded decisions, handoff notes, questions and
   answers; where there is no record, the agent says it has none and does not invent a reason.
3. One open room per world (`open_rooms_per_world: 1`), so two people never steer one run at once
   (BQ-MROOM-5).

## Decision 2: events (registry 1.3.0; ADR-0027 takes 1.2.0)
Five new verbs in the existing `meeting` family and one in `plan`, so the family enum is unchanged. The
older `meeting.started`/`ended` keep their meanings: a type has one meaning. None is a side effect;
`authz` is null on all six. Priority `should` (a user addition, not a PRD 9.8 row; BQ-MROOM-1).

| Type | Pillar | Actor, target | `data` (text is never in an event) | World effect / HUD effect |
| --- | --- | --- | --- | --- |
| `meeting.convened` | P4 | convener (`u_`), the lead | `room_id`, `lead`, `agents`, `as_role` (owner, approver, member), `run_state` (live, finished), `credit_cap`, `max_turns` | The lead and its agents gather in the Meeting Hall / the room opens with them seated |
| `meeting.asked` | P4 | convener, the addressed agent | `room_id`, `turn`, `to`, `mode` (quick, thinking), `message_ref` | A speech bubble over the Meeting Hall / the chat shows the message |
| `meeting.replied` | P2 | the agent, the convener | `room_id`, `turn`, `mode`, `outcome` (answered, proposed_change, declined, failed), `message_ref` (null when failed), cited `units` and `artifacts`, `proposal` (units and artifact versions only) | A reply bubble / the chat shows the reply and its sources; the speaker's cue shows while it is on screen |
| `meeting.change_requested` | P4 | convener, the proposing agent | `room_id`, `proposal_id`, `to`, `units`, `artifacts` (equal to the proposal's), `as_role`, `message_ref` (the confirmed wording) | A change slip goes to the Town Hall / the chat marks it as sent to planning |
| `meeting.adjourned` | P4 | convener (reason `person`) or `system` | `room_id`, `reason` (person, idle, capped, paused, access_lost, failed), `turns`, `credits_spent` | The agents leave the Meeting Hall / the room closes and says why |
| `plan.revised` | P1 | the Director, the world | `proposal_id`, `run` (same_run, revision_run), `units` (`{id, revises}`), `credits` (estimate) | Revision blueprints appear on the buildings whose work changes / the plan gains the units |

`vis` is every attendee's district (`all` for a room with the Director). Words live in the redacted raw
archive behind `message_ref`, readable by the world's owner and the convener only (MR-12), so a district
viewer sees that a room met, not what was said (BQ-MROOM-4). `meeting_room.schema.json` 1.0.0 holds the
shared shapes, the three request bodies and the room read model; `plan.schema.json` 1.1.0 gives a unit an
optional `revises` and `change` (both or neither); rules MR-01 to MR-12 are in
`contracts/meeting_room.rules.md` and PG-13 in `plan.rules.md`.

## Decision 3: honesty (PRD 9.4)
- **HR-1.** Everything the room shows is caused by a recorded event: attendees come from
  `meeting.convened`, each chat line from a `meeting.asked` or `meeting.replied`, the "sent to planning"
  mark from `meeting.change_requested`, the closing from `meeting.adjourned`. Nothing is shown
  optimistically: the person's message appears when its `meeting.asked` is recorded.
- **HR-2.** No idle animation suggests thinking or work. After `meeting.asked`, the addressed agent holds a
  still "listening" pose caused by that event; there is no typing loop. The speaking cue (a soft pulse of
  the halo colour, or a static mouth mark in still mode) shows only while that agent's latest
  `meeting.replied` is the line on screen, and stops when the next event arrives or after its reveal.
- **HR-3.** Seating is a deterministic function of the attendee order; arriving is a fade of at most
  2 s; nothing walks unless an event says so.
- **HR-4.** A room opened from a replay is read-only and carries the replay banner; the replay re-shows
  recorded turns, never new calls.
- **HR-5.** Older clients show the six types in the Trace only.
- **HR-7.** The room authorises nothing, so it has no policy or person stamp. A revision's gates show
  their usual stamps.
- **Selection is not state.** The halo on click is UI selection (like FR-WLD-06's outline ring), drawn
  static in `lt(body colour, 0.5)`; it implies no work.

## Decision 4: how an agent answers
1. **Context, built by code.** For the addressed agent only: the run's approved brief; its own plan units
   (title, status, its events' `summary` lines); its own artifact versions (manifest and a capped text
   excerpt); its handoff notes, questions and answers; for a Lead, the same for its district's units; for
   the Director, the plan and every district's summaries. Nothing from other districts, no other room,
   no connector call, no web, no memory search outside the world. A model never picks what is read.
2. **Two roles, the person's choice.** `mode: quick` calls role `meeting` and `mode: thinking` calls role
   `meeting_thinking` (both in `config/models*.yaml`, with an NFR-25 fallback). Example profiles (the user
   chooses final models): `meeting` on `lite-31` without thinking, about 12,000 tokens in and 800 out;
   `meeting_thinking` on `flash-37` with thinking `low`, about 12,000 in and 4,000 out. Quick is the
   default; the person picks per turn.
3. **Reply shape.** A response schema: reply text (at most 4,000 characters), cited unit ids, cited
   artifact versions, and optionally a proposal (unit ids and artifact versions, nothing else). Code then
   checks every id against the grounding set (MR-06); one id outside it makes the reply `failed`, never
   silently trimmed. Text goes through the secret redactor before the archive and the screen.
4. **Metered and capped.** Each call reserves its quote first (MT-03) against the room's `credit_cap` and
   the convener's per-user cap (SEC-16, lowered by their team role, FR-TEAM-02); its cost is the
   `meeting.replied` `credits`. The run's budget pays for none of it (BQ-MROOM-6).

## Decision 5: untrusted text (PRD 16.3)
- The person's words and every prior agent output (artifacts, page extracts, mail the agents read) are
  data. They enter the prompt fenced by `tilo_harness.untrusted.neutralise` in `<<<NAME ... NAME>>>`
  blocks, after the SafetyProvider screen. A flagged message gets a `declined` reply and cannot become a
  proposal. Flagged source content is left out of the context, with a note that it was.
- The reply cannot act: it has no tool, no `ui_action` and no link the web would follow; the web shows it
  as plain text. A proposal has no field for an action, recipient, connector, risk tier or policy, so a
  planted "send this to x@example.com" cannot reach the planner as anything but words a person must read
  and confirm.
- The confirmed wording reaches the Director as untrusted instruction text, like an intake request: the
  normal brief rules apply (FR-INT-12 refusals included).

## Decision 6: a change becomes work only through the normal path
1. An agent proposes (`meeting.replied` `proposed_change`). The web shows the proposal's units and
   artifact versions and its wording, and a confirm sheet with an editable wording and the planning cost.
   The person confirms: tilo-api writes `meeting.change_requested` with the proposal's own units and
   artifacts (MR-07); the request body cannot name any.
2. The planner (the Director's planning call, `revision_plan_max_output_tokens: 4096`, reserved against
   the confirmer's per-user cap, not the room's cap) compiles revision units. Each `revises` a confirmed unit, keeps its district and role
   and gets fresh ids. The deterministic plan validator checks the revised plan (PG-01 to PG-13), the
   solver adds the units to the revised unit's building, and `plan.revised` is written.
3. **Live run** (`same_run`): the units join the running plan. **Finished run** (`revision_run`): see
   decision 8.
4. **Who pays.** A revision unit starts after the owner's in-person `budget.granted` for it (never a
   policy), except a `same_run` revision the owner confirmed whose estimate fits the remaining budget
   (MR-10). `budget.requested` already shows the remaining units and an estimate (FR-MTR-03).
5. **No side effect from the room.** Revision units' side effects go through gates or policies, the
   deterministic engine and the outbox like any unit's; tiers come from the table and never from the
   meeting; T3 still needs a person; a change request is never an L2 instruction (MR-11). The team's
   tool access levels (FR-ACC-01/02, #619, #642, ADR-0027 decision 3) apply to revision units unchanged;
   a room cannot raise them.

## Decision 7: who may convene
Checked at every request, not only at convene (MR-03). Park team roles are #642's (`Owner`, `Approver`,
`Member`, `Viewer`, BQ-DSN-01); world roles are PRD 10.1's.

| Convener | May call | May ask | May confirm a change |
| --- | --- | --- | --- |
| The world's owner | Any Lead with its agents, or the Director with the Leads | Yes | Yes; the owner's own budget decides (MR-10) |
| An Approver or Member of the team | A Lead whose district, and every attendee's district, is in their view of the world (shared scope or their districts) | Yes | Yes, as a request: no unit starts before the owner's `budget.granted` |
| A Viewer | No (Viewers spend nothing, `role_limits_minor.Viewer: 0`) | No | No |

A paused world opens no room. Losing access mid-room adjourns it (`access_lost`). The rule lives in
`config/meeting_room.yaml` `convene_roles`, not in the Team page's 8 x 4 matrix, whose rows are the
design's (BQ-MROOM-3).

## Decision 8: a finished world reopens as a revision run
A room on a finished world writes its events after `world.completed` (or `world.failed`) under the
finished run's `run_id`; asking reopens nothing. A confirmed change starts a **revision run of the same
world**: a new `run_id` whose first event is `plan.revised` (`revision_run`, `cause` the change request),
then `budget.requested` to the owner, the owner's `budget.granted`, `world.started` with that cap, the
units, and `world.completed`. Same world, so the layout, its agents and EV-15's artifact versions carry
on (a revision makes `artifact.versioned`, not a new artifact). Connections are used only if still
established at that time; an expired or revoked one goes through `connection.requested` and the owner's
consent as usual. Skill versions stay pinned to the first run's unless one was withdrawn (the Trace shows
which). No `world.requested` is written, so no L2 instruction can arise (BQ-MROOM-7).

## Decision 9: cost and limits (`config/meeting_room.yaml`, example values)
| Key | Default | Why |
| --- | --- | --- |
| `max_agents` | 6 (lead + 5) | A readable table; the schema ceiling is lead + 7 |
| `max_turns` | 20 | Schema ceiling 50 |
| `credit_cap` | 20 credits (US$0.10, about INR 8) | A quick turn is about 0.85 credits (lite-31: 12,000 in × US$0.25/M + 800 out × US$1.50/M), a thinking turn about 4.8 (flash-37: 12,000 × 0.75 + 4,000 × 3.75), so a room holds about 20 quick or 4 thinking turns |
| `max_changes` | 3 per room | Each change costs a planning call of up to about 8 credits (30,000 in, 4,096 out on the Director's profile) |
| `idle_timeout_s` | 600 | An abandoned room closes |
| `open_rooms_per_world` | 1 | Decision 1.3 |
| `convene_roles` | Owner, Approver, Member | Decision 7 |

The room's cap is also clipped to the convener's remaining per-user cap at convene. The global daily hard
cap and replay-only switch (NFR-24) apply unchanged. Prices are `config/prices.yaml`'s; the user may
change every value here.

## Decision 10: failure and abandonment
- **Provider error:** the fallback profile (NFR-25); if both fail, `meeting.replied` `failed` with no text
  and the chat says "No reply was recorded". No made-up text.
- **Cap reached:** the turn is refused before any call and the room adjourns (`capped`).
- **Idle:** the sweeper adjourns after `idle_timeout_s` (`idle`). A closed tab or lost network leaves the
  room open until then; reopening rebuilds it from events.
- **Pause all / Stop all:** open rooms adjourn (`paused`) before `world.paused` (FR-WLD-07).
- **Restart mid-call:** the pending turn closes as `failed` (idempotent by room and turn); the call is not
  resumed.
- **Planning fails** (the validator rejects the revised plan or the Director refuses the change): no
  `plan.revised`; an `alert.raised` (`needs_you`) tells the convener why. The owner holding or ignoring the
  budget card leaves the revision unstarted: the card holds by default and nothing runs.
- **Writer or archive error:** the request answers 503 and the room adjourns (`failed`) once the writer is
  back.

## Decision 11: the scene and the web
- **View.** An over-the-shoulder view from the person's seat at the head of the table: the person's
  shoulders and hands in the foreground, the table running away from the camera, the lead at the far end
  facing the person, the other agents along both sides in attendee order. Built in PixiJS v8 with the
  ported iso primitives (`art/iso.ts` `box`, `poly`) and `drawAgent` (the same body colour as in the
  world: the agent's tint, the Director's brand colour), seen from a fixed oblique camera.
- **Halo.** Clicking or keyboard-selecting an agent draws a static ring under and behind it in
  `lt(tint, 0.5)` (the lighter body colour); the chat panel scrolls to its turns. No new brand colour.
- **Design-export gaps** (the design lane draws them; never copied from third parties): the room interior
  (floor, back wall, window), the table and chairs from this camera, a seated agent pose, the person's
  seat and foreground, and the speaking cue. Until they exist, neutral role tokens from
  `design/tokens.json` and the existing `TW.box` table style stand in (BQ-MROOM-11).
- **Panels.** A chat panel (turns, sources as links to Inspect, outcome labels), a Quick/Thinking switch,
  the credits left and turns left, the change confirm sheet, and Leave. Keyboard: Tab through the seats,
  Enter selects; the chat is a live region.
- **Motion.** Reduced motion and the `still` setting: no movement at all, fades only, the cue becomes a
  static mark. Professional density: smaller figures, names on.
- **Entry points.** Inspect on a Lead ("Call a meeting"), the Meeting Hall building, and S-09.

## Decision 12: voice is phase 2
Push-to-talk input transcribed by the `speech` role (ADR-0027, through `SpeechProvider`) becomes the same
`meeting.asked` text; spoken replies need a text-to-speech role that ADR-0027 leaves out. Phase 2 adds an
optional `input: voice` to `meeting.asked` (additive) and its own ADR; audio is not kept beyond the
transcript (BQ-MROOM-12). Nothing in phase 1 depends on it.

## Decision 13: API (tilo-api)
| Route | Body (`meeting_room.schema.json`) | Answers |
| --- | --- | --- |
| `POST /v1/worlds/{world_id}/rooms` | `convene_request` | 201 the room; 403 not allowed; 409 `room_open`, `world_paused`; 429 over a cap |
| `GET /v1/worlds/{world_id}/rooms/{room_id}` | none | the room (root shape) for the owner or the convener; 404 for anyone else, byte-equal to a missing room |
| `POST .../rooms/{room_id}/turns` | `ask_request` | 202 with the turn; the reply arrives as an event; 409 `turn_in_flight`, `room_closed` |
| `POST .../rooms/{room_id}/changes` | `change_request` | 202; 409 `already_confirmed`, `not_a_proposal`, `max_changes` |
| `POST .../rooms/{room_id}/adjourn` | none | 200 |

## Consequences
- **Versions.** `events/registry.yaml` 1.1.0 to 1.3.0 (`registry.schema.json` unchanged: no new family);
  six new data schemas 1.0.0; `plan.schema.json` 1.0.0 to 1.1.0; new `meeting_room.schema.json` 1.0.0.
  All additive: every older plan, event and fixture stays valid. Generated Python and TypeScript types and
  `apps/web/src/world/registry.generated.ts` are regenerated. `test_CC_PEOPLE_FR_WLD_03` now checks a
  registry floor (the same edit as ADR-0027's PR #649, so the two merge cleanly).
- **If #649 merges first**, keep 1.3.0 here; if this merges first, #649 takes 1.4.0 on merge.
- **New rules** MR-01 to MR-12 and PG-13 have no validator yet (tickets MR-A1, MR-H2; BQ-MROOM-9).
- **S-09** lists `meeting.*` events of the run; the new types will appear there too, which is honest.
- **Config is not in this PR**: `config/meeting_room.yaml`, its loader and the two roles come with MR-H1
  (adding roles breaks the NFR-25 role-set pin until that ticket updates it).

## Implementation tickets (after the user's yes)
Lanes: harness, api, web, render can run in parallel once the contracts merge; MR-W1 can start on
fixtures before MR-A1 lands.

| ID | Owner (lane) | Size | Depends on | Scope | Security notes |
| --- | --- | --- | --- | --- | --- |
| MR-H1 | harness (intelligence-builder) | M (~350) | contracts | `config/meeting_room.yaml` + loader (refuses unknown keys, non-integers); roles `meeting`, `meeting_thinking` in `models*.yaml` + dev fakes + NFR-25 pin; `tilo_harness.meeting.reply(scope, room, turn)`: grounding set, context builder, neutralise fences, SafetyProvider screen, response schema, id check (MR-06), redactor, archive write, reply data | Security review: injection fixtures in artifacts and in the person's words; an id outside the set fails; no tool or connector reachable |
| MR-H2 | harness/planning (intelligence-builder) | M (~300) | contracts | Director revision call (capped), revision units with `revises`/`change`, PG-13 in the plan validator, solver adds units to the revised building, `plan.revised`; live append; `revision_run` start (new `run_id`, budget request, `world.started`); MR-09, MR-10 | Security review: a proposal cannot add actions or lower a tier; non-owner change never starts without the owner's in-person grant |
| MR-A1 | api (reach-builder) | M (~380) | contracts; MR-H1 for live replies (fake reply until then) | The five routes; access check per request (MR-03); turns, caps, reservations (MR-04, MR-08); one open room; idle sweeper; Pause/Stop hook; event writes through the world writer; read model from events + archive (owner and convener only, 404 byte-equal) | Security review: authz per request, IDOR on room ids, convener-only archive reads, rate limits (SEC-10), cap exhaustion |
| MR-R1 | render (world-builder, renderer art) | M (~300) | contracts | `world/art/room.ts`: room shell, table, chairs, seated agent pose from `drawAgent`, person foreground, halo in `lt(tint, 0.5)`, speaking cue; over-the-shoulder camera; renderer tests; design-gap stand-ins from tokens | None (no data access) |
| MR-W1 | web (world-builder) | L (~450, may split W1a scene host / W1b panels) | MR-R1 (art), MR-A1 (live; fixtures before) | Room screen: reducer over `meeting.*` events, Pixi scene host, chat panel, Quick/Thinking, confirm sheet, Leave, entry from Inspect, Meeting Hall and S-09; reduced motion and still; keyboard and screen reader; city world effects of the six types (FR-WLD-03 renderer tests) | Text shown as plain text only; no links followed from replies |
| MR-E1 | evals (evidence-builder) | S (~150) | MR-H1 | Room grounding set: questions about other districts decline, planted instructions in artifacts never become proposals, "why" with no record declines; credit and turn caps hold | None |
| MR-V1 | harness + web | M | ADR for TTS, MR-W1 | Phase 2 voice (decision 12) | Audio retention, consent |

## Alternatives considered
- **Reuse `meeting.started`/`ended` with an optional `room_id`.** Rejected: one type would then carry
  three meanings, discriminated by which optional field is present, with a HUD effect wrong for two.
- **A new `room` family.** Rejected: the room is the Meeting Hall's, and a new family conflicts with
  ADR-0027's `registry.schema.json` change for no gain.
- **A change becomes `world.requested` or a new world.** Rejected: `world.requested` on the web is an L2
  instruction (OB-01) and a new world loses the artifact versions (EV-15) and the layout.
- **Charging room talk to the run's budget.** Rejected: a Member could spend the owner's budget by
  talking; the convener pays for their own questions.
- **Letting the model start the revision directly.** Rejected: the planner, the validator, the owner's
  grant and the policy engine are the only way work starts; a model never authorises.
