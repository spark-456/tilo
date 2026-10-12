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
- Writes: artifact files to Cloud Storage (versioned).

## Config
- `templates/` (deliverable templates), `config/themes/` (chart styling), `design/tokens.json`.
- `TILO_RENDER_AUDIENCE` and comma-separated `TILO_RENDER_ALLOWED_CALLERS` configure the expected Google OIDC audience and caller service-account allowlist when not passed explicitly to `create_app()`.

## Requirement IDs
- Section 6.2 `tilo-render` row; FR-CON-09 (PDF and PPTX, data-bound charts); the render side of
  FR-CON-10 (provenance appendix); LW-11 (`POST /render` with service-to-service auth, ADR-0029).

## Local rules
- Parsing, arithmetic, geometry, templates and charts are deterministic code, never a model
  call (section 6.6 "Deterministic first").
- `POST /render` enforces hard caps (`MAX_BODY_BYTES = 1 MiB` before JSON parsing, `DEFAULT_RENDER_TIMEOUT = 15s` via `run_in_threadpool`, `DEFAULT_MAX_CONCURRENCY = 4` returning 429 `busy`, `MAX_OUTPUT_BYTES = 20 MiB`) and logs/returns fixed reason codes only — never echoing untrusted spec text, paths, or exception details.
- Deliverables go through the outbox when they trigger a side effect (e.g. sharing).
