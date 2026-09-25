# apps/web

## Purpose
The Firebase-hosted web client (PRD 6.2): React UI, the PixiJS v8 isometric world, Story and
Trace lenses, cards and settings. P0-08a (this ticket) ships the shell only: token pipeline,
layout frame (left/right rail, bottom tabs) and the iso stage — no fixture player yet.

## Commands
- `just dev` or `pnpm --filter @tilo/web run dev` — dev server
- `pnpm --filter @tilo/web run build` / `test` / `test:e2e` — build / unit tests / Playwright
- `just tokens` — regenerate `src/styles/tokens.css` and `src/design/tokens.ts` from
  `design/tokens.json` (PRD 18.2); commit the result
- `just check` — full gate from the repo root

## Contracts
- Reads: `packages/contracts-ts` generated types; Firestore documents under security rules
  (never calls models, connectors or storage directly — writes only through `tilo-api`).
- Writes: none yet.

## Config
- `config/themes/` (world themes), feature flags.

## Requirement IDs
- UX-1 through UX-9 (section 18.1); FR-WLD-* (world rendering); owned starting P0-08.

## Local rules
- Nothing animates without a recorded event (honesty rules HR-1–HR-7, PRD 9.4).
- One primary filled button per screen (UX-1); no streaks, hearts or fake urgency (UX-7).
