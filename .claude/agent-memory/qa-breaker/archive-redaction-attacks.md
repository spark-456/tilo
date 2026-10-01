---
name: archive-redaction-attacks
description: FR-MEM-04/05 tilo_archive redaction attacks that found real leaks (JWT regex, log args, PEM split across msg/args)
metadata:
  type: project
---

FR-MEM-04 round 1 (2026-09-25) failed on redaction, not the hash chain.
- JWT regex `\b[A-Za-z0-9_-]{10,}\.` is quadratic on "a-"*n (80k chars = 25 s; 1 MB ~ an hour). Always time every regex on "a-"*n and "a."*n.
- RedactingFilter only redacts str args: dict/list args leak secret-named keys and tokens; a msg "Authorization: Bearer %s" + arg leaks the token (redact getMessage() instead).
- verify CLI and RunArchive reopen crash with a JSONDecodeError traceback on a partial last line instead of naming it.
- Hypothesis deadline flakes on the OneDrive path (200 ms).
- Round 2 (393f3ac): regexes fixed (1 MB adversarial < 1.2 s; card regex on "1 "*500000 ~5-8 s, linear), but the partial-last-line crash was still unfixed in verify.py and RunArchive.__init__. Round-1 findings get skipped; re-probe every one.
- Round 3 (1aed1b1): partial line fixed, but verify_chain crashes (AttributeError/TypeError) on a tampered line that is valid JSON but not an object (`null`, `[1]`) or has an unhashable seq; CLI also tracebacks on invalid UTF-8. Always tamper with type-changing edits, not just value edits. Copying another run's whole file passes the CLI (no expected run id).
- Round 4 (24deddc): all tamper cases caught; but a crash that leaves the last record without its trailing "\n" reopens silently, and the next append glues onto that line, destroying a good record and bricking reopen. Always test "strip only the final newline", not just a byte-truncated line. Also: duplicate JSON keys in a stored line pass verify (parser differential).
- Round 5 (9817e14): str.splitlines() in read_lines and verify CLI splits a legit record on raw U+2028/U+2029/ (ensure_ascii=False leaves them unescaped): one unicode append bricks reopen and fails verify. Always append payloads with U+2028 and  then reopen.
- Round 7 (edc993f): args got only key-level pass, so an arg that getMessage never renders (extra arg, %d on str) keeps any secret raw in record.args and logging's handleError prints it to stderr. Also: log args ordered body/END before header, nested lists, END+BEGIN in one list element, dict sibling values all leak PEM body. Always test format-error log calls. The 2 s adversarial timing test flakes under full-suite load.
- Round 8 (e9ecee0, _has_split_key): detection keys on whole BEGIN/END markers, so a PEM chunked at fixed sizes (11-30 bytes) that splits both markers leaks every body chunk. Always chunk a secret at every size 1..200, not only at line boundaries.
- Round 9 (71f4e99, join all strings then scan): dict KEY text is joined between values, so chunks stored as {"0":c0,"1":c1}, [{"chunk":c}...], {c:"x"}, or log dict args with a missing %(key)s (handleError stderr) break the marker and leak body at chunk sizes 17-30. Reversed chunk order leaks at 138/200 sizes. Always wrap chunks in per-item dicts.
- Round 10 (fa339b6, scans all / values-only / keys-only joins): any SECOND noise string per chunk breaks all three joins: [{"chunk": c, "id": str(i)}], [c, "|"] interleaved, [["line", c]], {i: {"c": c, "n": "z"}} leak body at sizes 17-30 in redact(), archive file and log. Marker-contiguity detection cannot survive interleaved noise; fuzz with 2+ noise fields per record. S0 split the ticket after this round (FR-MEM-05 redo on the shared redaction module).
**Why:** these recur in any regex-based redactor or log filter.
**How to apply:** rerun these probes on any redaction or archive rework. See [[skill-checker-attacks]].
Recurring leak class in packages/archive redact.py: per-fragment redaction runs before whole-line scanning.
- Round 6 (2026-09-26): RedactingFilter runs structural redact() on each arg first; a PEM header passed as its own
  arg fails-closed to "[REDACTED:private_key]", which destroys the BEGIN marker, so the composed-line scan no longer
  sees a block and the base64 body + END line (in msg or other args) print in clear. Same for a payload list of PEM lines.
- Label rule "ends with PRIVATE KEY" misses PGP "PRIVATE KEY BLOCK", digit labels (SSH2), trailing-space labels.
- Earlier rounds: quadratic JWT regex, log arg leaks, verify CLI crash on partial line.

**Why:** builders fix the exact repro; fragment-then-compose ordering keeps reappearing.
**How to apply:** always attack secrets split across log msg/args and list elements; build fake keys at runtime.
