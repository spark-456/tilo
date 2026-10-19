"""Tilo Sandbox Web (PRD 6.2): generic FastAPI app rendering every seed/<slug>.yaml site."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from tilo_sandbox_web.fetch_fixtures import router as fetch_fixtures_router

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'"  # inline <style> only; no external source
MAX_QUOTE_INPUT = 1_000_000

_CSS_TECHNIQUES = {  # technique -> (css class, rule); doubles as the page's <style> block
    "display-none": ("d-none", "display:none"),
    "visibility-hidden": ("v-hidden", "visibility:hidden"),
    "zero-font-size": ("f-zero", "font-size:0"),
    "white-on-white": ("w-on-w", "color:#fff;background:#fff"),
    "offscreen-position": ("off-pos", "position:absolute;left:-9999px"),
}
HIDDEN_CSS = "".join(f".{cls}{{{rule}}}" for cls, rule in _CSS_TECHNIQUES.values())
_TEMPLATES = {  # technique -> element whose text is the payload {p}; link-smuggling puts it on {h}
    **{t: f'<div class="{cls}">{{p}}</div>' for t, (cls, _) in _CSS_TECHNIQUES.items()},
    "aria-hidden": '<div aria-hidden="true">{p}</div>',
    "html-comment": "<!-- {p} -->",
    "alt-title-attr": '<img src="" alt="{p}" title="{p}">',
    **dict.fromkeys(("zero-width-chars", "homoglyph-bidi"), "<div>{p}</div>"),
    "link-smuggling": '<a href="{h}">{p}</a>',
}

_LOADED = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(SEED_DIR.glob("*.yaml"))]
SEEDS: dict[str, dict[str, Any]] = {s["slug"]: s for s in _LOADED}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _render_value(value: Any) -> str:
    """Seed data rendered generically; dict keys stay attached as labels."""
    if isinstance(value, dict):
        return "".join(f"<div>{_esc(k)}: {_render_value(v)}</div>" for k, v in value.items())
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_render_value(v)}</li>" for v in value) + "</ul>"
    return _esc(value)


def render_page(seed: dict[str, Any], page_key: str) -> str:
    data = seed["pages"][page_key]
    title = data.get("title", page_key) if isinstance(data, dict) else str(page_key)
    is_form = isinstance(data, dict) and data.get("accepts_post")
    shown = {k: v for k, v in data.items() if k not in ("accepts_post", "inputs")} if is_form else data
    body = _render_value(shown)
    if is_form:
        fields = "".join(f'<input name="{_esc(f)}" type="number">' for f in data["inputs"])
        body += f'<form method="post" action="/s/{seed["slug"]}/{page_key}">{fields}<button>Get quote</button></form>'
    rows = [e for e in seed.get("manifest", []) if e["page"] == page_key]
    extra = "".join(_TEMPLATES[e["technique"]].format(p=_esc(e["payload"]), h=_esc(e.get("href", ""))) for e in rows)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{HIDDEN_CSS}</style><title>{_esc(title)}</title></head>"
        f"<body><h1>{_esc(title)}</h1>{body}{extra}</body></html>"
    )


app = FastAPI(title="Tilo Sandbox Web", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(fetch_fixtures_router)


@app.middleware("http")
async def _security_headers(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Content-Security-Policy"] = CSP
    return response


@app.get("/health")  # Cloud Run reserves /healthz on run.app; the smoke check uses /health (#397)
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
    seed = SEEDS.get(slug)
    if seed is None or page not in seed["pages"]:
        raise HTTPException(404, "unknown site or page")

    if request.method == "POST":
        if page != "quote" or not seed["pages"]["quote"].get("accepts_post"):
            raise HTTPException(405, "POST is only accepted on the quote form")
        raw = await request.body()
        try:  # JSON, or the rendered form's urlencoded fields
            if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                body: Any = {k: float(v) for k, v in parse_qsl(raw.decode())}
            else:
                body = json.loads(raw)
        except (ValueError, RecursionError) as exc:  # malformed JSON, bad UTF-8, non-numeric form field
            raise HTTPException(422, "body must be JSON or numeric form fields") from exc
        if not isinstance(body, dict):
            raise HTTPException(422, "body must be a JSON object")
        rate_card, total = seed["rate_card"], seed["rate_card"]["base_fee"]
        for field in seed["pages"]["quote"]["inputs"]:
            value = body.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_QUOTE_INPUT:
                raise HTTPException(422, f"{field} must be a number from 0 to {MAX_QUOTE_INPUT}")  # also NaN/inf
            per_key = f"per_{field}" if f"per_{field}" in rate_card else f"per_{field[:-1]}"  # singular/plural
            total += rate_card[per_key] * value
        return JSONResponse({"quote": total})

    html_doc = render_page(seed, page)  # rendered for HEAD too, so a bad page fails the same way
    return Response(media_type="text/html") if request.method == "HEAD" else HTMLResponse(html_doc)
