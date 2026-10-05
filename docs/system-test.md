# System test: does the whole stack work end to end?

Two halves. Neither makes a paid call, signs anyone in or sends anything real (EFF-01).

## 1. Local (`just system-test`, about 3 minutes)

`tests/system/` starts the real processes the way the Dockerfiles do (`uvicorn <module>:app`) and talks to them over HTTP.

| File | What it proves |
| --- | --- |
| `test_SYS_prototype_flow_over_http.py` | ADR-0008's flow through `tilo-api` in dev mode (fake Director and unit runner, a recording connector): request, clarifying questions, approaches and budget, run, approval card, **approve** (one outbound send through the outbox, delivery, contiguous `seq`), **hold** (nothing sent, run waits, a later approve completes), pause all, layout, intake refusals, budget limits, no 5xx for unknown ids or bad bodies, the dev Host and CORS limits, and that every route the API serves is driven by this suite (a new route fails it). |
| `test_SYS_fail_closed_and_services.py` | each of the six other services starts and answers `/health` and `/healthz`; a route that is not public by design refuses an anonymous call; `tilo-api` without dev mode serves nothing that needs a person (one `xfail`: it answers 500, not 401, issue linked in the test). |
| `apps/web/e2e/cp2/` (`just e2e-cp2`) | the web app against the same API, no fixtures: task to delivery (`cp2-live-run`), card on two surfaces, bare routes, and **hold then approve** (`cp2-hold-then-approve`). Starts its own API on 8080 and Vite on `TILO_CP2_PORT`. |

`just test` and `just check` skip the `system` mark (they need port 8080 and take minutes); run `just system-test` before a deploy.

What the local run showed on 6 Oct 2026: the five services other than `tilo-api` and `sandbox-web` serve only `/health`, `/healthz`, `/docs` and `/openapi.json` today. The harness runs inside `tilo-api` (its writer and validator are libraries), so there is no separate harness HTTP surface to drive yet.

## 2. Deployed `tilo-dev` (read-only, no sign-in)

Region `asia-southeast1`. Commands used, all reads: `gcloud run services list` and `get-iam-policy`, then anonymous `curl`. `/healthz` is reserved by Cloud Run on `run.app` (Google answers 404), so liveness is checked through `/openapi.json` or a refusal.

| Service | Ready | Ingress | Anonymous invoker | Anonymous probes (6 Oct) |
| --- | --- | --- | --- | --- |
| tilo-api | True | all | allUsers | `/openapi.json` 200, `/docs` 200, any API route **500** |
| tilo-channels | True | all | allUsers (webhook) | `/openapi.json` 200, `/docs` 200, other routes 404 |
| tilo-sandbox-web | True | all | allUsers (practice site) | `/manifest.json` 200, `/openapi.json` 404 |
| tilo-harness, tilo-connectors, tilo-browser, tilo-render | True | internal | harness / connectors / browser callers only | 404 from Google for every outside path (fail-closed) |

`/health` is 404 on every deployed service: the image predates #404.

Web app: https://essential-wares-510320-f0.web.app answers 200.

Findings: #410 (anonymous calls to `tilo-api` answer 500, not 401/503) and #411 (`tilo-api` and `tilo-channels` publish `/openapi.json` and `/docs`).
