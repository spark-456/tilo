# services/render — `tilo-render`

## Purpose
Cloud Run service (PRD 6.2): deliverables — PPTX, PDF, charts; Google Slides and Docs via
`tilo-connectors`. Priority "Must" covers PPTX and PDF for the hackathon build.

## Commands
- `uv run pytest "services/render" -q` — render tests (built by the AG-RENDER lane, `docs/lanes.md`).
- `just check` — full gate from the repo root.

## Contracts
- Reads: `packages/contracts-py` deliverable-spec types; `templates/`.
- Writes: artifact files to Cloud Storage (versioned).

## Config
- `templates/` (deliverable templates), `config/themes/` (chart styling).

## Requirement IDs
- Section 6.2 `tilo-render` row; FR-CON-09 (PDF and PPTX, data-bound charts); the render side of
  FR-CON-10 (provenance appendix). The HTTP service, auth and storage wiring are Claude lane CL-INT.

## Local rules
- Parsing, arithmetic, geometry, templates and charts are deterministic code, never a model
  call (section 6.6 "Deterministic first").
- Deliverables go through the outbox when they trigger a side effect (e.g. sharing).
