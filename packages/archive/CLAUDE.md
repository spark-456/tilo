# packages/archive — `tilo_archive`

## Purpose
The raw archive (PRD 13.2, 15.1, 22.2 D-09): every model call, tool call and inbound/outbound
channel message, with secrets removed, stored as SHA-256-hashed, hash-chained JSONL records per
run so tampering (an edit, insertion, deletion or reordering, or a truncated tail) is detectable.
Also the redaction backstop (SEC-14, PRD 16.1 rule 4): connector tokens stay in the token broker
and Tilo never handles passwords, so this package exists to catch anything that slips through —
known credential formats, secret-named fields and payment card numbers — before it reaches the
archive, a log line or a prompt.

## Commands
- `uv run --package tilo-archive pytest packages/archive/tests` — tests
- `uv run python -m tilo_archive.verify <path to a run's .jsonl>` — verify one run's chain from
  the command line; prints `{"ok": bool, "records": N, "problems": [...]}`, exits 1 on any problem
- `just check` — full gate (fmt, lint, typecheck, tests) from the repo root

## Contracts
- `contracts/common.schema.json` `$defs.run_id` (`^r_[0-9A-Za-z_]{1,48}$`) and `$defs.org_id`
  (`^org_[0-9A-Za-z_]{1,48}$`): `RunArchive` rejects any id that does not match, before writing
  anything.
- `contracts/event.schema.json` `$defs.archive_ref` (only on the unmerged P0-03 branch) —
  `"<run id>/<record seq>"`, pattern `^r_[0-9A-Za-z_]{1,48}/[0-9]{1,9}$`. `RunArchive.append`
  returns exactly this shape; not imported from that branch since this package needs nothing else
  from it.

## Local rules
- Standard library only at runtime. No import from `scripts/` (root CLAUDE.md); `redact.py`
  reproduces the nine patterns in `scripts/secret_scan.py` by hand, independently, the same way
  that script says its own copy is independent of the guard hook's — the two are kept in sync by
  hand on purpose, not by sharing code.
- `redact()` is not a general DLP. It covers exactly: values under secret-named keys (password,
  token, api_key, authorization, cookie, private_key, client_secret, refresh_token, access_token,
  pin, ...), the patterns above plus bearer tokens and JWTs, and Luhn-valid payment card numbers
  (13–19 digits) reduced to their last 4. Nothing beyond that threat model.
- `redact()` never raises. Oversize text (over `MAX_SCAN_CHARS`, 1,000,000) is replaced whole
  rather than scanned piecemeal — fail closed on a scan that can't run to completion. Nesting
  beyond a depth of 64 becomes `"[REDACTED:too_deep]"` rather than recursing further.
- `RunArchive.append` redacts, then hashes and serialises; NaN/Infinity and non-JSON-serialisable
  payloads are rejected there (`ValueError`, nothing written), not silently stored — `redact()`
  itself passes them through unchanged.
- `LocalDirStore` never rewrites an existing line; every write is an append. A `GcsStore` was
  left out of this ticket's scope (optional per the brief); add it only behind the same `Store`
  protocol in `archive.py`, tested only against a mock client, no network.
- Encryption at rest is the Cloud Storage bucket's KMS key (infra, ticket P0-07) — nothing in
  this package encrypts anything.

## Requirement IDs
- FR-MEM-04 (raw archive with per-record hashes and a per-run hash chain), FR-MEM-05 (secrets
  never reach the archive, logs or prompts), SEC-14 redaction part (raw archive redaction).
