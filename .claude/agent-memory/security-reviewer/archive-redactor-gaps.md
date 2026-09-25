---
name: archive-redactor-gaps
description: FR-MEM-04/05 + SEC-14 (packages/archive, tilo_archive.redact): r1-r5 FAIL, r6 PASS at ae17c83 (whole-PEM redaction, "\n"-only JSONL reads); open follow-ups listed
metadata:
  type: project
---

FR-MEM-04/05/SEC-14, branch feat/FR-MEM-04-raw-archive (PR #37), worktree sh-feat-mem04. r1-r5 FAIL (2026-09-25). r6 (one round past the cap) PASS on 2026-09-26 at ae17c83.

Closed at r6: the whole PEM block is found with str.find (BEGIN, then a flat `[A-Z ]*` label, then the exact matching END). With no END it redacts to the end of the value. 800 probes found no body or END leak: 7 labels, 5 separators (\n, \r\n, literal \\n, double-escaped, space), END present or not, across redact, archive JSONL, redact_prompt and 7 log shapes (msg, %s, %r, bytes, split header and body, exception, dict arg). The worst 1 MB adversarial PEM input took 0.25 s (long labels, near-miss END lines, many BEGINs). JSONL readers split on "\n" only. U+2028/2029/0085 round-trip, and CRLF files reopen clean. json.dumps escapes every char below 0x20, so a payload cannot inject a "\n" split.

Open follow-ups (out of scope at r6, flagged):
- The value of private_key_id survives inside a JSON-quoted service-account string, including redact_prompt(json.dumps(sa_dict)). It is only redacted as a dict key. Low risk: it is the public JWT `kid`.
- These PEM-like forms are not redacted: PGP "PRIVATE KEY BLOCK" armour, labels with digits (SM2, ED25519), SSH2 "---- BEGIN" and URL-encoded PEM.
- A PEM stored as a list of lines, or split across a key and its value: only the element that holds BEGIN is redacted.
- camelCase secret keys (privateKey, privateKeyId, apiKey) are not secret-named. A headerless base64 key body under one of them leaks.
- Still open from r5: cards held as JSON numbers, "1 " * 500k takes 58 s, card separators other than a space or dash, a JWT glued to a word character, x-api-key, Basic auth, log `extra` and stack_info, and verify_chain has no expected run id.

**Why:** this redactor is the last guard before the archive, the logs and the prompts (PRD 16.1 rule 4, SEC-14). Every round closed the probe it was given and missed the one next to it.
**How to apply:** if the redactor is reopened, probe for the secret material itself, not the marker. Build it at runtime, then check each output path: archive file, log line, redact_prompt. Test every encoding the payload could arrive in.
