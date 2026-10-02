# apps/web

## Purpose
The Firebase-hosted web client (PRD 6.2): React UI, the PixiJS v8 isometric world, Story and
Trace lenses, cards and settings. P0-08a shipped the shell: tokens, layout frame and iso stage.

## Commands
- `pnpm --filter @tilo/web run dev` / `build` / `test` / `test:e2e` — dev server / build / Vitest / Playwright
- `just tokens` — regenerate the committed token files from `design/tokens.json`
- `just check` — full gate from the repo root

## Contracts
- Reads `packages/contracts-ts` types and Firestore docs under security rules (never calls
  models/connectors/storage directly — writes only through `tilo-api`). Writes: none yet.

## Config
`config/themes/` (world themes), feature flags.

## Requirement IDs
UX-1–UX-9 (18.1); FR-WLD-* (world rendering); owned starting P0-08.

## Stage (`src/stage/`)
- `camera.ts`: pure camera maths (pan/`zoomAt`/`normalizeWheel`/easing), unit-tested. `Stage.tsx`:
  the camera is the Pixi world container's transform; no CSS transform, no always-on ticker, one
  render per camera change/resize/DPR/visibility change (HR-2). Every drawn frame writes
  `data-camera-x/y/zoom`. World content plugs in through `onWorld(world, requestRender)`.
- `data-stage-ready="true"` appears with the first frame (after Pixi init); e2e specs navigate
  with `gotoStage`/`reloadStage` (`e2e/support/camera.ts`), which wait for it.

## World (`src/world/`)
- FR-WLD-04 pure pipeline: `registry.ts` (generated from `contracts/events/registry.yaml`) →
  `reducer.ts` (`WorldState`/`reduce`/`applyEvent`, HR-5) → `store.ts` (snapshots) → `frame.ts`
  (plain-data list, token colours) → `renderer.ts` (Pixi placeholders). `choreographer.ts` (HR-3)
  alone animates anything; `runWorld.ts` wires it up, owns the real clock.
- Fixture mode: `?fixture=<name>` plays a layout+stream into the world; `?seq=N`/`?speed=N`
  control replay. DOM contract: `apps/web/e2e/support/world.ts`.

## Screens and navigation (`src/screens/`, AGW-08)
- `meta.ts` is the PRD 18.3 table (S-01..S-25: name, priority, pillar, address, `built` or
  `placeholder` status, route pattern). `routes.tsx` maps each routed screen to its `S_NN.tsx`.
  Flow-shell screens (S-01..S-04, S-12) stay in `FlowShell.tsx` until their tickets replace them.
- To build a screen: replace the body of its `S_NN.tsx` stub, flip its status in `meta.ts`.
- `PrimaryNav.tsx` is the left rail and the five mobile tabs; `/more` reaches the rest and
  `/screens` (dev only) lists every screen with its status. A control that does nothing yet is
  `aria-disabled="true"` with a "Coming soon" title; it is never a dead click.

## Local rules
- Nothing animates without a recorded event (honesty rules HR-1–HR-7, PRD 9.4).
- One primary filled button per screen (UX-1); no streaks, hearts or fake urgency (UX-7).
