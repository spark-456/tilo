# apps/web

## Purpose
The Firebase-hosted web client (PRD 6.2): React UI, the PixiJS v8 isometric world, Story and
Trace lenses, cards and settings.

## Commands
- `pnpm --filter @tilo/web run dev` / `build` / `test` / `test:e2e` — dev server / build / Vitest / Playwright
- `just tokens` — regenerate token files from `design/tokens.json`; `just check` — full gate

## Contracts
- Reads `packages/contracts-ts` types and Firestore docs under security rules; writes only through
  `tilo-api`, never to models, connectors or storage directly. Writes: none yet.

## Config
`config/themes/` (world themes), feature flags.
## Requirement IDs
UX-1–UX-9 (18.1); FR-WLD-* (world rendering); owned starting P0-08.

## Stage and world (`src/stage/`, `src/world/`)
- `Stage.tsx`: the camera is the Pixi world container's transform (`camera.ts`); no CSS transform,
  no always-on ticker (HR-2). `data-stage-ready="true"` appears with the first frame.
- FR-WLD-04 pipeline: `registry.ts` → `reducer.ts` (HR-5) → `store.ts` → `frame.ts` → `renderer.ts`;
  `choreographer.ts` (HR-3) alone animates. `?fixture=<name>`, `?seq=N`, `?speed=N` control replay.

## Screens (`src/screens/`, AGW-08)
- `meta.ts` is the PRD 18.3 table (S-01..S-25, status, route pattern); `routes.tsx` maps each
  routed screen to its `S_NN.tsx`. Build one: replace the stub, flip its status. `/more`, `/screens`.
- A control that does nothing yet is `aria-disabled="true"` with a "Coming soon" title.
- `?speed=` is parsed in `world/speed.ts` (clamped 0.1..1000); the HR-6 badge says "Replay at N× speed".
- An unknown world id or an unowned path under `/world/` or `/task/` shows `NotFound`, not Start.

## Needs you (`src/needs-you/`, AGW-05)
- `reduce.ts` (one reducer; queue.ts, gates.ts wrap it) derives queue and gates from events only,
  by run (HR-1); a card joins on same id and run id. A gate opens on `approval.resolved` (approve)
  or `policy.applied` (stamp, HR-7). `/screens/cards`.

## Local rules
- Nothing animates without a recorded event (HR-1–HR-7, PRD 9.4); `src/honesty/` (FR-WLD-09) fails on animation APIs outside `choreographer.ts` (allowlist: `test-support/honestyScan.ts`).
- One primary filled button per screen (UX-1); no streaks, hearts or fake urgency (UX-7).
