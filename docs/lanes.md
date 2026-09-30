# Lanes: Claude and Antigravity work split to CP3

Updated 2026-10-01 by the orchestrator (Claude), who keeps this file current. Two builder teams share the remaining PRD **Must** work: Claude lanes (agents run by the orchestrator) and Antigravity lanes (Google Antigravity on Gemini Flash or Pro, on its own quota). GitHub is the only channel between them. For path ownership this file replaces the session table in `docs/parallel-sessions.md`; the rest of that file and root `CLAUDE.md` still apply.

## Targets
- **CP2 thin slice, running locally by 4 Oct:** type a task, answer the questions, pick an approach and a budget, watch the world, approve a "Needs you" gate, get the result. It runs on fakes and recordings and sends nothing real (ADR-0008). The deploy part of CP2 waits for Google Cloud billing (ADR-0003).
- **CP3, 9 Oct:** every Must acceptance test green (93 Must IDs in the PRD; about 42 had tests on 1 Oct).
- Should and Could items stay behind server-side flags, off by default. When behind, cut in the PRD 5.5 order; the never-cut list (gates and the authorisation audit, Trace, Pause all, credential policy, ledger and raw archive, provider layer, context handoff, evals, kill switch and budget alerts) is never cut.

## Who may change what

| Lane | Owner | Paths | Branches, base |
| --- | --- | --- | --- |
| CL-TRUST | Claude | `contracts/`, `config/`, `docs/adr/`, `packages/contracts-*`, `packages/providers/`, `packages/policy/`, `services/api/` (all but the intake module), `.github/`, `infra/`, `scripts/`, every `CLAUDE.md`, `.claude/` | `feat/<ID>-<slug>` from `phase0-stack` |
| CL-PLAN | Claude | `packages/planning/`, `services/api` intake module, `prompts/` | same |
| CL-HARNESS | Claude | `services/harness/`, `packages/archive/`, `packages/memory/`, `skills/` | same |
| CL-REACH | Claude | `services/connectors/`, `services/channels/`, `services/browser/` | same |
| CL-EVID | Claude | `evals/src/`, existing `evals/tests/`, `evals/case.schema.json`, `packages/metering/`, `services/sandbox-web/` | same |
| CL-INT | Claude | the CP2 wiring across the lanes above, plus `apps/web/src/api/http*` (the web's HTTP client and sign-in) | same |
| AG-WEB | Antigravity | `apps/web/**` except `apps/web/src/api/http*`, generated files (`src/world/registry.generated.ts`, `src/design/tokens.ts`, `src/styles/tokens.css`) and `apps/web/CLAUDE.md`; plus `pnpm-lock.yaml` and `docs/licences.md` | `ag-web/<ticket>-<slug>` from `phase0-stack`, worktree `.claude/worktrees/ag-web` |
| AG-EVAL | Antigravity | `evals/cases/**`, `evals/fixtures/**`, new `evals/tests/test_PRD_19_2_*.py` | `ag-eval/<ticket>-<slug>` from `phase0-stack`, worktree `.claude/worktrees/ag-eval` |
| AG-MEET | Antigravity | `meet-bot/**` on the `chore/meet-bot-baseline` line only | `ag-meet/<VA-nn>-<slug>` from `chore/meet-bot-baseline`, worktree `.claude/worktrees/meet-bot` |

Never given to Antigravity: security, concurrency and contract work, which means contracts, the policy engine and risk tiers, the outbox, cards and gates (server side), kill switches, auth, principal and redaction, channels and webhooks, connectors and the token broker, harness concurrency and the provider layer. `scripts/lane_guard.py` enforces the AG-WEB and AG-EVAL paths in CI on every `ag-*` branch.

## Handoff protocol (GitHub only)
1. **Issue per ticket.** Labels `antigravity`, `flash` or `pro`, and `lane:ag-web`, `lane:ag-eval` or `lane:ag-meet`. The issue holds the requirement IDs, the PRD sections, the acceptance tests to write first (IDs in the test names), the files in scope and out of scope, and the done-check.
2. **Flash or Pro.** Pro: planning, multi-file state logic, anything that reads the event stream or touches the honesty rules HR-1 to HR-7, renderer performance, and meet-bot VA-09, VA-11, VA-13 and VA-16. Flash: a single screen or component from a clear spec, tests from a spec, fixtures and eval-case content, docs, lint fixes.
3. **PR.** Antigravity opens PRs into `phase0-stack` (AG-WEB, AG-EVAL) labelled `antigravity`. The body carries `Closes #<issue>`, the IDs, the tests, the `just check` result and the hand-written line count.
4. **Review.** The orchestrator reviews every Tilo-lane PR with its agents: code-reviewer always; design-critic and qa-breaker once per screen for AG-WEB. One PR comment in the root `CLAUDE.md` reviewer format lists every blocking problem.
5. **Fix.** Antigravity fixes everything in one pass; only the failed reviewer re-checks. After 2 failed rounds the orchestrator splits the ticket or takes it into a Claude lane.
6. **Merge.** Only the orchestrator merges into `phase0-stack` (`gh pr merge --merge`), with CI green and review PASS on the final commit. Any diff that touches a Claude-lane path, `contracts/` or `docs/prd/`, or adds a model id outside `config/`, is rejected.
7. **AG-MEET** merges its own PRs into `chore/meet-bot-baseline` once the meet-bot gate is green (Pro tickets wait for an orchestrator review comment). The orchestrator reviews the whole line at the integration ticket VA-INT, which moves its model ids into `config/` and its calls into `packages/providers`.
8. **Questions.** Antigravity comments on the issue with the PRD default it used; the orchestrator folds it into `docs/open-questions.md`.

## Claude lane queue
1. **In-flight branches (1 to 2 Oct):** one review round each, then merge. See the tracker.
2. **CL-INT, CP2 wiring (2 to 4 Oct):** `POST /intake` with the SafetyProvider (after CC-SP-47), questions and answers, approaches, approval with the budget grant (policy risk table from `config/` after CC-SP-64), a harness run on fake providers writing events to the Firestore emulator, live rendering in the web (FR-WLD-05), the gate card through the outbox to a fake send, delivery. Adds `apps/web/src/api/http.ts` behind the AGW-01 `TiloClient` interface.
3. **Phase B Musts (4 to 9 Oct):**
   - CL-PLAN: FR-INT-11, FR-INT-12, FR-WLD-01 (layout: model semantics, deterministic solver, WE rules).
   - CL-HARNESS: FR-AGT-04 (skills redo, #70), -05, -08, -09, -10, -12, -13; FR-MEM-01, -02, -03, -05, -06, -09.
   - CL-TRUST: FR-HIL-10 (Team Lead console API), FR-HIL-11 (card sync across channels), P0-03b (#28).
   - CL-REACH: FR-CHN-01 to -12 and -14 (web and WhatsApp channels, webhooks, email links, Gmail watch, triage, drafting, undo window); FR-CON-01 to -05, -07, -08, -10 (connector registry, token broker, consent, Gmail, Drive, browser workers, provenance manifest).
   - CL-EVID: P8-06c runner and credit cap, P8-06d results and CLI, the E-ROUTE checks (`routed_domain`, `answered_from_decision`), FR-MTR-06, EFF-06 nightly (P8-09).

## Antigravity queue
- **AG-WEB:** AGW-01 to AGW-05 open. Next: AGW-06 S-04 world HUD (meter, needs-you count, Pause all; Pro), AGW-07 S-12 delivery and celebration (Flash). Then the UI-only FR-WLD Musts: FR-WLD-06 lenses in sync and Inspect (Pro), -07 Pause-all veil (Pro), -08 replay and scrub (Pro), -09 static honesty check (Pro), -10 performance (Pro), -11 accessibility (Flash). Then the remaining Must screens on fixtures: S-05, S-10, S-11, S-13 to S-19, S-21 to S-24.
- **AG-EVAL:** AGE-01 to AGE-05 open (140 cases). Next: AGE-06 E-ROUTE (20 cases and the "every group complete" test) once CL-EVID registers its checks. Then the lane becomes **AG-RENDER**: FR-CON-09 (PDF and PPTX deliverables from templates with data-bound charts, `services/render/`), brief to follow.
- **AG-MEET:** VA-05, VA-06, VA-07, VA-12 (Flash) and VA-09 (Pro) open. Order after that follows `meet-bot/docs/VOICE_ARCHITECTURE.md` section 5; experiment X4 (Gemini Live) needs the user's AI Studio key and a live run, so VA-16's place waits for it. Meeting features (specs MF-01 to MF-04 in `meet-bot/docs/specs/`) start only once the user approves them.

## Tracker

| Lane | Ticket | IDs | Owner | Model | Status | Issue | PR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CL-TRUST | CC-SP-47 SafetyProvider | FR-INT-02 | Claude | - | finishing (merge base, tests) | #47 | - |
| CL-PLAN | FR-INT-06/07/08 approaches, estimates, budget | FR-INT-06, -07, -08 | Claude | - | finishing; security review next | #68 | - |
| CL-PLAN | FR-INT-09 PlanGraph validator | FR-INT-09 | Claude | - | queued (wip 81b44c8) | - | - |
| CL-TRUST | FR-HIL-01/02 cards API | FR-HIL-01, -02 | Claude | - | queued (rebase onto redaction) | #32 | - |
| CL-TRUST | CC-SP-64 `grant_budget` T1 | FR-INT-08 | Claude | - | queued (tests only) | #64 | - |
| CL-TRUST | FR-HIL-07 kill switches (redo) | FR-HIL-07 | Claude | - | queued (wip 42d4789) | #46, #55 | - |
| CL-EVID | P8-06c/d eval runner, credit cap, results | EFF-07 | Claude | - | queued (port from `feat/P8-06-eval-harness`) | - | - |
| CL-INT | CP2 wiring | FR-WLD-05, CP2 | Claude | - | after the in-flight merges | - | - |
| AG-WEB | AGW-01 flow shell and TiloClient seam | PRD 18.3, UX-1..3 | Antigravity | Pro | open | #80 | - |
| AG-WEB | AGW-02 S-01 Start | FR-INT-01 | Antigravity | Flash | open (after AGW-01) | #81 | - |
| AG-WEB | AGW-03 S-02 Understanding | FR-INT-01, -03, -04, -05 | Antigravity | Flash | open (after AGW-01) | #82 | - |
| AG-WEB | AGW-04 S-03 Approaches and budget | FR-INT-06, -08 | Antigravity | Flash | open (after AGW-01) | #83 | - |
| AG-WEB | AGW-05 S-06/S-07 cards and gate sheet | FR-HIL-01, -11, FR-CHN-01, FR-WLD-09 | Antigravity | Pro | open (after AGW-01) | #84 | - |
| AG-EVAL | AGE-01 E-PLAN (10) | 19.2 E-PLAN | Antigravity | Flash | open | #85 | - |
| AG-EVAL | AGE-02 E-RED (14) | 19.2 E-RED, EV-09 | Antigravity | Pro | open | #86 | - |
| AG-EVAL | AGE-03 E-CHN (30) | 19.2 E-CHN, FR-CHN-04 | Antigravity | Flash | open | #87 | - |
| AG-EVAL | AGE-04 E-MAIL (50) | 19.2 E-MAIL, FR-CHN-09, -10 | Antigravity | Flash | open | #88 | - |
| AG-EVAL | AGE-05 E-RES, E-DOC, E-HAND (36) | 19.2 | Antigravity | Flash | open | #89 | - |
| AG-MEET | VA-05 replay harness and fakes | VA-05 | Antigravity | Flash | open | #90 | - |
| AG-MEET | VA-06 AudioIn with Silero VAD | VA-06 | Antigravity | Flash | open | #91 | - |
| AG-MEET | VA-07 paced persistent player | VA-07 | Antigravity | Flash | open | #92 | - |
| AG-MEET | VA-12 Scribe manual commit | VA-12 | Antigravity | Flash | open | #93 | - |
| AG-MEET | VA-09 FloorController and addressing | VA-09 | Antigravity | Pro | open | #94 | - |
