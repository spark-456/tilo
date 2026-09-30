---
name: archive-redactor-gaps
description: FR-MEM-04/05 + SEC-14 (packages/archive). Redactor r1-r5 FAIL, r6 PASS (ae17c83), then the ticket was split. FR-MEM-04-only split r1 PASS (2bcb609). Open items listed for the shared-redactor redo.
metadata:
  type: project
---

PR #37 history. Redactor rounds r1-r5 FAILED (2026-09-25). r6 PASSED at ae17c83 (2026-09-26). After that, QA could not close chunked-PEM detection, so the orchestrator split the ticket. Branch split/FR-MEM-04 at 2bcb609 deleted redact.py and the FR-MEM-05 tests. `RunArchive` now takes a required `redactor=` keyword with no default.

Split r1 PASSED on 2026-09-26. It was flagged in r1-r5, so the user must still approve the merge.
- A missing redactor raises TypeError at construction.
- None, or a redactor that raises, gives ValueError: the message has the exception type name only, it is raised `from None`, and nothing is written.
- The identity redactor exists only in tests/conftest.py. At 2bcb609 no production code constructs RunArchive.
- The verify CLI prints counts and problem strings only, never payloads. The package does no logging.

Non-blocking findings at the split:
- archive.py:134 echoes `kind!r` without bound, before redaction. If a caller swaps the arguments, the whole payload lands in the error text.
- archive.py:94 (reopen) echoes an entire non-object stored line.
- `__context__` still holds the original exception. No Sentry is in uv.lock, so this is only a note.

Carry to the FR-MEM-05/SEC-14 redo on the shared module. Nothing in docs/ tracks it yet.
- MF-06 (contracts/manifest.rules.md:16) and ADR-0002:179 name "the redactor that guards the raw archive", which no longer exists.
- Items still open from r6:
  - chunked or list-of-lines PEM
  - PGP armour and digit labels
  - camelCase secret keys
  - cards stored as JSON numbers
  - separators other than a space or dash
  - "1 " * 500k takes 58 s (DoS)
  - x-api-key, Basic auth, Cookie header in free text
  - log `extra` and stack_info

**Why:** the redactor is the last guard before the archive, logs and prompts (PRD 16.1 rule 4, SEC-14). Every round closed the probe it was given and missed the one next to it. The builder's tests checked a detection marker, not whether the secret itself was gone.
**How to apply:**
- When the harness or channels first wire RunArchive, check what they pass as `redactor`. Identity or a lambda is an automatic FAIL.
- When the shared redactor is reviewed, build secrets at runtime. Probe for the secret material itself, not its marker. Check every output: the archive line, log records and the prompt path.
