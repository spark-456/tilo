# services/sandbox-web — `tilo-sandbox-web`

## Purpose
Cloud Run service (PRD 6.2): fictional sites used by scenarios and evals, so `tilo-browser`
has safe, deterministic targets instead of the live internet.

## Commands
- `uv run pytest "services/sandbox-web/tests" -q` — acceptance tests (P8-07; failing until
  `tilo_sandbox_web` and its `services/sandbox-web/pyproject.toml` land on `feat/P8-07-sandbox-web`).
- `just check` — full gate from the repo root.

## Contracts
- Reads: `evals/cases/` and `evals/checks/` fixtures for the pages it must serve.
- Writes: none (static/generated fictional site content only).

## Config
- None yet; scenario config lives in `config/scenarios/` once scenarios are built.

## Requirement IDs
- Section 6.2 `tilo-sandbox-web` row; supports EV-* eval acceptance tests.

## Local rules
- Public ingress allowed (needed for browser-worker eval runs), but serves only fictional,
  fixture-driven content — never proxies real third-party sites.
- No scenario-specific code without a pillar requirement backing it.
