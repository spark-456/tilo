# services/render — `tilo-render`

## Purpose
Cloud Run service (PRD 6.2): deliverables — PPTX, PDF, charts; Google Slides and Docs via
`tilo-connectors`. Priority "Must" covers PPTX and PDF for the hackathon build.

## Commands
- Package and dev/test commands land with the render code (ticket P6+).
- `just check` — full gate from the repo root.

## Contracts
- Reads: `packages/contracts-py` deliverable-spec types; `templates/`.
- Writes: artifact files to Cloud Storage (versioned).

## Config
- `templates/` (deliverable templates), `config/themes/` (chart styling).

## Requirement IDs
- Section 6.2 `tilo-render` row; charting/rendering acceptance tests as pillars land.

## Local rules
- Parsing, arithmetic, geometry, templates and charts are deterministic code, never a model
  call (section 6.6 "Deterministic first").
- Deliverables go through the outbox when they trigger a side effect (e.g. sharing).
