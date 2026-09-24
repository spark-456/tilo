# packages/contracts-ts

## Purpose
Generated TypeScript types for the `contracts/` JSON Schemas and event registry — the TS side
of Tilo's single source of truth for shapes crossing a service boundary, consumed by `apps/web`.

## Commands
- Generation script and command land with ticket P0-02 (owns `contracts/`).
- `just check` — full gate from the repo root once generation exists.

## Contracts
- Reads: `contracts/schemas/`, `contracts/events/` (owned by ticket P0-02; read-only from here).
- Writes: `src/` — generated types only, never hand-edited (see `.gitattributes`
  `linguist-generated=true`).

## Config
- None directly; generation is driven by `contracts/` itself.

## Requirement IDs
- Supports FR-* / NFR-* wherever `apps/web` needs a typed contract object. Owned by P0-02.

## Local rules
- Nothing in this directory is hand-written except this file and generation tooling.
- CI fails on drift between `contracts/` and the generated output (schema drift = automatic FAIL).
- This ticket (P0-01) creates the empty directory and this file only.
