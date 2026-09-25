"""Tilo Sandbox Web (PRD 6.2): generic FastAPI app rendering every seed/<slug>.yaml site."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

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

SEEDS: dict[str, dict[str, Any]] = {}
for _path in sorted(SEED_DIR.glob("*.yaml")):
    _seed = yaml.safe_load(_path.read_text(encoding="utf-8"))
    SEEDS[_seed["slug"]] = _seed


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _render_value(value: Any) -> str:
    """Seed data rendered generically; dict keys stay attached as labels."""
    if isinstance(value, dict):
        return "".join(f"<div>{_esc(k)}: {_render_value(v)}</div>" for k, v in value.items())
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_render_value(v)}</li>" for v in value) + "</ul>"
    return _esc(value)


def _render_technique(entry: dict[str, Any]) -> str:
    """Payload as text inside the element carrying the hiding style/attribute."""
    technique, payload = entry["technique"], _esc(entry["payload"])
    css = _CSS_TECHNIQUES.get(technique)
    if css:
        return f'<div class="{css[0]}">{payload}</div>'
    if technique == "aria-hidden":
        return f'<div aria-hidden="true">{payload}</div>'
    if technique == "html-comment":
        return f"<!-- {payload} -->"
    if technique == "alt-title-attr":
        return f'<img src="" alt="{payload}" title="{payload}">'
    if technique in ("zero-width-chars", "homoglyph-bidi"):
        return f"<div>{payload}</div>"
    return f'<a href="{_esc(entry["href"])}">{payload}</a>'


def render_page(seed: dict[str, Any], page_key: str) -> str:
    data = seed["pages"][page_key]
    title = data.get("title", page_key) if isinstance(data, dict) else str(page_key)
    is_form = isinstance(data, dict) and data.get("accepts_post")
    shown = {k: v for k, v in data.items() if k not in ("accepts_post", "inputs")} if is_form else data
    body = _render_value(shown)
    if is_form:
        fields = "".join(f'<input name="{_esc(f)}" type="number">' for f in data["inputs"])
        action = f"/s/{seed['slug']}/{page_key}"
        body += f'<form method="post" action="{action}">{fields}<button type="submit">Get quote</button></form>'
    extra = "".join(_render_technique(e) for e in seed.get("manifest", []) if e["page"] == page_key)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{HIDDEN_CSS}</style><title>{_esc(title)}</title></head>"
        f"<body><h1>{_esc(title)}</h1>{body}{extra}</body></html>"
    )


app = FastAPI(title="Tilo Sandbox Web", docs_url=None, redoc_url=None, openapi_url=None)


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
    seed = SEEDS.get(slug)
    if seed is None or page not in seed["pages"]:
        raise HTTPException(404, "unknown site or page")

    if request.method == "POST":
        if page != "quote" or not seed["pages"]["quote"].get("accepts_post"):
            raise HTTPException(405, "POST is only accepted on the quote form")
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001 — any malformed body is a 422, not a 500
            raise HTTPException(422, "body must be JSON") from exc
        if not isinstance(body, dict):
            raise HTTPException(422, "body must be a JSON object")
        rate_card = seed["rate_card"]
        total = rate_card["base_fee"]
        for field in seed["pages"]["quote"]["inputs"]:
            value = body.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise HTTPException(422, f"{field} must be a finite number")
            if not 0 <= value <= MAX_QUOTE_INPUT:
                raise HTTPException(422, f"{field} out of range")
            per_key = f"per_{field}" if f"per_{field}" in rate_card else f"per_{field[:-1]}"  # singular/plural
            total += rate_card[per_key] * value
        if not math.isfinite(total):
            raise HTTPException(422, "computed total is not finite")
        return JSONResponse({"quote": total})

    html_doc = render_page(seed, page)
    if request.method == "HEAD":
        return Response(status_code=200, media_type="text/html")
    return HTMLResponse(html_doc)
