# packages/redact — `tilo_redact`

## Purpose
The one shared secret redactor (FR-MEM-05, SEC-14; PRD 13.2, 16.1 rule 4, 16.2): `redact(text)`, `redact_value(tree)`,
`REDACTED` and `RedactingFilter` for logs. Standard library only, a leaf: every other package may depend on it.

## Commands
- `uv run pytest -q packages/redact/tests` — tests (fake secrets are assembled at runtime in `_redact_samples_lib.py`)
- `just check` — full gate from the repo root

## Contracts
- Reads none. `contracts/manifest.rules.md` MF-06 and the artifact store's AR-07 refuse content this redactor would
  change, so a false positive breaks real work: add a keeps test with every new rule.

## Config
- None. Rules are code; nothing is read from the environment.

## Requirement IDs
FR-MEM-05, SEC-14. Wired into `tilo_providers.router` (prompt, system, tool outputs), `tilo_api.deps.get_redactor`.

## Local rules
- Deterministic and idempotent: `redact(redact(t)) == redact(t)`. A clean text is returned unchanged (replay keys hash it).
- Emails and phone numbers stay. A card is 13 to 19 Luhn-valid digits, never starting with 0, and not a plain 13-digit
  epoch-millisecond timestamp (BQ-FRMEM05-1). Secure fields are the nine exact keys in `SECURE_KEYS`.
- `RedactingFilter` never drops or raises. NFR-26's JSON formatter must attach it.
- Other redactors (`google_adapter`, `model_armor_adapter`, `skill_proposals`, connectors `recording`) are not yet
  folded into this one; do that as a follow-up, not silently.
