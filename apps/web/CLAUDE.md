# apps/web

## Purpose
The Firebase-hosted web client (PRD 6.2): React UI, the PixiJS v8 isometric world, Story and
Trace lenses, cards and settings.

## Commands
- `pnpm --filter @tilo/web run dev` / `build` / `test` / `test:e2e` — dev server / build / Vitest / Playwright (always `TILO_WEB_PORT=<own port>`; a filtered run also runs the whole `timing` project unless `--no-deps`)
- `just tokens` — regenerate token files from `design/tokens.json`; `just check` — full gate; `just e2e-cp2` — `@cp2` Playwright walk on the real dev API (starts `tilo-api` + its own Vite; local only, never CI); `just parity [page]` — Park pixel-parity report vs the design (`parity-report/`, local only)

## Contracts
- Reads `packages/contracts-ts` types and Firestore docs under security rules; writes only through `tilo-api` (`src/api/http.ts`, chosen by `VITE_TILO_API_URL`, else the fixture client; polls events by seq). SEC-10 `src/appcheck/`: `HttpClient` sends `X-Firebase-AppCheck` from a getter that starts Firebase App Check (reCAPTCHA Enterprise) on the first API call; none on local hosts; `VITE_FIREBASE_API_KEY`/`_PROJECT_ID` come from `just deploy-web` (BQ-SEC10-5). `TiloApiError.code` carries an access refusal (SEC-15: `src/access/` sign-up question, under-construction page, `AccessGate`; not mounted until real sign-in). SEC-15 sign-in `src/auth/` (`tests/API_SIGNIN.md`, BQ-SIGNIN-1..7): `session` (one Firebase Auth controller, SDK dynamic import; local host or no config = "unavailable", no call) behind `SignInGate` in `Root`; `HttpClient` sends `Authorization: Bearer` (+ `X-Tilo-Channel: mobile_web` on phones) from `authToken`; account menu (FR-UX-10: `ParkApp` gives the shell's `ParkAuth` seam from `api/sessionAuth.ts`; Sign out reloads only if the SDK ended the session, else the gate says so); S-08 Gmail unverified-app note. ADR-0035 L4 (FR-CON-02): `src/api/connect.ts` (`ConnectFlow`: saves Google's `state` in sessionStorage before leaving, posts the callback only on a match), `src/oauth/` (`/oauth/google/callback`: `capture.ts` strips `code`/`state` with `replaceState` before anything renders; `CallbackPage` behind `SignInGate`; Hosting sends `no-referrer`, `no-store`), `park/pages/Connectors/GoogleAccess.tsx` (live flow only, `api/connectEnv.ts`; Disconnect warns that Gmail, Drive and Calendar end together). M1 (FR-MTG-09): `park/pages/Connectors/MeetingHostAccess.tsx` signs in the meeting bot's own account (`meeting_host`, `send`) over the same flow and state guard; status from the live `GET /v1/connectors` row (unknown unless `state_known`); no flow = "needs a real sign-in". ADR-0035 L6c: `needs-you/FieldsForm.tsx` (a `provide` card is answered by typed fields via `api/fields.ts`, not a tap), `ItemDocumentView` (show-me text of email/file/event documents, never markup). L6d: `api/useFieldsForm.ts` (headless form state, shared with Park's `park/app/DecisionFields.tsx`, a `provide` decision's form via `fieldsContext`; no tap), `api/item.ts` + `needs-you/ShowItem.tsx` (gate sheet 'Show me' from `GET .../cards/{cid}/item`, owner only). ; not wired until a read route exists, BQ-ADR35L6c-3). SEC-16 lifetime cap (403 `spend_cap_reached`, `isLifetimeCap`): `components/LifetimeCapDialog` with a feedback box (`submitFeedback`, Thanks only after the server confirms), shown by `FlowShell` and the Park `AppShell` instead of the error (BQ-FEEDBACK-1). ADR-0041 BYOK-5 (inert, SECURITY-FLAGGED credential input, BQ-BYOK-WEB-1..3): `park/pages/Profile/ModelKey.tsx` (Plan and billing, owner only; a member reads a line) over `api/modelKey.ts` + `modelKeyEnv.ts`; the key is one PUT body and nowhere else, typed in a CSS-masked text field (never type=password, PRD 16.1) with the page's own `CONSENT_VERSION` sent for the server to compare, "saved" only after a re-read, 503 `not_configured` = "off in this build" with a disabled form.

