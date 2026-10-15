# services/render — `tilo-render`

## Purpose
Cloud Run service (PRD 6.2): deliverables — PPTX, PDF, charts; Google Slides and Docs via
`tilo-connectors`. Priority "Must" covers PPTX and PDF for the hackathon build.

## Commands
- `uv run pytest "services/render" -q` — render tests (built by the AG-RENDER lane, `docs/lanes.md`).
- `just check` — full gate from the repo root.
- Image: `Dockerfile` runs `tilo_render.app:app` (`/health` for Cloud Run smoke checks, `/healthz` for in-container probes; P0-07a, P0-07h); deploy: `docs/deploy-dev.md`.

## Contracts
- Reads: `packages/contracts-py` deliverable-spec types; `templates/`; `design/tokens.json`.
- HTTP (`POST /render`, LW-11): service-to-service Google OIDC Bearer auth before body read (`create_app(oidc_verifier=..., audience=..., allowed_callers=...)`; fails closed with 401/403 when missing or unconfigured). Accepts JSON `{"format": "pdf" | "pptx", "spec": DeliverableSpec}` (`extra="forbid"`; `manifest` is omitted from JSON because `tilo-harness` attaches provenance in `outputs.keep`). Returns deterministic file bytes with `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`.
- `tilo_render.xlsx.render_xlsx` (DOCS-OUT A4) turns a spec's tables into a workbook in process in `tilo-api` (not on the HTTP door), capped at 7000 cells.
- Writes: PDF/PPTX bytes to the HTTP response; this service does not persist artifacts or write to Cloud Storage. The harness attaches provenance and stores accepted outputs through `outputs.keep`.

## Config
- `templates/` (deliverable templates), `config/themes/` (chart styling), `design/tokens.json`.
- `TILO_RENDER_AUDIENCE` and comma-separated `TILO_RENDER_ALLOWED_CALLERS` configure the expected Google OIDC audience and caller service-account allowlist when not passed explicitly to `create_app()`.
- A trusted Google OIDC verifier must also be supplied to `create_app(oidc_verifier=...)`. The module-level `app = create_app()` does not install one: `/health` and `/healthz` work, but `/render` returns 401 without a valid Bearer header and 403 with a well-formed Bearer header, before reading the body. Setting the audience and caller environment variables alone does not enable rendering.

## Requirement IDs
- Section 6.2 `tilo-render` row; FR-CON-09 (PDF and PPTX, data-bound charts); the render side of
  FR-CON-10 (provenance appendix); LW-11 (`POST /render` with service-to-service auth, ADR-0029).

## Local rules
- Parsing, arithmetic, geometry, templates and charts are deterministic code, never a model
  call (section 6.6 "Deterministic first").
- `POST /render` enforces hard caps (`MAX_BODY_BYTES = 1 MiB` before JSON parsing, `DEFAULT_RENDER_TIMEOUT = 15s` via `run_in_threadpool`, `DEFAULT_MAX_CONCURRENCY = 2` returning 429 `busy`, `MAX_OUTPUT_BYTES = 20 MiB`) and logs/returns fixed reason codes only — never echoing untrusted spec text, paths, or exception details.
- A timed-out running renderer retains its concurrency slot until its worker exits; the HTTP timeout does not stop that thread. A request cancelled or timed out before its worker starts returns the unclaimed slot.
- Deliverables go through the outbox when they trigger a side effect (e.g. sharing).
