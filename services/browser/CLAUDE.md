# services/browser — `tilo-browser`

## Purpose
Cloud Run service with a proxy sidecar (PRD 6.2): one isolated headless browser per session,
allowlisted egress, masked secure fields, nothing persisted between runs.

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
- Reads/writes: `contracts/card.schema.json` needs-you cards via a `card_sink`; masked
  screenshots to Cloud Storage. No event type exists yet for a blocked egress request
  (`EgressPolicy.blocked` holds it for the caller).

## Config
- `config/connectors.yaml` (egress allowlist per adapter; not created yet, tests use literals).

## Requirement IDs
- Section 6.2 `tilo-browser` row; FR-CON-07, FR-CON-08, FR-CON-13; LW-08; SEC-09 (egress allowlist).

## Local rules
- One isolated browser per session; egress only through the allowlist proxy.
- Secure fields (passwords, payment) are masked and never persisted or logged.
- Tilo never types a credential: a login page raises a needs-you card, never a filled field.
- `tilo-browser` cannot read Firestore or Cloud Storage business data directly.
- Nothing from a run is kept once the run ends.
