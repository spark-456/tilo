# services/browser — `tilo-browser`

## Purpose
Cloud Run service with a proxy sidecar (PRD 6.2): one isolated headless browser per session,
allowlisted egress and masked secure fields. `BrowserWorker.close()` closes that run's context;
the separate LW-08 fetch path archives accepted output for the run.

## Commands
- `uv run pytest services/browser -q` — FR-CON-07 and FR-CON-08 tests (fakes only, no browser, no network).
- `uv run mypy services/browser/src`; `just check` — full gate from the repo root.
- Image: `Dockerfile` runs `tilo_browser.app:app` (`/health` for Cloud Run smoke checks, `/healthz` for in-container probes; P0-07a, P0-07h); deploy: `docs/deploy-dev.md`.

## Code (`src/tilo_browser/`)
- `egress.py` — `EgressPolicy.check`: deterministic allowlist; logs every `Decision`, never a query or userinfo.
- `masking.py` — `mask_text` / `mask_data`: the one masker for anything that leaves a worker.
- `login.py` — `detect_login`, `secure_field_refs`, `build_login_card` (needs-you card; FR-CON-08).
- `worker.py` — `BrowserWorker`, a `HandsProvider` over `engine.new_context(gate)`; one worker = one run.
- `fetch.py` — `FetchService` and `POST /fetch` (LW-08): service-to-service HTTPS GET fetcher with SSRF IP pinning, `robots.txt` check, size/unit caps, magic-byte sniffing, HTML text extraction, and `RunArchive` writing.

## Contracts
- Outputs: `contracts/card.schema.json` needs-you cards via a `card_sink`; masked
  screenshots returned to the caller. No event type exists yet for a blocked egress request
  (`EgressPolicy.blocked` holds it for the caller).
- LW-08: `RawArchiveStore` stores accepted fetched bytes (HTML becomes cleaned text) by SHA-256
  and appends a hash-chained `tool_call` record through `RunArchive`. The default store is local
  `.tilo-archive`, not Cloud Storage; no automatic deletion at run end is implemented here.

## Config
- `config/connectors.yaml` exists as the connector catalogue; this service does not load it as
  an egress allowlist. Callers construct `EgressPolicy(allow=...)`; `FetchService(base_allow=...)`
  combines its base list with the request's `allow_hosts` and `task_allowlist`. Tests use literals.
- `POST /fetch` requires an explicitly configured `create_app(oidc_verifier=..., audience=...,
  allowed_callers=...)`. The module-level `app = create_app()` is unconfigured: missing Bearer
  tokens receive 401 and Bearer requests receive 403 before the body is read or a fetch runs.

## Requirement IDs
- Section 6.2 `tilo-browser` row; FR-CON-07, FR-CON-08, FR-CON-13; LW-08; SEC-09 (egress allowlist).

## Local rules
- One isolated browser per session; egress only through the allowlist proxy.
- Secure fields (passwords, payment) are masked and never persisted or logged.
- Tilo never types a credential: a login page raises a needs-you card, never a filled field.
- `tilo-browser` cannot read Firestore or Cloud Storage business data directly.
- Closing a worker ends its browser context. LW-08 archived output has a separate lifecycle;
  worker shutdown does not erase it or implement an archive retention policy.
