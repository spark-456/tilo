# tilo-render

Turns a structured deliverable spec into a file. It calls no model and no network, so the same spec gives the same
file. Charts are drawn by code from the spec's data, never by a model.

## Formats

| Format | Library or method | Where it runs |
| --- | --- | --- |
| PDF | reportlab; a cover and report layout, or a `one_page` layout | in-process and over HTTP |
| PPTX | native bar, line and pie charts; `two_column`, `image` and `stat` blocks | in-process and over HTTP |
| DOCX | hand-built OOXML with Word styles | in-process and over HTTP |
| XLSX | formulas with cached values, native charts, fill of an uploaded template | in-process only |
| CSV | the spec's first table | in-process only |

A `figure` block places recorded PNG or JPEG images, and a provenance appendix lists the manifest. Websites are not
rendered here: a website is written by the run's writer unit and stored as an artifact (ADR-0050). Native Google Slides,
Docs and Sheets come from `tilo-connectors`, which converts a PPTX, DOCX or XLSX made here; this service never calls it.

Templates: `templates/report/default.yaml`, `templates/deck/default.yaml` and `design/tokens.json` (copied into the image).

## Run and call

The image runs `uvicorn tilo_render.app:app` on `$PORT`. `GET /health` and `/healthz` are public. `POST /render` takes
JSON with `format` (`pdf`, `pptx` or `docx`) and a `spec` of up to 1 MiB, within a 15 s timeout, two renders at once
(more get 429 `busy`) and a 20 MiB output cap.

`POST /render` needs a Google ID token, and it **fails closed**: the shipped module-level `app = create_app()` installs
no verifier, so over HTTP it refuses every render with 403 until a verifier is injected and `TILO_RENDER_AUDIENCE` and
`TILO_RENDER_ALLOWED_CALLERS` are set (nothing in the repo sets them). `tilo-api` calls it through `RenderRpc` only when
`TILO_RENDER_URL` is set; otherwise `report_render.py` renders in its own process, which is the path in use today.
Ingress is internal-only in Terraform, which names `tilo-harness` as invoker although the code's real caller is `tilo-api`.

## Key modules

`spec.py` (`DeliverableSpec`), `pdf.py`, `pptx.py`, `docx.py`, `docx_styles.py`, `xlsx.py`, `csv_table.py`,
`charts.py`, `formula.py`, `text.py`, `app.py`. No Firestore, bucket or secret is used.

## Tests

```sh
uv run pytest services/render -q
```

See [CLAUDE.md](CLAUDE.md) for the requirement IDs and local rules.
