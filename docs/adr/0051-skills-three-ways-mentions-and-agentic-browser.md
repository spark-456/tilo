# ADR-0051: Teach a skill three ways, @ mentions in chat, and an agentic browser the person can watch

- Status: **Accepted** (16 Oct 2026). The owner's request, verbatim, is the approval for the feature and for every
  contract change it needs (quoted below).
- Deciders: owner (scope and approval), supervisor (relay and merge order), architect (design), security reviewer
  (tickets marked SEC in `agy-bridge/tasks/SKILLS-MENTIONS-BROWSER-TICKETS.md`)
- Requirements: FR-SKL-01 to -06 (`docs/prd-supplement-design-2026-10-06.md`), FR-ACC-01, -02, FR-CON-07, -08, -13,
  FR-AGT-03, -11, FR-PA-11, -17, -19 (`docs/prd-addendum-people-agents.md`); PRD 9.4 (HR-1 to HR-7), 10.4, 12.3, 12.5,
  16.1, 16.3; ADR-0018, ADR-0029, ADR-0034, ADR-0037, ADR-0040, ADR-0048
- Number: 0051. 0050 is the highest ADR on any branch on 16 Oct (checked `git log --remotes` and local branches).
  New rule ids BR-01 to BR-14 (`contracts/browser.rules.md`), MN-01 to MN-10 (`contracts/mentions.rules.md`),
  TS-18 to TS-21, AR-11; questions BQ-SMB-1 to BQ-SMB-9.

## Context

The owner, verbatim (16 Oct 2026): "We must be able to build skills either by screen recording, uploading a recording
or by typing it out, the agent must understand, read everything, allocate necessary tools and hands to do the task and
then lets make it such that on the chat section if we hit @ we get a list of all files folders functions and skills
that we can assign, any skill the workspace has built or personally built, it shows up there so we can tag it and ask
it to do a task. We will also need a agentic browser work where the screen is controlled by the bot like how you and
codex do your agentic browsing, etc. Do you get what I mean? fill in the rest yourself"

What exists on `live19-candidate` (77bc679b):

- **Skills.** 18 library skills in `skills/` (`skill.yaml`: `tools_allowed`, optional `tool_access`). Taught skills
  (ADR-0034, `taught_skill.schema.json` 1.1.0): `POST /v1/skills/captures` accepts only `method: describe` with text,
  `/captures/{id}/version` proposes steps through role `specialist` (`CAPTURE_ROLE`, a one-line switch to
  `skill_capture`), `POST /v1/skills` saves; code checks every step's action against config (`unknown_action`) and
  sets `must_ask`. Ratings, fixes and state routes exist (`skills_feedback.py`); `start_real_run` exists but nothing
  calls it; there is no try-run route. Visibility is owner plus current-team (`skill_store.list_visible`). The web
  TeachWizard is describe-only: "record your screen" is disabled (`EXAMPLE_OFF`); no `getDisplayMedia` anywhere.
  `packages/providers` already takes media parts (`MediaPart`, WebM/MP4 magic bytes, 10 MiB a part, 14 MiB a call,
  inline). The Chrome recorder and replay runner exist only on unmerged branches (`cx/SKILL-REPLAY-*`: a 200-event
  extension export, `skill_recording.py`, `skill_replay.py`), with an open plan (CX-SKILL-REPLAY-03) that needed this
  decision on contracts.
- **Chat.** The chat page and the bubble post `POST /intake` (multipart `text`, `mode=quick`, `files`); Quick keeps no
  record and emits no event. Home posts the same route as Thinking (`world.requested`). No request carries a
  reference, chip or mention; `mention.schema.json` is the pinboard tag of a teammate only. Reusable reads: `GET
  /v1/skills`, `GET /worlds` (team shares, ADR-0040), `GET /v1/people` (PE-20), `GET /v1/connectors`. Drive is
  `drive.file`; the picked set is in memory only until ADR-0048 ticket E (Picker) stores it.
- **Browser.** `services/browser` (`tilo-browser`, Cloud Run, internal, invoked by the harness only) has the egress
  policy, masking, login detection and the FR-CON-08 card, and a `BrowserWorker(HandsProvider)`, all tested against a
  fake engine: **there is no real browser engine** (no Playwright) and no session route; tilo-api imports the LW-08
  fetch as a library. `config/models.yaml` has no `computer_use` role (profile `flash-38` declares the capability);
  `HandsProvider` has navigate/find/click/type/tree/screenshot/upload/download. No `browser.*` event, no Browser panel
  (the Browser Station building is decoration). The policy engine (`runs.py gate()`, `tilo_policy`) and the outbox
  exist; an action missing from `config/autonomy.yaml` is T3.

## Decision

### A. One pipeline for three ways of teaching (TS-18 to TS-21, taught_skill 1.2.0)

