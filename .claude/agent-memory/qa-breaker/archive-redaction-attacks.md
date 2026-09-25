---
name: archive-redaction-attacks
description: FR-MEM-04/05 tilo_archive redaction attacks that found real leaks (JWT regex, log args, PEM split across msg/args)
metadata:
  type: project
---

Recurring leak class in packages/archive redact.py: per-fragment redaction runs before whole-line scanning.
- Round 6 (2026-09-26): RedactingFilter runs structural redact() on each arg first; a PEM header passed as its own
  arg fails-closed to "[REDACTED:private_key]", which destroys the BEGIN marker, so the composed-line scan no longer
  sees a block and the base64 body + END line (in msg or other args) print in clear. Same for a payload list of PEM lines.
- Label rule "ends with PRIVATE KEY" misses PGP "PRIVATE KEY BLOCK", digit labels (SSH2), trailing-space labels.
- Earlier rounds: quadratic JWT regex, log arg leaks, verify CLI crash on partial line.

**Why:** builders fix the exact repro; fragment-then-compose ordering keeps reappearing.
**How to apply:** always attack secrets split across log msg/args and list elements; build fake keys at runtime.
