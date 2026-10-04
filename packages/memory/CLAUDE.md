# packages/memory — `tilo_memory`

## Purpose
Pillar P7 memory layers (PRD 13.1). Today only the result cache: a web, file or email-body result is
reused instead of refetched when it is fresh and a fit check and the Verifier both accept it. Every
reuse is one `memory.hit` event and is the only thing credited as saved (PRD 14.3).

## Commands
- `uv run pytest packages/memory/tests -q` — acceptance and property tests (fakes only, network blocked)
- `just check` — full gate from the repo root

## Contracts
- Builds `memory.hit` (`contracts/events/data/memory.hit.schema.json`, EV-09: `saved` = `origin_cost` minus
  `lookup_cost`), validated with `tilo_contracts`. Returns events, never writes them: the harness is the
  single writer and owns `seq` (the caller passes it). There is no `memory.miss` type (BQ-192): a miss is a
  record in `cache.log`, not an event.

## Config
- None yet. `lookup_cost` is a constructor argument; the 7-day web window is a constant (PRD 13.1).

## Local rules
- Key = kind + whitespace-normalised request text + source fingerprint (no case folding, BQ-190).
- Web results are fresh while age is at most 7 days; files until their fingerprint changes; email bodies are
  never stored. A refetch replaces the entry and restarts its age.
- `fit_check` and `verifier` are injected `(request, value) -> bool`. Production wires both through
  `packages/providers` (PL-01, role `verifier`); no model id or model call lives here. Both must accept; a
  rejected entry is never served and the fresh result replaces it (BQ-193).
- Time comes only from the injected clock; nothing sleeps and nothing touches the network.

## Requirement IDs
FR-MEM-01, FR-MEM-02. (FR-MEM-03 to FR-MEM-09 are separate tickets.)
