# apps/web

## Purpose
The Firebase-hosted web client (PRD 6.2): React UI, the PixiJS v8 isometric world, Story and
Trace lenses, cards and settings. P0-08a shipped the shell: tokens, layout frame and iso stage.

## Commands
- `pnpm --filter @tilo/web run dev` / `build` / `test` / `test:e2e` — dev server / build / Vitest / Playwright
- `just tokens` — regenerate the committed token files from `design/tokens.json`
- `just check` — full gate from the repo root

## Contracts
- Reads: `packages/contracts-ts` generated types; Firestore documents under security rules
  (never calls models, connectors or storage directly — writes only through `tilo-api`).
- Writes: none yet.

## Config
- `config/themes/` (world themes), feature flags.

## Requirement IDs
- UX-1 through UX-9 (section 18.1); FR-WLD-* (world rendering); owned starting P0-08.

## Stage (`src/stage/`)
- `camera.ts` holds the pure camera maths (pan, `zoomAt`, `normalizeWheel`, easing); unit-tested.
- `Stage.tsx`: the camera is the transform of a Pixi world container (position = stage centre
  + (x, y), scale = zoom); the iso grid is redrawn in world coordinates for the visible rect.
  No CSS transform on the canvas and no always-on ticker: one render per camera change, eased
  keyboard moves timed by `performance.now()`, and a render on resize, DPR change and
  visibility change (HR-2). Every drawn frame writes `data-camera-x/y/zoom` on the stage frame.
- Readiness: the first frame is drawn as soon as Pixi's init resolves; from then on the stage
  frame carries `data-stage-ready="true"` (never before). E2e specs navigate with
  `gotoStage`/`reloadStage` from `e2e/support/camera.ts`, which wait for it.
- World content plugs in through the `onWorld(world, requestRender)` prop (`WorldSeam`).

## Local rules
- Nothing animates without a recorded event (honesty rules HR-1–HR-7, PRD 9.4).
- One primary filled button per screen (UX-1); no streaks, hearts or fake urgency (UX-7).
