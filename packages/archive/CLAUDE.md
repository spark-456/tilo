# packages/archive — `tilo_archive`

## Purpose
The raw archive (PRD 13.2, 15.1, 22.2 D-09): every model call, tool call and inbound/outbound
channel message, with secrets removed, stored as SHA-256-hashed, hash-chained JSONL records per
run so tampering is detectable. Redaction itself is not here: `RunArchive` takes an injected
redactor; FR-MEM-05 / SEC-14 supply the real one: `tilo_redact.redact_value`.

## Commands
- `uv run --package tilo-archive pytest packages/archive/tests` — tests
- `uv run python -m tilo_archive.verify <path to a run's .jsonl> [--head <seq>:<hash>]` — verify
  one run's chain (`--head` also catches a cut tail); prints
  `{"ok": bool, "records": N, "problems": [...]}`, exits 1 on any problem
- `just check` — full gate (fmt, lint, typecheck, tests) from the repo root

## Contracts
- `contracts/common.schema.json` `$defs.run_id` (`^r_[0-9A-Za-z_]{1,48}$`) / `$defs.org_id`
  (`^org_[0-9A-Za-z_]{1,48}$`): `RunArchive` rejects any id that does not match, before writing.
- `contracts/event.schema.json` `$defs.archive_ref` (unmerged P0-03 branch) —
  `"<run id>/<record seq>"`, pattern `^r_[0-9A-Za-z_]{1,48}/[0-9]{1,9}$`. `RunArchive.append`
  returns exactly this shape; nothing else is used from that branch.

## Local rules
- Standard library only at runtime. No import from `scripts/`.
- `RunArchive(..., redactor=...)` is a required keyword with no default, so nothing archives an
  unredacted payload by omission. Tests pass an identity redactor; production passes FR-MEM-05's.
- `RunArchive.append` runs the redactor, then hashes and serialises the redactor's output. A
  raising redactor, NaN/Infinity or a non-JSON-serialisable payload is a `ValueError` with
  nothing written (fail closed); the redactor's own message is not chained into the error.
- Error messages never echo caller input or stored content: an invalid kind names the allowed
  kinds, a non-object stored line names its JSON type, a redactor failure its exception type.
- `LocalDirStore` never rewrites an existing line. A `GcsStore` was left out (optional per the
  brief); add it behind the same `Store` protocol, tested only against a mock client.
- Encryption at rest is the bucket's KMS key (infra, P0-07) — nothing here encrypts anything.

## Requirement IDs
FR-MEM-04. (FR-MEM-05 / SEC-14 redaction: `packages/redact`.)
