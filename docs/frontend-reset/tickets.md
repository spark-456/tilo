# Frontend reset: tickets

Each ticket is written to be filed as a GitHub issue as it stands. IDs: `FE-nn`. Requirements are in [requirements.md](requirements.md). Branch `feat/FE-nn-<slug>` from `phase0-stack`. Acceptance tests are written first by test-writer, with the requirement ID in the test name. PRs over 400 hand-written lines are split (`a`, `b`, ...); ported design code is counted separately and logged as a size exception, as done for P0-05.

Model column: **S** = Sonnet (default), **O** = Opus (needs the user's OK; the exception rule is escalation only). Reviewers: **C** code-reviewer, **D** design-critic (blind, both viewports), **Q** qa-breaker, **A** architect.

## Index and dependencies

| Ticket | Title | Requirements | Depends on | Model | Reviewers | Wave |
| --- | --- | --- | --- | --- | --- | --- |
| FE-00 | Decisions, ADR and addendum registration | all | none | O (architect) | none | 0 |
| FE-01 | Design gate: parity map, goldens, stub check | FR-UX-08 | none | S | C, Q | 0 |
| FE-02 | Art bible, kit manifest, capability atlas | FR-KIT-01, -02, -03 | FE-00 | O | A, D | 0-1 |
| FE-03 | Kit core: port primitives, building generator, states, `/kit` gallery | FR-KIT-04, -11 | FE-02 | S | C, D | 1 |
| FE-04 | Common buildings, all 15 | FR-KIT-05 | FE-03 | S | C, D | 1 |
| FE-05 | Ground and infrastructure | FR-KIT-07 | FE-03 | S | C, D | 1 |
| FE-06 | Agents and carried items | FR-KIT-06 | FE-03 | S | C, D | 1 |
| FE-07 | App shell and navigation | FR-UX-01, -02 | FE-01 | S | C, D, Q | 1 |
| **Style lock** | **User reviews the `/kit` gallery and approves the look** | | FE-03 to FE-06 | user | | gate |
| FE-08 | Renderer integration: art on the real stage | FR-KIT-10 | FE-03 to FE-06 | S | C, D, Q | 2 |
| FE-09 | Domain pack A: knowledge, money, law, data, IT | FR-KIT-03/04 | Style lock | S | C, D | 2 |
| FE-10 | Domain pack B: commerce, logistics, making, building, field | FR-KIT-03/04 | Style lock | S | C, D | 2 |
| FE-11 | Domain pack C: people, care, learning, hospitality, creative, public | FR-KIT-03/04 | Style lock | S | C, D | 2 |
| FE-12 | Home rebuilt from the artboard | FR-UX-03 | FE-07 | S | C, D | 2 |
| FE-13 | World screen composition and overlays | FR-UX-05 | FE-07, FE-08 | S | C, D, Q | 2-3 |
| FE-14 | Approve loop: adopt #84, #199, #200 under the gate | FR-UX-06 | FE-01, FE-07 | S | C, D, Q | 2-3 |
| FE-15 | Variety corpus and coverage proof | FR-KIT-08 | FE-08, FE-09 to FE-11 | S | C, D | 3 |
| FE-16 | Tiers, metropolis, level of detail, performance | FR-KIT-09, FR-WLD-10 | FE-08 | S (O if two fails) | C, Q | 3 |
| FE-17 | Landing page | FR-UX-04 | FE-07, FE-08 | S | C, D | 3 |
| FE-18 | Remaining screens to design quality | FR-UX-07 | FE-07 | S | C, D | 3 |
| FE-19 | States, motion and density polish | FR-UX-09 | FE-18 | S | D, Q | 4 |

Cross-lane dependency: the deterministic solver (FR-WLD-01, CL-PLAN) must read footprints and heights from the FE-02 manifest. It is not started; FE-02 publishes the manifest first and opens a `contract-change` note if the solver needs more fields.

---

## FE-00 Decisions, ADR and addendum registration
**Owner** architect. **Paths** `docs/adr/`, `docs/open-questions.md`, `docs/lanes.md`, `contracts/theme.schema.json` (new, additive), `docs/frontend-reset/`.
**Do**
1. Record the requirement addendum (requirements.md) once the user approves it; add its IDs to the ticket loop.
2. ADR "Kit rendering pipeline": options (a) bake each kit part to a texture atlas at build time from the generator's SVG, tinted at runtime (matches PRD 9.7), (b) draw vectors live in Pixi `Graphics`, (c) hybrid: bake static parts, draw agents and effects live. Decide with a one-day spike on the reference profile (55 fps p95 with 40 agents). Default if undecided: (c).
3. ADR "Kit manifest": fields, compatibility rules, how the solver gets footprint and height, how themes load. Add `contracts/theme.schema.json` (additive only; no change to `layout.schema.json`).
4. ADR "Lanes for the reset": propose that Claude sessions own `apps/web/src/kit/**`, `apps/web/src/shell/**`, `apps/web/src/world/renderer.ts`, `apps/web/src/stage/**` and `config/themes/**`, and AG-WEB keeps `apps/web/src/screens/**` under the FE-01 gate. Update `docs/lanes.md` and `scripts/lane_guard.py`.
5. Navigation decision (default in FR-UX-02) and the policy-colour defaults already in ADR-0003.
**Done** ADRs merged, lanes file updated, no code. Use the next free ADR numbers after 0013 (0014 is reserved for the untracked partner-portal ADR).

## FE-01 Design gate: parity map, goldens, stub check
**Requirement** FR-UX-08. **Paths** `apps/web/e2e/`, `docs/frontend-reset/parity.md`, `scripts/`, `.github/workflows/` (via CL-TRUST for the workflow line).
**Do**
- `parity.md`: one row per screen: PRD id, artboard file and label, viewport, status (missing, partial, matched), last design-critic verdict.
- A Playwright harness that opens a route at 1440x900, 390x844 (and 1920x1080 for stage), waits for `data-stage-ready`, and compares to a committed golden with a small tolerance. Update command: `pnpm --filter @tilo/web test:e2e -- --update-snapshots`.
- A CI check listing every route that renders `ComingSoon`; fails if a Must route does; prints the count today.
- A short guide for design-critic: how to open the artboard next to the build, what to compare.
**Acceptance** `test_FR_UX_08_gate`: a fixture PR that adds a route without a parity row fails; the stub list matches `meta.ts`.
**Done** harness runs on three existing screens; stub count printed in CI.

## FE-02 Art bible, kit manifest, capability atlas
**Requirements** FR-KIT-01, -02, -03. **Model** Opus (judgment-heavy; this is the "deep understanding" ticket). **Paths** `docs/design/art-bible.md`, `docs/design/capability-atlas.md`, `config/themes/metropolis/kit.yaml`, `apps/web/src/kit/lint/`.
**Read** art-facts.md; `design/source/Tilo World Kit.dc.html`; `tilo-world.js`; `tilo-kit.js`; `contracts/layout.rules.md`; PRD 4.3, 8.2, 9.1, 18.5.
**Do**
1. **Art bible**: turn art-facts.md into rules with do and don't pictures and a lint.
2. **Capability atlas**: survey real work across at least 16 domains (starting list: research and intelligence; finance and accounting; legal and compliance; sales and CRM; marketing and content; customer support; operations and logistics; procurement and supply; manufacturing and engineering; software and IT; data and analytics; people and HR; education and training; health and care admin; home, property and construction projects; travel, hospitality and events; personal life admin; public sector and non-profit; creative and media; retail and e-commerce; agriculture, energy and field work). For each, list at least 4 capabilities (verbs such as gather, read, extract, compare, price, negotiate, schedule, book, draft, design, calculate, reconcile, audit, verify, approve, sign, file, monitor, forecast, build, assemble, test, inspect, deploy, publish, present, translate, teach, answer, triage, route, track, deliver, archive). Map each to a body archetype, icon, props and role colour, with a one-line reason a person would recognise.
3. **Body archetypes** (seed list; extend and justify): office, library or archive, lab, workshop, factory with sawtooth roof, warehouse with loading bays, harbour or dock, market or shopfront, counting house or bank, civic hall with columns, clinic, school, glass studio, theatre or stage, lookout or observatory, greenhouse, barn with silo, power station with tank and chimney, data hall with racks, call centre, sorting office, kitchen or cafe, inn, station, building site with crane and scaffold, high-rise, pavilion, gatehouse, print works, showroom, depot, launch pad.
4. **Parts**: roofs (flat, gable, dome, plus hip, sawtooth, pyramid or spire, canopy, glass), facades (windows, band, arches, plus shopfront, bays, curtain glass, columns, slats), annexes (chimney, antenna, solar panels, tank, flag, awning, crane, sign), props (crates, pallets, carts, trucks, boats, benches, plants), ground surfaces, icons (at least 120 in the stroke style of `icon()`).
5. **Manifest** `kit.yaml` with footprint, height range, compatible-with, capability tags; `theme.schema.json` validates it (FE-00).
6. **Fallback rule**: any capability with no tag still gets a valid generic building (workshop, studio, office or yard) composed from the manifest.
**Acceptance** `test_FR_KIT_01_style_lint`, `test_FR_KIT_02_manifest_valid`, `test_FR_KIT_03_atlas_coverage` (requirements.md).
**Done** manifest and schema merged; atlas reviewed by design-critic and the user; the planner prompt owner (CL-PLAN) is told where the list lives.

## FE-03 Kit core
**Requirements** FR-KIT-04, -11. **Paths** `apps/web/src/kit/`, `apps/web/src/routes` for `/kit` (dev and gallery), `docs/licences.md`.
**Do** Port the primitives from `tilo-world.js` and `tilo-kit.js` into typed modules: projection, `box`, `facade`, `roofEl`, `colorsFor`, seeded `rng`/`hash`, `icon`, `pin`, `tag`, `label`. Build `buildBuilding(spec, state, seed)` from the manifest. Implement all eight states and hover and selected. Apply the FE-00 pipeline decision (atlas bake or live). Add `/kit`: a gallery of every part, archetype and state, dev only plus a flag for review builds. Do not port `support.js`.
**Acceptance** `test_FR_KIT_04_deterministic_render`, `test_FR_KIT_04_states_gallery`, `test_FR_KIT_11_licence_register`, plus the FE-02 lint passing on all output.
**Done** `/kit` shows the 14 original kit buildings in 8 states, matching the original at the same zoom (design-critic blind PASS).

## FE-04 Common buildings, all 15
**Requirement** FR-KIT-05. **Paths** `apps/web/src/kit/common/`.
**Do** The 14 existing kit buildings plus Mail Room and Expert Office (new, in style), each recognisable without its label, in all eight states. Mail Room has a pier-side chute for the channel boat.
**Acceptance** `test_FR_KIT_05_common_buildings`, 15 x 8 goldens, blind recognition test.

## FE-05 Ground and infrastructure
**Requirement** FR-KIT-07. **Paths** `apps/web/src/kit/ground/`.
**Do** Plot surfaces (at least 6), roads and junctions, rail, footpath, pier with boat, bridges for each connection type, islands, cloud cover, lifts and landings, gates with the person and the policy variants (policy stamp per ADR-0003 and BQ-49), plants and props, crates, carts, trucks. Greyscale test: each bridge type is distinct without colour.
**Acceptance** `test_FR_KIT_07_ground_and_infra`.

## FE-06 Agents and carried items
**Requirement** FR-KIT-06. **Paths** `apps/web/src/kit/agents/`.
**Do** Port `agent()`: six ranks, nine role colours, every expression, walk frame, carried items, backpack, rank badge, crowd figure for aggregation. Map every `agent.*` event type to a pose with a registry-driven test.
**Acceptance** `test_FR_KIT_06_agent_poses`.

## FE-07 App shell and navigation
**Requirements** FR-UX-01, -02. **Paths** `apps/web/src/shell/**`, `apps/web/src/styles/`, `apps/web/src/App.tsx`, `router.ts`.
**Do**
- Shell: top bar with wordmark, world switcher, HUD (time saved marked as an estimate, credits used, saved by memory, needs-you count), left rail, right rail, content region. Mobile bottom tabs and three-height sheets.
- Nav: rail items per FR-UX-02; unbuilt Should screens hidden by flag; real not-found page; focus handling already in `App.tsx` is kept.
- `ComingSoon` is removed from every navigable path; Must stubs are tracked by FE-01 until their tickets land.
**Acceptance** `test_FR_UX_01_shell_on_every_route`, `test_FR_UX_02_nav_crawl`, design-critic PASS against Home v2 and Balanced Refined 2-1 and 2-2.

## Style lock (user gate, no ticket)
After FE-03 to FE-06 the user opens `/kit` and `/world/<fixture>` and says: *this is the look* or *change X*. No domain pack (FE-09 to FE-11) starts before that, so a style change costs hours, not days.

## FE-08 Renderer integration
**Requirement** FR-KIT-10 (and FR-WLD-04 determinism stays). **Paths** `apps/web/src/world/renderer.ts`, `apps/web/src/stage/**`.
**Do** Replace the diamond and dot drawing with kit output for every Frame element: buildings in their states, districts, agents on routes, gates, bridges, clouds, items, pins. Keep the camera and the choreographer as they are (HR-3). Port route and pathfinding behaviour from `tilo-player.js` into the existing choreographer, not a second animation path. Fix the blank-stage case: if the frame has content, the canvas is never empty.
**Acceptance** `test_FR_KIT_10_no_placeholders`, existing `reducer`, `frame` and `choreographer` tests unchanged and green, one Playwright golden of the Village fixture.

## FE-09 / FE-10 / FE-11 Domain packs
**Requirements** FR-KIT-03, -04. **Paths** `apps/web/src/kit/packs/<pack>/`, manifest additions in `config/themes/metropolis/kit.yaml` (FE-02 owner reviews).
**Do** For each pack, build the archetypes, annexes, props and icons the atlas assigns to its domains, each with a gallery tile and eight-state goldens.
- **A**: research and intelligence, finance and accounting, legal and compliance, data and analytics, software and IT, sales, marketing and content.
- **B**: retail and e-commerce, operations and logistics, procurement, manufacturing and engineering, home, property and construction, agriculture, energy and field work.
- **C**: people and HR, education, health and care admin, travel, hospitality and events, personal life admin, creative and media, public sector and non-profit, customer support.
Cut order if behind: C, then B, then A (A matches the first scenarios). The generic fallback keeps every domain acceptable.
**Acceptance** `test_FR_KIT_03_atlas_coverage` extended per pack; no two archetypes in a pack share a silhouette in greyscale.

## FE-12 Home rebuilt from the artboard
**Requirement** FR-UX-03. **Paths** `apps/web/src/screens/flow/StartScreen.tsx` and a new `apps/web/src/screens/home/`.
**Do** Match `Tilo Home v2.dc.html`: task box, drop zone, suggested tasks, three ways to work, resume list from real worlds, needs-you banner. First-run and returning states. Keep the intake behaviour from AGW-02 and the 4,000-character and file limits.
**Acceptance** `test_FR_UX_03_home_states`, existing `StartScreen` tests unchanged.

## FE-13 World screen composition and overlays
**Requirement** FR-UX-05. **Paths** `apps/web/src/screens/world/`, `apps/web/src/stage/`.
**Do** HUD, level switcher, follow and zoom, districts panel, needs-you card, scrubber with event markers and speed badge (HR-6), lens tabs, overlays. Each overlay is a pure function of recorded events with a unit test. Stage mode and density mode remain display settings.
**Acceptance** `test_FR_UX_05_world_screen`.

## FE-14 Approve loop under the gate
**Requirement** FR-UX-06. Adopts open tickets #84 (S-06 and S-07), #199 (S-08), #200 (S-09). **Do** Keep their own specs and tests; add the FE-01 parity row and goldens, the design-critic pass, and the nav entries from FE-07. Policy variant per BQ-49.

## FE-15 Variety corpus and coverage proof
**Requirement** FR-KIT-08. **Paths** `apps/web/fixtures/worlds/`, `apps/web/e2e/variety/`.
**Do** Author at least 40 plan and layout fixtures across at least 16 domains and all tiers, written as data (no scenario code), with scripted events labelled as demo. Render all, assert the numeric checks, publish a contact sheet in the PR. At least six are polished showcase worlds used by the landing page.
**Acceptance** `test_FR_KIT_08_variety_corpus`.

## FE-16 Tiers, metropolis, level of detail, performance
**Requirements** FR-KIT-09, FR-WLD-10. **Do** Outpost to metropolis, the 7-level tower with lifts, crowd aggregation past 60 agents, texture atlases, the perf test on the reference laptop profile (55 fps p95 with 40 agents; 30 fps with 20 on the phone profile).
**Acceptance** `test_FR_KIT_09_tier_render`, `test_FR_KIT_09_lod`, the perf job.

## FE-17 Landing page
**Requirement** FR-UX-04. **Paths** `apps/web/src/screens/landing/`. **Needs** the user's copy direction (default: plain, calm, no hype, no numbers without a source).
**Do** Hero with a live replay of a showcase world from FE-15 and the permanent replay banner; three-line explanation; four-step how-it-works; trust and safety; one call to action to the demo. Signed-out `/` shows it; signed-in `/` shows Home.
**Acceptance** `test_FR_UX_04_landing`.

## FE-18 Remaining screens to design quality
**Requirement** FR-UX-07. **Do** S-05, S-10 to S-19, S-21 to S-24 and Skills, Ledger, Team from the design set: layout, empty, loading and error states, copy per PRD 18.4. One PR per two or three screens, each with its parity row, goldens and critic verdict.

## FE-19 States, motion and density polish
**Requirement** FR-UX-09. **Do** Skeletons, empty and error states, token-timed transitions, reduced motion, professional density. CP4 design gate.

---

## Review gates per ticket
- Always: code-reviewer. UI tickets: design-critic blind against the artboard at both viewports. Running code: qa-breaker once.
- Auto-FAIL additions for this programme: any placeholder shape on the stage, any `ComingSoon` on a Must route, any off-palette colour, any console error.
- Reviewers list every blocking problem in one round; after two failed rounds the ticket is split or goes to Opus.
