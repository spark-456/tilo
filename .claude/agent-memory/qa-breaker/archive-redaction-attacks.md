---
name: archive-redaction-attacks
description: FR-MEM-04/05 tilo_archive attacks that broke round 1 - quadratic JWT regex, log arg leaks, CLI crash on partial line
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
**Why:** these recur in any regex-based redactor or log filter.
**How to apply:** rerun these probes on any redaction or archive rework. See [[skill-checker-attacks]].
