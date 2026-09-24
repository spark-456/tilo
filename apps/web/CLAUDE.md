# apps/web

## Purpose
The Firebase-hosted web client (PRD 6.2): React UI, the PixiJS v8 isometric world, Story and
Trace lenses, cards and settings. No app code yet — ticket P0-08 builds it; this ticket adds
only this file so the pnpm workspace has a documented member slot.

## Commands
- `pnpm --filter tilo-web dev` — dev server (once P0-08 adds the app)
- `pnpm --filter tilo-web build` / `test` — build / test (once P0-08 adds the app)
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
