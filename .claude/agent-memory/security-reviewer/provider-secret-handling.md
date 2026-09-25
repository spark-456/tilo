---
name: provider-secret-handling
description: Provider-layer (packages/providers) API key, recording and egress gaps found in P0-05 r1 and r2; check on router (P0-06), openai_compat contract change, connector/HTTP adapter tickets
metadata:
  type: project
---

P0-05 round 1 (88f1f33, 2026-09-25) FAIL.
- Key leak into exceptions: openai_compat adapter puts `Bearer {key}` in httpx client headers and maps every httpx.HTTPError to RetryableError(str(error)). A key with a trailing CR/LF (common on Windows pastes) makes h11 raise "Illegal header value b'Bearer <key>\r'" and the key lands in the exception text, classed retryable. Tests only used MockTransport, which skips h11, so no test caught it. Probe: loopback socket listener + real transport (conftest allows loopback).
- Error bodies copied verbatim into exceptions (response.text fallback); `{"error": "string"}` raises unmapped AttributeError.
- base_url has no scheme/host allowlist (http:// accepted, bearer in cleartext); api_key_env can name any env var. Only constructor args today; re-check when the contract adds base_url/api_key_env to $defs.profile.
- CI /etc/hosts block lists googleapis hosts only; integrate.api.nvidia.com not added.
- Recording writes response only (no request, no headers); that part was fine.
- Builder left a failing test (NIM file through loader) as "needs contract change".

P0-05 round 2 (7d1e451, 2026-09-25) FAIL. Fixed: clean-token check at construction, fixed messages + `from None` in _post, NIM host in CI block, string error field.
- New bug: `_scrub` truncates to 500 chars BEFORE replacing the key, so a key straddling the boundary leaks its prefix (nearly whole key if echoed at ~offset 460). Test only used a short body. Pattern: always redact first, truncate second.
- Still open: http:// and any host accepted for base_url; any env var for api_key_env; recordings not scrubbed for the key if an endpoint echoes it into content; `from None` still leaves key in `__context__` (standard formatters and Sentry honour suppress, so minor).
- Factory raises NotImplementedError for openai_compat until contract adds base_url/api_key_env, so no untrusted input reaches base_url yet.

P0-05 round 3 (26a844d, 2026-09-25) FAIL, but only on the auto-fail rule: `just check` red because the NIM-loader test is contract-blocked (xfail removed). Security fixes held: redact-then-truncate verified with 81 probe cases (offsets 0-518, non-JSON 200, bad SSE, 429 string, embed KeyError), all clean. LIVE=1 alone now goes live (TILO_RECORD=1 adds recording), live adapter built lazily. Still open, not yet reachable: http:// base_url accepted by the adapter constructor; echoed key in response content is not scrubbed from recordings.

P0-05 round 4 (ca3157b, 2026-09-25) FAIL, again only on the contract-blocked NIM-loader test (contract still lacks base_url/api_key_env). https-only base_url check holds: 21 probe URLs (userinfo tricks, nip.io, 127.1, decimal IP, backslash, scheme-less) all reject or resolve to loopback; follow_redirects False. New live stream recording (_join_chunks) still writes an echoed key into fixtures/model-recordings. scripts/secret_scan.py (and guard hook) have no `nvapi-` pattern, so a NIM key in a committed recording or fixture is not caught. No test covers the https-only rejection. FAKE_KEY in tests is a literal, not runtime-assembled.

P0-05 round 5 (still ca3157b, 2026-09-25) FAIL, no new commits. The same NIM-loader test fails (extra_forbidden base_url/api_key_env) because P0-02b is still not merged into phase0-stack. The fix is ordering, not code: merge P0-02b, merge it into P0-05, then wire openai_compat in the factory. If a round comes back with the same head, check `git log` first. Round 6 (2026-09-25) was the same head with the same result (1 failed, 100 passed). P0-02b (5bc8d4a) was still not an ancestor of phase0-stack or P0-05. Round 7 (2026-09-25): same head ca3157b, same 1 failed / 100 passed, P0-02b still not in phase0-stack (base tip e38b01b). The workflow keeps re-sending this ticket without the merge; say plainly that the orchestrator must merge P0-02b first. Round 8 (2026-09-25): the task claimed head e38b01b, but that is the phase0-stack tip. The branch was still ca3157b: same 1 failed / 100 passed, secret_scan --all-tracked clean, .env.example placeholders only. Always check `git rev-parse <branch>` against the head the task claims.

P0-02b round 1 (5bc8d4a, 2026-09-25) PASS. The contract now has profile base_url (https, no userinfo/query/fragment, `not` pattern for a trailing \n) and api_key_env (`^[A-Z][A-Z0-9_]{2,63}$`), and an if/else limits both to openai_compat. The nvapi- pattern is the same in scripts/secret_scan.py and guard.py; --all-tracked is clean and doc placeholders (`nvapi-<key>`, `nvapi-xxxx`) are not flagged. Open hand-off: the generated pydantic ProvidersProfile (the only validator load_providers_config runs) drops the if/else, so a google or fake profile with base_url/api_key_env loads. That is harmless today because the P0-05 factory dispatches on provider, but the loader should reject it by hand, the way P0-04 handles the prices if/then. The path segment can still hold a token (for example /v1/<token>), and only key formats the scanner knows are caught. api_key_env can name any variable (BQ-33 accepts this).

**Why:** root CLAUDE.md and PRD 16.1 rule 4: no secrets in logs or exceptions; EFF-01 no paid calls in CI. Router retries RetryableError and will log messages.

**How to apply:** on any adapter or HTTP client ticket, probe with a malformed key (CR/LF, non-ASCII) through a real transport, not only MockTransport; probe redaction with a long body where the secret straddles any truncation limit; grep for str(error) passed into provider errors; check the CI egress block covers every endpoint in config/. When base_url lands in the profile contract, require https-only (loopback exempt in tests) and re-check. When a new provider's key format enters the repo (e.g. `nvapi-`), check the secret scanner and guard hook patterns cover it.
