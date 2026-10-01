---
name: intake-extraction-gaps
description: FR-INT-01/02 intake, r1-r4 FAIL, r5 PASS (07f3672); strict UTF-8 plus a raw allowlist bounds expat tokens; open follow-ups on xmlns CPU, screening wiring and ingress; tilo-api 512Mi
metadata:
  type: project
---

FR-INT-01/02 (`packages/planning` extraction/intake/artifacts, `POST /intake` in tilo-api) passed at r5, 07f3672, on 2026-09-26. It was flagged in r1-r4, so merging needs the user's approval.

What failed in each round:
- **r1:** a decompression budget for each file, and no screening result on stored versions.
- **r2:** attribute, giant-token and depth bombs, plus an EOCD count that could lie.
- **r3:** UTF-16 (0x3C inside CJK code units) and `<` inside comments, PIs and DOCTYPE literals.
- **r4:** a part starting with the UTF-16 BOM and containing no NUL bytes. expat switches encoding on the BOM even with a UTF-8 protocol encoding, and buffered 45 MB as one name token.

Final design:
- `check_raw` puts every chunk through a strict incremental UTF-8 decoder and rejects NUL bytes, any `<!`, and any `<?` except the leading declaration (closed within 256 bytes).
- Runs between `<` characters are capped at 256 KiB, depth at 256, and elements plus attributes at 1M per request.
- Decompressed bytes are capped at 50 MiB per request, text at 200k characters per file, and the central directory at 1 MiB, with zip64 refused.
- `StoredArtifact.screening` records clean, flagged or unscreened.

Open follow-ups:
- `xmlns:*` declarations are not in `attrs`: 299 tags × 8000 declarations costs 2.3 s of CPU.
- `screening` does not reach the policy engine yet, and `tiers.safety_flags` defaults to False.
- Typed text is not screened.
- Filenames go unscreened into event summaries.
- No sign-in, App Check or rate limit.
- The in-memory store is unbounded and unscoped.
- For #47: the provider must be thread-safe and must refuse media types it cannot screen.
- For #49: the ingress body cap.

Probe scripts in the session scratchpad: `probe_intake.py`, `probe_r2.py`, `probe_r3.py`, `probe_r3b.py` and `probe_r4.py`. Use tracemalloc for memory and `--time` for untraced timing.

**Why:** each round bounded one proxy. Only a strict allowlist (valid UTF-8, no `<!`, no stray `<?`) made the raw `<` run cap sound. expat's auto-detection (BOM, 3C 00, 00 3C) ignores the protocol encoding.

**How to apply:** for any byte-level guard in front of a parser, test the other encodings (UTF-16 with and without a BOM, with and without NUL bytes) and every token type in which the delimiter is legal. Check the peak against the 512Mi limit (infra/modules/service/main.tf:70). On later tickets (FR-INT-03, P4), check that the screening result reaches the policy engine and that a missing value means "not clean". Related: [[skill-checker-gaps]].
