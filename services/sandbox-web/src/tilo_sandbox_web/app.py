"""Tilo Sandbox Web (PRD 6.2 `tilo-sandbox-web`; SC-01, SC-06, E-RED, E-RES).

Generic, deterministic FastAPI app that renders every site from
`services/sandbox-web/seed/<slug>.yaml`. No scenario-specific code: one
page renderer walks any seed's `pages` dict, and one technique renderer
plants a hidden payload per `kind: red`'s `manifest` entries. The service
never fetches or proxies anything; every non-relative link stays on
`*.example` / `*.invalid`.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
CSP = "default-src 'self'"

_CSS_TECHNIQUES = {
    "display-none": 'style="display:none"',
    "visibility-hidden": 'style="visibility:hidden"',
    "zero-font-size": 'style="font-size:0"',
    "white-on-white": 'style="color:#fff;background:#fff"',
    "offscreen-position": 'style="position:absolute;left:-9999px"',
    "aria-hidden": 'aria-hidden="true"',
}


def _load_seeds() -> dict[str, dict[str, Any]]:
    seeds: dict[str, dict[str, Any]] = {}
    for path in sorted(SEED_DIR.glob("*.yaml")):
        seed = yaml.safe_load(path.read_text(encoding="utf-8"))
        seeds[seed["slug"]] = seed
    return seeds


SEEDS = _load_seeds()


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _render_value(value: Any) -> str:
    if isinstance(value, dict):
        return "".join(f'<div class="field">{_render_value(v)}</div>' for v in value.values())
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_render_value(v)}</li>" for v in value) + "</ul>"
    return _esc(value)


def _render_technique(entry: dict[str, Any]) -> str:
    """A benign fictional payload, hidden the way `entry['technique']` claims:
    never as ordinary element text (a naive text scraper would still see
    that), always as an attribute value or a comment instead."""
    technique = entry["technique"]
    payload = _esc(entry["payload"])
    if technique in _CSS_TECHNIQUES:
        return f'<div {_CSS_TECHNIQUES[technique]} data-hidden="{payload}"></div>'
    if technique == "html-comment":
        return f"<!-- {payload} -->"
    if technique == "alt-title-attr":
        return f'<img src="" alt="{payload}" title="{payload}">'
    if technique in ("zero-width-chars", "homoglyph-bidi"):
        return f"<div>{payload}</div>"
    if technique == "link-smuggling":
        return f'<a href="{_esc(entry["href"])}">{payload}</a>'
    raise ValueError(f"unknown E-RED technique: {technique}")  # pragma: no cover


def render_page(seed: dict[str, Any], page_key: str) -> str:
    data = seed["pages"][page_key]
    title = data.get("title", page_key) if isinstance(data, dict) else str(page_key)
    extra = "".join(_render_technique(entry) for entry in seed.get("manifest", []) if entry["page"] == page_key)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{_esc(title)}</title></head>"
        f"<body><h1>{_esc(title)}</h1>{_render_value(data)}{extra}</body></html>"
    )


def _seed_or_404(slug: str) -> dict[str, Any]:
    seed = SEEDS.get(slug)
    if seed is None:
        raise HTTPException(404, "unknown site")
    return seed


def _validate_quote_inputs(fields: list[str], body: Any) -> dict[str, float]:
    if not isinstance(body, dict):
        raise HTTPException(422, "body must be a JSON object")
    out: dict[str, float] = {}
    for field in fields:
        if field not in body:
            raise HTTPException(422, f"missing field: {field}")
        value = body[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(422, f"{field} must be a number")
        if value < 0:
            raise HTTPException(422, f"{field} must not be negative")
        out[field] = value
    return out


def _rate_for(rate_card: dict[str, Any], field: str) -> float:
    """Generic singular/plural lookup: an input field "cabinets" prices off
    a rate_card key "per_cabinets" or, failing that, "per_cabinet"."""
    for key in (f"per_{field}", f"per_{field[:-1]}" if field.endswith("s") else None):
        if key and key in rate_card:
            return rate_card[key]
    raise HTTPException(500, f"seed has no rate for field: {field}")  # pragma: no cover


def _quote(seed: dict[str, Any], body: Any) -> JSONResponse:
    quote_page = seed["pages"]["quote"]
    inputs = _validate_quote_inputs(quote_page["inputs"], body)
    rate_card = seed["rate_card"]
    total = rate_card["base_fee"] + sum(_rate_for(rate_card, k) * v for k, v in inputs.items())
    return JSONResponse({"quote": total})


app = FastAPI(title="Tilo Sandbox Web", docs_url=None, redoc_url=None)


@app.middleware("http")
async def _security_headers(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Content-Security-Policy"] = CSP
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/manifest.json")
def manifest() -> dict[str, Any]:
    sites = [{"slug": s["slug"], "name": s["name"], "kind": s["kind"]} for s in SEEDS.values()]
    injections = [entry for seed in SEEDS.values() for entry in seed.get("manifest", [])]
    return {"sites": sites, "injections": injections}


@app.api_route("/s/{slug}/{page}", methods=["GET", "HEAD", "POST"])
async def site_page(request: Request, slug: str, page: str) -> Response:
    seed = _seed_or_404(slug)
    if page not in seed["pages"]:
        raise HTTPException(404, "unknown page")

    if request.method == "POST":
        if page != "quote" or not seed["pages"]["quote"].get("accepts_post"):
            raise HTTPException(405, "POST is only accepted on the quote form")
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001 — any malformed body is a 422, not a 500
            raise HTTPException(422, "body must be JSON") from exc
        return _quote(seed, body)

    html_doc = render_page(seed, page)
    if request.method == "HEAD":
        return Response(status_code=200, media_type="text/html")
    return HTMLResponse(html_doc)
