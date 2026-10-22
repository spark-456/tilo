# tilo-sandbox-web

Fictional websites that scenarios, evals and the browser tests use as safe targets, so tests never touch the real web.
It serves deterministic pages from YAML seeds, plus fixtures for the fetch tool: a robots file, a PDF with the wrong
magic bytes, an oversize file, an archive and redirect loops. It stores nothing and never proxies a real site.

## Run

```sh
uv run --package tilo-sandbox-web uvicorn tilo_sandbox_web:app --port 8090
```

Deployed, the image runs `uvicorn tilo_sandbox_web.app:app` on `$PORT` (8080). Terraform gives it public ingress and no
authentication, because it holds nothing but fictional pages. Every response carries `X-Robots-Tag: noindex` and a
self-only Content-Security-Policy.

## Routes

| Route | What it returns |
| --- | --- |
| `GET /health`, `GET /healthz` | liveness |
| `GET /manifest.json` | the sites and the prompt injections planted in them |
| `GET`, `HEAD`, `POST /s/{slug}/{page}` | a seed page; `POST` is accepted only on a seed's `quote` page that sets `accepts_post`, and returns a quote computed from the rate card |
| `GET /robots.txt`, `/private/secret-paper.pdf`, `/papers/*` | fetch-tool fixtures: wrong magic bytes, oversize file, archive, SSRF redirects, redirect loop, a study guide |

## Seeds

`src/tilo_sandbox_web/seed/*.yaml`: three pricing sites (`beacontrack`, `fluxpoint`, `ledgerly`), three contractor
sites (`maple-stone-builders`, `northgate-renovations`, `riverside-kitchens`) and `redteam-notes`, which hides
instructions in 11 different ways for the red-team evals. Seeds are read at import time, so a change needs a restart.

## Tests

```sh
uv run pytest services/sandbox-web/tests -q
```

See [CLAUDE.md](CLAUDE.md) for the requirement IDs this service owns and its local rules.
