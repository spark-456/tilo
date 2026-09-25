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

## Local rules
- Nothing animates without a recorded event (honesty rules HR-1–HR-7, PRD 9.4).
- One primary filled button per screen (UX-1); no streaks, hearts or fake urgency (UX-7).
