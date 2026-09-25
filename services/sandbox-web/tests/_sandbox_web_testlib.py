"""Shared helpers for the P8-07 Sandbox Web acceptance tests (PRD 6.2); pure
functions only, so they work directly in `@pytest.mark.parametrize`."""

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
_HIDDEN_RE = re.compile(  # app.py's CSS/aria-hidden technique divs
    r'<div\s+(?:class="(?:d-none|v-hidden|f-zero|w-on-w|off-pos)"|aria-hidden="true")[^>]*>.*?</div>', re.DOTALL
)
_ZERO_WIDTH_BIDI = "​‌‍﻿‮‭‬⁦⁧⁨⁩"


def load_seed(slug: str) -> dict[str, Any]:
    return yaml.safe_load((SEED_DIR / f"{slug}.yaml").read_text(encoding="utf-8"))


def all_seed_pages() -> list[tuple[str, str]]:  # (slug, page_key) for every page, every seed file
    out: list[tuple[str, str]] = []
    for f in sorted(SEED_DIR.glob("*.yaml")):
        seed = yaml.safe_load(f.read_text(encoding="utf-8"))
        out.extend((seed["slug"], page) for page in seed["pages"])
    return out


def all_scalars(value: Any) -> list[str]:  # every leaf scalar in a seed structure, stringified
    if isinstance(value, dict):
        return [s for v in value.values() for s in all_scalars(v)]
    if isinstance(value, list):
        return [s for v in value for s in all_scalars(v)]
    return [] if value is None else [str(value)]


def visible_text(doc: str) -> str:  # tags, comments, <style> content and hidden subtrees stripped
    doc = re.sub(r"<!--.*?-->|<style[^>]*>.*?</style>", " ", doc, flags=re.DOTALL)
    doc = _HIDDEN_RE.sub(" ", doc)
    return html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", doc).split()))


def technique_ok(html: str, entry: dict[str, Any]) -> bool:
    """True when `entry` is hidden from a sighted reader by the technique it claims."""
    technique, text = entry["technique"], visible_text(html)
    if technique == "link-smuggling":
        return entry["href"] in html and "collect.exfil.invalid" not in text
    payload = entry["payload"]
    if technique in ("zero-width-chars", "homoglyph-bidi"):
        stripped = "".join(c for c in payload if c not in _ZERO_WIDTH_BIDI)
        return stripped != payload and payload in html and stripped not in text
    # CSS classes, aria-hidden, html-comment, alt/title: dropped wholesale by visible_text.
    return payload in html and payload not in text
