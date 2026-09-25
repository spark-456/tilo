"""Pure helpers for the P8-07 Sandbox Web acceptance tests (PRD 6.2), usable in `parametrize`."""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path
from typing import Any

import yaml

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"
SC01_SLUGS = ["ledgerly", "beacontrack", "fluxpoint"]
SC06_SLUGS = ["riverside-kitchens", "northgate-renovations", "maple-stone-builders"]
RED_SLUG = "redteam-notes"

ALLOWED_LINK_RE = re.compile(r"^https?://[a-z0-9.\-]+\.(example|invalid)(?:[/?#].*)?$")  # PRD 16.2/6.2
_ZERO_WIDTH_BIDI = "​‌‍﻿‮‭‬⁦⁧⁨⁩"


def load_seed(slug: str) -> dict[str, Any]:
    return yaml.safe_load((SEED_DIR / f"{slug}.yaml").read_text(encoding="utf-8"))


def all_seed_pages() -> list[tuple[str, str]]:  # (slug, page_key) for every page, every seed file
    seeds = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted(SEED_DIR.glob("*.yaml"))]
    return [(s["slug"], page) for s in seeds for page in s["pages"]]


def all_scalars(value: Any) -> list[str]:  # every leaf scalar in a seed structure, stringified
    if isinstance(value, dict):
        return [s for v in value.values() for s in all_scalars(v)]
    if isinstance(value, list):
        return [s for v in value for s in all_scalars(v)]
    return [] if value is None else [str(value)]


def visible_text(doc: str) -> str:  # tags, comments and <style> content stripped
    doc = re.sub(r"<!--.*?-->|<style[^>]*>.*?</style>", " ", doc, flags=re.DOTALL)
    return html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", doc).split()))


_DECL = {  # CSS technique -> declarations the carrier's class rule must hold
    "display-none": [r"display:\s*none"],
    "visibility-hidden": [r"visibility:\s*hidden"],
    "zero-font-size": [r"font-size:\s*0(?![.\d])"],
    "white-on-white": [r"(?<![-\w])color:\s*#fff\b", r"background(?:-color)?:\s*#fff\b"],
    "offscreen-position": [r"left:\s*-\d"],
}


def technique_ok(html: str, entry: dict[str, Any]) -> bool:
    """True when `entry`'s payload is carried by exactly the technique it claims and seen nowhere else."""
    technique = entry["technique"]
    if technique == "link-smuggling":
        return entry["href"] in html and "collect.exfil.invalid" not in visible_text(html)
    payload = entry["payload"]
    if technique in ("zero-width-chars", "homoglyph-bidi"):
        stripped = "".join(c for c in payload if c not in _ZERO_WIDTH_BIDI)
        return stripped != payload and payload in html and stripped not in visible_text(html)
    esc = re.escape(html_lib.escape(payload))
    carrier = {
        "html-comment": rf"<!--(?:(?!-->)[\s\S])*{esc}[\s\S]*?-->",
        "alt-title-attr": rf'<img\b[^>]*\b(?:alt|title)="{esc}"[^>]*>',
        "aria-hidden": rf'<(\w+)\s[^>]*\baria-hidden="true"[^>]*>{esc}</\1>',
    }.get(technique, rf'<(\w+)\s[^>]*\bclass="([^"]*)"[^>]*>{esc}</\1>')
    m = re.search(carrier, html)
    if m is None or payload in visible_text(html.replace(m.group(0), " ")):
        return False
    if technique not in _DECL:
        return True
    styles = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.DOTALL))
    rules = [r for c in m.group(2).split() for r in re.findall(rf"\.{re.escape(c)}\s*\{{([^}}]*)\}}", styles)]
    return any(all(re.search(d, r) for d in _DECL[technique]) for r in rules)
