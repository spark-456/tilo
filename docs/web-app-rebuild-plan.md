# Web app rebuild plan: Park City handoff (phase 0 proposal)

Status: APPROVED by the supervisor on 6 Oct 2026 with the decisions recorded in section 9 (BQ-WEB-1 to BQ-WEB-6).
Sources read: `design_handoff_tilo_web_app/` (README, PROMPTS, inventory, tokens.css, `design/tilo-app.js`, `tilo-park.js`, `tilo-world.js`; PR #442), `apps/web/CLAUDE.md`, `src/router.ts`, `src/screens/{meta,routes}.ts(x)`, `src/App.tsx`, the honesty scan (`src/honesty/`, `test-support/honestyScan.ts`). The `.dc.html` pages are read page by page in their own phase, not here.

## 1. What changes and what stays

The handoff is 9 pages in one shell. `apps/web` today is a flow shell (S-01..S-04 with the Pixi stage and rails), 23 routed `S_NN` screens, a People set (S-26..S-29) and an honesty layer (HR-1..HR-7, FR-WLD-09 static scan, fixture banners). Stack stays: React 18, TS, Vite, Vitest, Playwright, the History API router (no new dependency).

Strategy: **build the Park shell beside the old app, cut over once, delete nothing before the list in section 8 is approved.**

- All new code lives in `apps/web/src/park/`. It adds no import from `screens/` or `world/` except the API client and `useClient` seams.
- Park pages are served under `/park/<page>` (History API, same router style as today) until the cutover PR. The design's `#home`-style hash routes are mapped to these paths; the `AppCtx.go(page, params)` contract is kept as is, and `go` writes the path.
- The cutover PR (after wire-up and polish) changes the route table so `/`, `/worlds`, `/world/:id`, `/team`, `/connectors`... resolve to the Park pages and the kept screens stay reachable (section 3). It is its own PR and needs approval.

## 2. Folder structure (`apps/web/src/park/`)

```
park/
  tokens/park.css            handoff tokens.css, scoped to [data-park], night on [data-time="night"]
  engines/
    world.ts                 port of tilo-world.js (world map, buildings, agents), takes an `h` factory
    park.ts                  port of tilo-park.js (city backdrop: static scene + live cars/walkers layers)
    kit.ts                   port of the tilo-app.js render kit, memoised by key (cache kept)
    icons.ts                 kit.icon set (20x20 viewBox, 2px round stroke)
    types.ts                 H factory type, Scene, Pin, AgentExpression, ...
  api/
    types.ts                 typed shapes of every fixture (section 5)
    fixtures/                the tilo-app.js data, split per page (user, decisions, worlds, plans, skills, learn, ledger, agenda, team, connectors, notifications)
    index.ts                 `Api` interface, every method returns a Promise<{ data, source }>
    fixtureApi.ts            returns fixtures with source "fixture"
    liveApi.ts               stub for the real tilo-api calls; each method not backed yet rejects with `NotBuilt`
  app/
    AppCtx.ts, store.ts      the AppCtx contract; one store holding dec, added, prefs, toast, read, menu, wl
    router.ts                parkRoute(pathname) <-> { page, params }; go() with the transition
    AppShell.tsx             backdrop, nav, popovers, page outlet, toast, loaders, boot
  components/                core components (section 4)
  shell/                     CityBackdrop, TopNav, NotificationsPopover, AccountMenu, WorldLoader, BootSplash, PageTransition
  pages/                     Home, Worlds, World, Ledger, Skills, Agenda, Team, Profile, Connectors (each a folder: page + its local components + tests)
  dev/Components.tsx         /dev/components, every core component in day and night (dev build only)
```

Tests sit beside the code (`*.test.ts(x)`), names carry the ticket ID (section 7). Playwright specs go in `e2e/park/`, each run on its own `TILO_WEB_PORT`.

## 3. The 9 design routes against the existing screens

| Design route | Park path | Existing screen(s) it overlaps | Plan |
| --- | --- | --- | --- |
| `#home` | `/park/home` | S-01 Start (`/`), S-02/S-03 flow, S-06 Needs you | Park Home's composer calls the same intake API as S-01 in live mode (`/task/:id/understanding` and `/approaches` stay and are linked from the plan step). S-01 is replaced at cutover, S-02/S-03/S-06/S-07 stay |
| `#worlds` | `/park/worlds` | S-14 Worlds list and replays (`/worlds`) | Replaces S-14 at cutover (list, filters, search move over; S-14's replay entries stay reachable from the World page) |
| `#world/<id>` | `/park/world/:id` | S-04 World with HUD (Pixi stage), S-05, S-10, S-11, S-12 | **Open design question A.** The Park map is the SVG art engine and its animations are cosmetic. The Pixi stage is the event-driven, honest view of a run. Proposal: the Park World page is the overview (map, districts, activity, gate card, spend) and carries links "Open live stage" (S-04), Story (S-10), Trace (S-11), Delivery (S-12) and Inspect (S-05). Nothing of S-04..S-12 is removed |
| `#skills` | `/park/skills` | S-13 Library and Memory Vault, deferred S-20 Skills library | Fills S-20. S-13 stays (memory vault part) |
| `#ledger` | `/park/ledger` | none (S-23 explains estimates; the credits meter is in the HUD) | New. Linked from the HUD meter and S-23 |
| `#agenda` | `/park/agenda` | S-29 Calendar, S-28 Pinboards, S-26 Meetings, S-27 My plate | Supersedes S-28 and S-29 visually (pins and week grid). S-26 and S-27 stay, linked from the event panel and the Home panel. Data from `people/` (`calendar.ts`, `pins.ts`, `plate.ts`) is reused where it matches, else typed fixtures |
| `#team` | `/park/team` | S-18 Team Lead console (`/team`) | Replaces S-18's route at cutover; S-18's console view stays under its own path, linked from "When agents stop and ask" |
| `#profile` | `/park/profile` | S-22 Settings, S-15 Autonomy, S-16 Channels, S-24 Pilot | Replaces S-22. Notifications tab links to S-16 Channels, Security tab to S-15 Autonomy. S-24 stays |
| `#connectors` | `/park/connectors` | S-19 Connections, S-08 consent sheet | Replaces S-19's list view at cutover. S-08 consent stays and is opened from "Connect" and "Reconnect" |

Not covered by the handoff and kept untouched: S-05, S-07, S-08, S-09, S-10, S-11, S-12, S-13, S-15, S-16, S-17, S-21, S-23, S-24, S-26, S-27, the stage (`stage/`, `world/`), the needs-you rail, the access gate and the assistant panel. The Park shell gets a "More" entry in the account menu that opens the existing `/more` list.

## 4. Component list (core first, exactly as the README table)

Button (primary, secondary, needs), SegmentedControl (plain, sliding thumb), Switch, StatusChip, SummaryPill, KpiTile, ListRow, ArtTile, Card, PageSheet, Toast (with action, 4.2 s), Popover/Menu, ModalScrim. Plus shell parts: TopNav (logo tile, 6 tabs with Worlds badge, day/night, bell, avatar, progress bar), NotificationsPopover, AccountMenu, CityBackdrop, WorldLoader, BootSplash, PageTransition. Page-local components (Composer, PlanSteps, MiniWorldMap, SpendChart, Donut, Sparkline, Histogram, ActivityList, TeachFlow, ToolLevelControl, PinBoard, WeekGrid, EventPanel, MembersTable, MatrixTable, ConnectorTile, ScopeScale) are built in their page phase and promoted to `components/` only if a second page uses them. Focus ring, Escape and reduced-motion behaviour live in the core components.

Rules applied: UX-1 (one filled primary button per screen) is checked per page; UX-7 (no streaks, fake urgency): the amber "Needs you" treatment is a state, not a countdown; the design's strings are used verbatim from `inventory.md`, and any string there that breaks UX-6/UX-7 is listed in the page ticket, not silently changed.

## 5. TypeScript port of the engines and the fixture types

Engines (`tilo-world.js` 471 lines, `tilo-park.js` 154, `tilo-app.js` 300; all three are the user's own prototypes, `support.js` is never ported): each file becomes a module that exports factories taking `h` (`React.createElement`-compatible) and returns typed ReactNode trees, so no `dangerouslySetInnerHTML`. Same names, same numbers, same memo key scheme (`kit(h)` caches agents, buildings and worlds by key). No `window.*` globals, no `eval`. The renderer cache for the backdrop is one `Map<"time|motion", SVG>`. Ported files get a header "ported from design_handoff_tilo_web_app/design/<file> (user's prototype, ADR-0003)".

Fixture types (`park/api/types.ts`), one per README data-model entry: `User`, `Today`, `Decision {k, world, title, body, yes, icon, done}`, `World` (all optional fields typed: plan, districts, activity, runs, row, single), `Tier`, `Plan` (city layouts for `kit.world`), `Skill {id, name, team, owner, role, runs, rate, last, improved, st, first, now, from, tools: [name, level][], used, steps, ask?}`, `Learn {rates, reviews, helpers, tools}`, `Ledger {budget, spent, forecast, daily[24], by{world|tool|role}, tx[], runs, waits, memory, hours, activity[]}`, `Agenda {days, wkend, today, start, end, now, events[], slots[], details{}, pins[]}`, `Team {people, rules, matrix, roles, coverage}`, `Connector`, `Notification`, `AppCtx`, `DecisionKey`, `PageId`. The same types go through an `Api` interface (`decide/undo, startWorld, answerQuestion, rateRun, markTrusted, pauseSkill, setToolLevel, saveSkill, bookSlot, pins, invite/role/remove, addBackup, prefs, reconnect/sync`), every method returning a Promise. Fixture strings are verbatim; fixture arithmetic (the Ledger totals, forecast, the `dec` effects) is checked by unit tests so the numbers cannot drift from each other.

## 6. Honesty (HR-1..HR-7) and fixtures

1. **Fixtures never pass as live.** Every `Api` result carries `source: "fixture" | "live"`. The shell shows a persistent chip in the nav, "Sample data", whenever any visible page reads a fixture result; its popover says "Northwind Ops is a fictional team. Amounts are examples (£), dates are September 2026." Each fixture-backed page also keeps the chip next to its title and the HR-4-style line "Sample data recorded for the demo, not your workspace". On `tilo-dev` and `tilo-demo` (deployed mode, `deployedMode.P0-07c.test.ts` already pins the dev/demo split) the only client is the fixture client until each endpoint exists; a page whose endpoint is `NotBuilt` shows "Not connected yet" (the existing `EmptyState` pattern), never sample numbers as if real. A test renders every page in deployed mode and asserts the chip or the empty state is present.
2. **Ambient animation.** The city's cars and walkers and every CSS keyframe (`tiloSlide`, `tiloFade`, `tiloGhost`, `tiloPulse`, the spinners) are animations with no recorded event. `src/honesty/animation.static.test.ts` fails on animation APIs outside `choreographer.ts` unless `test-support/honestyScan.ts` lists the file with a reason. Proposal: (a) ambient scenery (cars, walkers, boot slide) and UI feedback (spinners, toast, transitions) go on the allowlist as **non-agent motion**, each with its reason; (b) nothing that depicts an agent working (agents on the Home map, the Teach "try run", the Agenda finding pulse) animates unless a fixture event stream drives it, and fixture-driven agent motion is labelled "Sample" and follows HR-4; (c) motion `still` is the default under `prefers-reduced-motion`. **This edits the honesty allowlist, so it needs an ADR and your approval before the shell phase.**
3. The Home map pins and the Worlds/World agent art show state only from fixture or event data (HR-1); the "Live now" label on Home is replaced by "Running" in live mode and "Sample run" in fixture mode (open question B).

## 7. Phases, branches, PRs and checks

Each phase: branch `feat/WEB-<n>-<slug>` off `origin/phase0-stack`, tests first (`tests/WEB-<n>`), Sonnet builder, reviewers per the supervisor's list, report with PR number, verdicts and the `tests/repo` count. Ticket IDs `WEB-0..WEB-14` are mine, there is no PRD ID for the redesign; acceptance tests carry them (`test_WEB_03_...` style names in Vitest titles). Requirement IDs they also touch: UX-1..UX-9, FR-WLD-09, NFR-01 (route chunks), PRD 18.2 type/space tokens.

| Phase | Ticket | Content | Reviews |
| --- | --- | --- | --- |
| 0 | WEB-0 | this plan (docs only) | supervisor approval |
| 1 | WEB-1 | tokens (scoped), fonts check, `api/` + typed fixtures, engines and kit ported (3 PRs if the diff needs it: types+fixtures, world+park engines, kit+icons) | code-reviewer, security-reviewer not needed |
| 2 | WEB-2 | core components + `/dev/components` | design-critic on the components page, day and night |
| 3 | WEB-3 | AppShell: backdrop, nav, popovers, router, AppCtx store, transitions, world loader, boot, toast with Undo; honesty ADR change | code-reviewer, design-critic, qa-breaker |
| 4-12 | WEB-4..12 | Home, Worlds, World, Ledger, Skills, Agenda, Team, Connectors, Profile (the README order, Profile last as in PROMPTS) | design-critic against the served `.dc.html` at 1440 and the narrow width, day and night, per page; code-reviewer |
| 13 | WEB-13 | wire-up: every cross-page link, `decide`/undo reaching badge, notifications, Home, Worlds, World, Ledger KPIs, Activity, chart, Agenda pin; `prefs.backup` | qa-breaker, code-reviewer |
| 14 | WEB-14 | polish: day/night everywhere, reduced motion, `still`, focus rings, Escape, collapse below 1100/1080, empty states, backdrop profile; then the cutover PR and the deletion list | design-critic, qa-breaker |

Gates on every PR: `just check`, `uv run pytest tests/repo -q`, no console error (`e2e/console-errors.spec.ts` extended to `/park/*`), apps/web `CLAUDE.md` kept at 40 lines or fewer (it is exactly 40 now, so the Park section replaces text rather than adding lines, or lives in `src/park/CLAUDE.md`), Playwright on a private `TILO_WEB_PORT`.

Line cap: CLAUDE.md caps a diff at 400 hand-written lines. A mechanical port of the engines (925 prototype lines of dense code) and each page (the Skills page file alone is 69 KB) will exceed it. Proposal: a ported or design-transcribed file is counted as generated when the PR says so and a diff against the prototype shows it is a transcription; logic, stores, API and tests stay under 400 per PR; pages over about 700 lines are split into two PRs (page frame, then sections). **Needs your decision.**

## 8. Existing screens: replaced at cutover, kept, and deleted

Nothing is deleted before the cutover PR, and the cutover PR lists each file here for approval. Replaced (route handed to Park): S-01 Start, S-14 Worlds list, S-18 route `/team` (its console moves to `/team/console`), S-19 Connections list, S-22 Settings, S-28 Pinboards and S-29 Calendar (visual). Replaced screens' tests are ported to the Park page or removed in the same PR with the list. Kept as they are: everything in the "Not covered" list in section 3. Files that become dead after cutover (candidates, to be confirmed with a reference check): `screens/S_14.tsx`, `S_22.tsx`, `S_28.tsx`, `S_29.tsx`, the S-01 body in `FlowShell.tsx`, and their tests and e2e specs. The `people/` data layer stays.

## 8a. Parity bar and review (user instruction, 6 Oct 2026 10:35 IST, relayed)

Pixel parity with the served `.dc.html` reference is the bar: layout, copy, colours, type, radii, spacing, motion timings, day and night, at 1440 and at the narrow width. design-critic checks parity (side-by-side screenshots at the same viewport and theme plus a pixel diff where possible), not "ours wins or ties". Any difference is a FAIL unless the PR lists it as an approved exception. No UI element is dropped or simplified because the PRD has no requirement for it; it is built as designed and runs on the typed fixtures through `api/`. No backend work for those elements now.

## 8b. Designed but not in the PRD

Running list; each designed element with no PRD requirement, so it can be wired up later. Filled in by each page phase (empty until then).

| Page | Element (feature, page, control) | Fixture source | Status |
| --- | --- | --- | --- |
| (none yet) | | | |

## 8c. Parity exceptions and component backlog (from the WEB-2 design-critic pass)

Design-owned exceptions (the design's own values win, listed in the PR that shows them): night white label on `--hero` (4.29:1, primary Button); day KPI label `--sch` on `--schSoft` (3.86:1, the "Saved by memory" tone); mobile touch targets under 44px (the design's control heights 32/34/36/38/42 win); font file (static fontsource Nunito Sans against the design's variable opsz Google font, about 0.015px per label).

Component variants the reference pages use, to add in the page ticket that first needs them:

- SegmentedControl: compact (Skills tool access: radiogroup r10, items h28 r7 12.5px `0 10px`); Worlds status tabs (h34, `0 12px`, 14px/700, count badge gap 7); Ledger "Group by" (grid of 3, no padding); Home "Size of job" (r16, p4, sliding, h36, 14px).
- Button sizes: h40, h44, h46 r14 (22px), h54 r18 (24px), h36 secondary r10, h34 secondary r10 13.5px, h28/h30/h32 small; trailing icon (`0 12px 0 16px`); needs hover `brightness(1.05)` (Worlds "Approve").
- SummaryPill solid amber ("Waiting for you": `#F0A500` / `#1F1D2B`, 13px, `0 12px`).
- Switch 40x24, knob 18, travel 16 (Profile notification matrix, Skills "ask me first") besides the 44x26 one (WEB-11 and the Skills phase).
- Card padding 18, 20/22/18, 22/24/24, 10 and PageSheet gap 20 (Ledger), 22 (Connectors, Profile, Team, World, Worlds), 30 (Agenda, Skills), padding `28px 32px 36px` (Skills 40 bottom, World 24 top): props before the screen tickets.
- Menu: account header (44px avatar, name 15/800, email 13/600, org 12.5/700 `--ink3`, lh 1.3, padding `10px 10px 12px`), separator (`1px --line2`, margin `0 6px 4px`); the Notifications popover is 392 wide.

Motion to restore in WEB-3 (reference values): primary hover `filter` (Home composer `.2s`, `transform .15s`, active `translateY(2px)`), needs hover `brightness(1.05)`; `background-color .2s` on ListRow, menu rows, nav rows and switch tracks (KPI `.3s`; Skills 40x24 switch `.25s`); switch knob `transform .25s cubic-bezier(.3,1.3,.5,1)`; sliding thumb `transform .4s cubic-bezier(.34,1.3,.5,1)` and item `color .25s`; Worlds tabs `background-color .2s, color .2s`; scrim `opacity .25s ease` and its modal panel `transform .4s cubic-bezier(.2,.8,.2,1)`; page transition `opacity .24s ease, transform .38s cubic-bezier(.2,.8,.2,1)`; Toast auto-hide 4.2 s; `@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}`. Toast and popover have no animation in the reference.

## 9. Decisions (approved 6 Oct 2026; logged in `docs/open-questions.md` as BQ-WEB-n)

- **A (BQ-WEB-2). World page**: the Park SVG overview, linking to the Pixi stage and to S-05, S-10, S-11, S-12. The stage is not replaced; no ADR.
- **B (BQ-WEB-3). Ambient motion**: first held for the user; then decided by the user's 6 Oct 2026 10:35 IST instruction as relayed by the supervisor ("ensure the frontend design is perfectly the same as the one I have provided"). Built as designed, on by default as in the reference: the city animates on Home only, is paused elsewhere and is frozen by motion `still` and reduced motion. One flag, `PARK_AMBIENT_MOTION` (default on), still gates it. Agent figures and world progress animate only from recorded events (HR-1). The scan stays untouched until WEB-3, where a narrow allowlist entry in `honestyScan.ts` for the non-agent layers only (cars, walkers, backdrop scroll, UI feedback keyframes), each with its reason, goes through code-reviewer and security-reviewer. WEB-1 to WEB-2 add no keyframes.
- **C (BQ-WEB-4). Type tokens**: Park pages are scoped under `[data-park]` with their own ramp test pinning the design's sizes; the design's type ramp wins on Park pages. The existing `type-ramp.spec.ts` stays unchanged for the old screens. The user's final design differs from PRD 18.2; this is recorded here as the reason.
- **D (BQ-WEB-5). Line cap**: engine ports and fixture transcriptions count as generated only when the PR body shows the diff against the prototype file, or a script that checks the port is faithful (each port ticket ships a parity test that runs the prototype in Node and the TS port with the same inputs and compares). Hand-written page code, logic and tests stay under 400 lines per PR. Pages are split as needed (Skills in two or more PRs).
- **E (BQ-WEB-6). Prototype approval**: `docs/adr/0003a-park-prototype-porting.md` cites the user's 6 Oct 2026 handoff. Root CLAUDE.md is not edited by this lane; the supervisor asks the user to add the file names there. `support.js` is never ported.
- **F (BQ-WEB-1). Connector logos**: monograms stay.

Still open, with the default shown:

- **Currency**: fixtures keep £ as sample data; the live API shows credits in the configured currency; the Ledger gets a unit prop.
- **Labels**: in fixture mode "Live now" reads "Sample run"; "Needs you" keeps its wording.
- **Mobile app link** in the account menu points at a placeholder ("Concept"), as in the README.
- **Dates**: fixtures are fixed at September 2026; the "today" marker is data, not the clock.
