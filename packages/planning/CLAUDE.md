# packages/planning — `tilo_planning`

## Purpose
Pillar P1 intake and planning (PRD 7). FR-INT-01/02: `intake.submit_intake` enforces the limits,
types and extracts files (`extraction`), screens them with a `SafetyProvider` and stores them as
versioned artifacts with an origin record (`artifacts`).

## Commands
- `uv run pytest packages/planning` — tests; `just check` — full gate from the repo root

## Contracts
- Builds `world.requested` and `artifact.created` events validated with `tilo_contracts`
  (`Event`, `EVENT_DATA_MODELS`); returns them, never writes them (the harness is the writer).

## Local rules
- No model calls here. Extraction is stdlib only and treats uploads as untrusted (bounded
  decompression, no DTDs in XML).
- A rejected submission stores nothing: limits first, then extraction and screening, then storage.
- A flagged file's `artifact.created` has severity `fyi` and `trace.tool` `safety_provider`;
  `trace.archive_ref` stays null until the raw archive (P7) exists.