1. **Three ways, one route.** describe (typed words, plus optional attached documents), upload (a file the person
   brings: a past recording, a PDF or an example) and record (a screen recording made on the Skills page) all create a
   capture through `POST /v1/skills/captures`; media first goes through a new `POST /v1/skills/captures/media` into the
   ADR-0034 store (owner's Desk world, origin `upload`, magic bytes, 50 MB stored, 90 days). The method values already
   exist; `upload` now covers any file the person brings (description text only).
2. **Understanding is one model call, role `skill_capture`** (ADR-0034's name; the brief's "skill_understand" step),
   Gemini multimodal through `packages/providers` only: typed text, video frames, narration audio and documents go in
   as delimited data parts. The answer is a proposal in a closed response schema: ordered steps (text, tool, action,
   verb), inputs and hosts. Code then drops any step whose tool or action is not declared (shown as "Tilo can't do this
   yet"), sets `must_ask` by the existing verb and tier rule (send, post, pay, delete, share and book always ask; T3
   always needs a person at run time), and computes what is missing ("Needs setup") from the person's connections and
   the team's levels on every read, never stored (TS-21).
3. **Hands are tools.** A step's "hands" are declared actions: Gmail, Calendar and Drive tools (ADR-0048), `web_search`
   and `fetch_url`, and the new `browse_web` (connector `web`, T1) for the agentic browser (part C). A skill with a
   `browse_web` step names its `hosts` (schema, TS-18); the person sees them on the review screen and keeps or removes
   each. `inputs` are named slots (TS-19).
4. **Recording limits.** In-Tilo recording uses `getDisplayMedia` + `MediaRecorder` (WebM, at most 300 s, about
   200 kbit/s video and 24 kbit/s Opus, so 300 s stays under the 10 MiB inline part); nothing leaves the browser while
   recording (FR-SKL-01). Sound is recorded only when the person turns Narrate on, and is read only when the role's
   profile has an `audio_input` price (TS-20; this amends ADR-0034's "no sound"). A file over 10 MiB is stored but not
   read until Vertex reads it from Cloud Storage by URI (BQ-SMB-5).
5. **Review, save, share.** The person edits the draft and saves it as just me or a team skill (existing scope rules,
   TS-01). Try runs and ratings stay as ADR-0034 and ADR-0037 define them.

### B. @ mentions (mentions.schema.json 1.0.0, MN-01 to MN-10)

6. **One read API.** `GET /v1/mentions?q=&kinds=&cursor=&limit=` answers a `Mentions` page of `option`s (ref, label,
   detail, scope mine/team/library, state ready/needs_setup/limited) across nine kinds: skill, taught_skill, file,
   drive_file, drive_folder, world, person, connector and tool ("functions"). It reuses the existing reads and their
   visibility, filters by substring in code, makes no model call and sits behind the SEC-10 limiter.
7. **A message carries refs, never content.** The composer inserts a chip per pick; the request sends `refs` (at most
   10, ids only, a file pinned to its version) as a field of `POST /intake`. tilo-api resolves every ref again as the
   sender; a ref the sender may not read gets the same 422 as a missing one (MN-02). Quick with refs answers
   `switch_to_thinking` (MN-06).
8. **What a tag does** (MN-04, MN-05): a tagged skill is pinned and loaded for the run (a taught skill's steps become
   the plan outline); files become inputs; Drive items are read with `read_file`/`list_files` (folders show only files
   picked or made by Tilo, state `limited`); a world gives its delivered results; a person gives a display name only;
   a connector or tool is a preference inside the allowlists. A tag never widens a level, a tool or a host.
9. **No new event.** Provenance is `skill.loaded`, the input artifact and `data.transfer` in (MN-09).

### C. The agentic browser (browser.schema.json 1.0.0, BR-01 to BR-14, registry 1.7.0, artifact 1.3.0)

10. **Where each part runs.** tilo-browser gets a real engine (Playwright Chromium) behind four internal routes
    (`POST /sessions`, `/sessions/{id}/inspect`, `/sessions/{id}/act`, `DELETE /sessions/{id}`, bodies in
    `browser.schema.json`). tilo-api runs the loop (it already runs units and holds the store, the policy engine and
    the event writer) and makes the model call through `packages/providers`; tilo-browser keeps no model, data or
    secret access (infra/ACCESS.md). Infra: tilo-browser invoked by `api` as well, 2 GiB, one instance (sessions live
    in memory; a restart is `session_lost`).
11. **The loop.** Screenshot, then the `computer_use` role proposes one `$defs/action` (navigate, click, type, scroll,
    key, back, wait, done, ask; points on a 0 to 999 grid, the provider's own convention), then code checks it
    (BR-01 to BR-08: schema, egress, inspect-then-act with a digest, no secure field or secret text, commit test, no
    downloads, login wall, step and credit caps), then tilo-browser runs it and answers a masked screenshot, then
    tilo-api stores the frame (artifact origin `browser`, PNG, AR-11) and writes `browser.acted`.
12. **Commits need a person.** A step that would submit, buy, send, post or delete (BR-05, decided by code from the
    element's facts and a closed word list; the provider's confirmation flag can only add one) is refused with
    `needs_person` in the first release. Ticket B3 then routes it as `browser_commit` (T3): gate card with the
    before-frame pinned, approval by a person, outbox entry, dispatcher act with `outbox_id`, `data.transfer` out. A
    unit with private workspace data treats every `type` as a commit.
13. **Allowlist.** Hosts typed in the request, a used skill's hosts, each with `*.host`, and, for a unit holding no
    private data, the hosts of this run's recorded `web_search` results (at most 10). Every request a page makes to
    any other host is blocked and logged (FR-CON-07), subresources included (BQ-SMB-1, BQ-SMB-2).
14. **Watching and control.** The Browser panel (World view; the chat links to it) shows only frames named by
    recorded `browser.*` events and the step log (HR-1). The world owner can Pause, Resume, Stop or Take over
    (`control_request`; Take over ends the session and returns the page's origin and path so the person continues in
    their own browser, since Tilo never holds a signed-in session). Each op is a `browser.controlled` event.
15. **Caps and cost.** `config/browser.yaml` (`BrowserConfig`): at most 3 sessions per world (PRD 12.3), 60 steps and
    2,000 credits per session as ceilings; shipped values lower. One frame per call by default. Dev and CI use the
    fake engine and a fake or recorded `ComputerUseProvider`; no paid call without `LIVE=1`.
16. **Provider interface (architect-owned, written by ticket B1b).** In `tilo_providers.interfaces`, beside
    `ModelProvider` and with the same synchronous convention:
    `ComputerUseRequest(role, goal, frames: tuple[bytes, ...], url, history: tuple[str, ...], page_text,
    max_output_tokens)`, `ComputerUseProposal(action: dict, needs_confirmation: bool, usage)`, and
    `ComputerUseProvider.propose(request) -> ComputerUseProposal`, reached through the router (role, caps, metering,
    fallback). The caller validates `action` against the contract; the adapter maps Gemini's computer-use function
    calls to it and refuses the rest. `HandsProvider` stays as it is (FR-CON-13).

### Contract changes (this ADR's PR)

- New `browser.schema.json` 1.0.0 (root `BrowserConfig` for `config/browser.yaml`, in `CONFIG_SHAPES`; `$defs`
  action, facts, session bodies, control bodies), `browser.rules.md`.
- New `mentions.schema.json` 1.0.0 (root `Mentions` page; `$defs` ref, refs, option, list_request, ref_error),
  `mentions.rules.md`.
- Events: family `browser` (`events/registry.schema.json` 1.3.0), `browser.started`, `browser.acted`,
  `browser.controlled`, `browser.stopped` (registry 1.7.0), none a side effect.
- `artifact.schema.json` 1.3.0: origin `browser` (PNG only, unit and agent set, no sources, no key); AR-11.
- `taught_skill.schema.json` 1.2.0: optional `inputs`, `hosts` (required with a `browse_web` step); TS-18 to TS-21.
- All additive (minor). Config lines (`connectors.yaml` `browse_web`, `browser_commit`; `autonomy.yaml` T1 and T3;
  `models.yaml` roles `skill_capture`, `computer_use`; `config/browser.yaml`) land with their adapters (tickets S1,
  B1b, B1c), never before.

## Consequences

- Teaching works the same three ways and every draft is checked by code; nothing in a recording or text can add a
  tool, host, recipient or approval. Skills can now drive a browser, and only on hosts the person kept.
- The chat can hand any visible skill, file, world, teammate or tool to a run by id, with no leak path through the
  picker or the resolver.
- The browser shows real, recorded frames; it reads and navigates on its own, and stops for a person at every commit.
  Strict egress means some sites load without third-party images or scripts (BQ-SMB-1).
- Risks: Chromium on Cloud Run (memory, cold start); single-instance sessions; provider availability of a
  computer-use model in `asia-southeast1` (the user picks the model and its price, BQ-SMB-4).
- Not in this ADR: replay of the extension's event export (`cx/SKILL-REPLAY-*`, still a separate plan), signed-in
  sessions, file upload or download by the browser, desktop hands (PRD 12.5 roadmap).

## Open questions (rows in `docs/open-questions.md`)

BQ-SMB-1 strict egress for subresources; BQ-SMB-2 search-result hosts; BQ-SMB-3 narration; BQ-SMB-4 the computer-use
model and its fallback; BQ-SMB-5 recordings over 10 MiB; BQ-SMB-6 Drive folders and picks; BQ-SMB-7 frame retention;
BQ-SMB-8 who watches a shared world's browser; BQ-SMB-9 commit words in code.
