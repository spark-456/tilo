# packages/archive — `tilo_archive`

## Purpose
The raw archive (PRD 13.2, 15.1, 22.2 D-09): every model call, tool call and inbound/outbound
channel message, with secrets removed, stored as SHA-256-hashed, hash-chained JSONL records per
run so tampering is detectable. Also the redaction backstop (SEC-14, PRD 16.1 rule 4): connector
tokens stay in the token broker and Tilo never handles passwords, so this catches anything that
slips through — known credential formats, secret-named fields, card numbers — before it reaches
the archive, a log line or a prompt.

## Commands
- `uv run --package tilo-archive pytest packages/archive/tests` — tests
- `uv run python -m tilo_archive.verify <path to a run's .jsonl>` — verify one run's chain;
  prints `{"ok": bool, "records": N, "problems": [...]}`, exits 1 on any problem
- `just check` — full gate (fmt, lint, typecheck, tests) from the repo root

## Contracts
- `contracts/common.schema.json` `$defs.run_id` (`^r_[0-9A-Za-z_]{1,48}$`) / `$defs.org_id`
  (`^org_[0-9A-Za-z_]{1,48}$`): `RunArchive` rejects any id that does not match, before writing.
- `contracts/event.schema.json` `$defs.archive_ref` (unmerged P0-03 branch) —
  `"<run id>/<record seq>"`, pattern `^r_[0-9A-Za-z_]{1,48}/[0-9]{1,9}$`. `RunArchive.append`
  returns exactly this shape; nothing else is used from that branch.

## Local rules
- Standard library only at runtime. No import from `scripts/`; `redact.py` reproduces the nine
  patterns in `scripts/secret_scan.py` by hand, independently, same as that script's own note.
- `redact()` is not a general DLP: secret-named keys, the patterns above plus bearer tokens and
  JWTs, and Luhn-valid card numbers (13–19 digits) reduced to their last 4 — nothing beyond that.
- `redact()` never raises. Oversize text (over `MAX_SCAN_CHARS`, 1,000,000) is replaced whole,
  fail closed; nesting beyond depth 64 becomes `"[REDACTED:too_deep]"`.
- `RunArchive.append` redacts, then hashes and serialises; NaN/Infinity and non-JSON-serialisable
  payloads are rejected there (`ValueError`, nothing written) — `redact()` itself never rejects.
- `LocalDirStore` never rewrites an existing line. A `GcsStore` was left out (optional per the
  brief); add it behind the same `Store` protocol, tested only against a mock client.
- Encryption at rest is the bucket's KMS key (infra, P0-07) — nothing here encrypts anything.

## Requirement IDs
FR-MEM-04, FR-MEM-05, SEC-14 redaction part.
