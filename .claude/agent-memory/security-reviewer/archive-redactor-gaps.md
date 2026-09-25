---
name: archive-redactor-gaps
description: FR-MEM-04/05 + SEC-14 (packages/archive, tilo_archive.redact) r1-r5 FAIL on 2026-09-25; r5 open bypass is PEM private key body left in clear
metadata:
  type: project
---

FR-MEM-04/05/SEC-14 (branch feat/FR-MEM-04-raw-archive, base origin/phase0-stack). Rounds r1 to r5 all FAILED on 2026-09-25.

r5 biggest: redact.py:40 replaces only the "-----BEGIN ... PRIVATE KEY-----" header line. The base64 key body and the END line stay in clear in the archive JSONL, in log lines (RedactingFilter) and in redact_prompt. A service-account JSON quoted as a string keeps its private_key body and private_key_id. The tests (test_FR_MEM_05 FAKE_SECRET_BUILDERS) only build the header marker, so they never see this. The fix: redact from BEGIN to the matching END (both real "\n" and JSON-escaped "\\n"), or to the end of the text when there is no END. Find it with str.find, not a lazy `[\s\S]*?` regex, because that goes quadratic with many BEGINs and no END.

Closed at r5: all the r4 card probes leak 0 of 300. Those were cards after "10 20 30 40 50 ", after "32 YYYY-MM-DD ", after "YYYY-MM-DD ", after "YYYY ", and a card between runs of stray digits. Chain tampering, the append-only store, and the NaN, inf and non-JSON rejections all still pass. Oversize input and depth over 64 fail closed.

Follow-ups (out of scope or secondary):
- A card as a JSON number ({"n": 4111...}) or as an int dict key is not masked. Only str values are scanned.
- The card scan is linear, but "1 " * 500k takes 58 s per redact call (it was 5.3 s/MB at r4). This is a DoS from untrusted inbound text.
- These card forms are missed: separators other than a single space or dash (a double space, NBSP, tab, ".", "/"), and two cards glued with no separator.
- Also still open: a JWT glued to a word character, x-api-key, Basic auth, a Cookie header inside free text, log `extra` fields, no expected run id in verify_chain or the CLI, and the verify CLI crashes on a missing path.

**Why:** the redaction backstop is the last line before the archive, logs and prompts (PRD 16.1 rule 4, 16.4 SEC-14). Every round has closed the probe it was given and missed the next adjacent case. The builder's tests check a detection marker, not whether the secret itself is gone.
**How to apply:** next round, rerun the PEM body probe first. Build a random base64 body at runtime and check the redacted output, the archive line, a log line and redact_prompt, for both a raw PEM and one quoted inside JSON. Then rerun the r4 card contexts and the chain probes. Also check the markers of every other pattern, and ask whether the secret material next to each marker survives.
