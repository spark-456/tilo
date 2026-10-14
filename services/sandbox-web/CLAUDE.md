# services/sandbox-web — `tilo-sandbox-web`

## Purpose
Cloud Run service (PRD 6.2): fictional sites used by scenarios and evals, so `tilo-browser`
has safe, deterministic targets instead of the live internet.

## Commands
- `uv run pytest "services/sandbox-web/tests" -q` — acceptance tests (P8-07).
- `uv run --package tilo-sandbox-web uvicorn tilo_sandbox_web:app --port 8090` — run the service locally.
- `just check` — full gate from the repo root.
- Image: `Dockerfile` runs `tilo_sandbox_web.app:app` (P0-07a); deploy: `docs/deploy-dev.md`.

## Contracts
- Reads: this service's `seed/*.yaml` at module import, using one generic renderer for `/s/{slug}/{page}`; `/manifest.json` lists the loaded sites and planted injection entries. LW-09 routes generate fictional fetch fixtures in process from `fetch_fixtures.py`.
- Writes: none (static/generated fictional site content only).
- `GET` and `HEAD` serve seeded pages; `POST` is accepted only on seeded quote forms with `accepts_post`, returning a deterministic calculation from the seed's rate card without persisting the submitted values.

## Config
- The loader resolves `seed/` relative to `app.py`; it does not read `config/scenarios/` or eval-case files. Seed changes require a process restart to reload. The Docker image copies the service tree, including its seeds.

## Requirement IDs
- Section 6.2 `tilo-sandbox-web` row; supports EV-* eval acceptance tests and LW-09 live-fetch fixtures (`fetch_fixtures.py`).

## Local rules
- Public ingress allowed (needed for browser-worker eval runs), but serves only fictional,
  fixture-driven content — never proxies real third-party sites.
- Responses receive `X-Robots-Tag: noindex` and a self-only CSP with inline styles allowed. LW-09 includes intentionally hostile fixtures (hidden instructions, malformed/oversize files and metadata-IP redirects) for browser refusal tests; a redirect response does not fetch its target in this service.
- No scenario-specific code without a pillar requirement backing it.