## Config and requirement IDs
`config/themes/` (world themes), feature flags. UX-1–UX-9 (18.1); FR-WLD-*; owned from P0-08.

## Stage and world (`src/stage/`, `src/world/`)
- `Stage.tsx`: the camera is the Pixi world container's transform (`camera.ts`); no CSS transform, no always-on ticker (HR-2). `data-stage-ready="true"` appears with the first frame. Zoom in/out buttons send the stage's own `+`/`-` keys (one camera path). `pixi.js`, `runWorld`, every `S_NN` screen (`routes.tsx`) and S-02/S-03 load by dynamic import (NFR-01) under `ChunkBoundary` + Suspense; keep them off the landing bundle.
- FR-WLD-04: `registry` → `reducer` (HR-5) → `store` → `frame` → `renderer.ts` (art in `world/art/`, ported
  from the design prototypes, ADR-0003); `choreographer.ts` (HR-3) alone animates. The stage draws a `?fixture=` replay
  (`runWorld`) or, on /world/:id, the client's own run: `useClientWorld` → `runClientWorld` (FR-WLD-05, any client; the one path). It waits for the layout via `getLayout` (until `world.started`); events held already fold in as a jump, later ones animate; no solver geometry = empty stage + a note; a failed load shows a note and retry. Needs-you reads `?world=<id>`, else the run `approve` last started (`worldContext.ts`, `lastWorld.ts`); live with none, `inARun.tsx` says "No run yet". `?seq=N`, `?speed=N`.
- FR-WLD-06: `selection.ts` keeps one selection per world (display state, never an event); the stage rings it.
- FR-WLD-08: `replay.ts` holds one replay point per world (display state); `ReplayScrubber` (right rail, or above the mobile tabs) scrubs a finished run, disabled while live. Stage shows `stateAt(seq)`, Story/Trace/HUD the events up to it (in `?fixture=` mode `WorldPanels` gets them as `replayed`; the HUD meter adds credits saved by memory, a phone's closed sheet shows `HudGlance`); the HR-4 banner ("Replay of run #… recorded …", fixtures add "dev fixture") shows once finished. The scrubber track marks decisions, finishes and problems; `LevelsPanel` (left of the stage from 1280 px, `world/levels.ts`) lists levels with progress and their latest line, all from the events.

## Screens (`src/screens/`, AGW-08)
- `meta.ts` is the PRD 18.3 table (S-01..S-29, status, route pattern); `routes.tsx` maps each
  routed screen to its `S_NN.tsx`. Build one: replace the stub, flip its status. `/more`, `/screens`. `ScreenPage` (the routed `<main>`) is tabbable and named only while it scrolls (#361).
- A control that does nothing yet is `aria-disabled="true"` with a "Coming soon" title. Nothing to list yet is `EmptyState` (`kit.tsx`: glyph, title, line, one action), in the reserved box the loading state held.
- `?speed=` is parsed in `world/speed.ts` (clamped 0.1..1000); the HR-6 badge says "Replay at N× speed"; it and the HR-4 pill sit in the fixed `.status-strip`; under it the shared `TopBar` (logo, place, real Needs-you count; no user/plan data, none exists) — fixed layers start below `--chrome-h`; keep its text from moving (CLS).
- An unknown world id or an unowned path under `/world/` or `/task/` shows `NotFound`, not Start.

## Needs you (`src/needs-you/`, AGW-05)
- `reduce.ts` (one reducer; queue.ts, gates.ts wrap it) derives queue and gates from events only,
  by run (HR-1); a card joins on same id and run id. A gate opens on `approval.resolved` (approve)
  or `policy.applied` (stamp, HR-7). `/screens/cards`.

## Local rules
- Nothing animates without a recorded event (HR-1–HR-7, PRD 9.4); `src/honesty/` (FR-WLD-09) fails on animation APIs outside `choreographer.ts` (allowlist: `test-support/honestyScan.ts`).
- One primary filled button per screen (UX-1, iris + 4px lip; `.secondary` is quiet); no streaks, hearts or fake urgency (UX-7).
  Type and spacing are tokens (PRD 18.2): `var(--text-N)` 12/14/16/20/24/32/40, `--space-N` 4..32, no `em` sizing; `e2e/type-ramp.spec.ts` pins it.
