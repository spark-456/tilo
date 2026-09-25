"""Shared, dependency-free helpers for the P8-07 Sandbox Web acceptance
tests (PRD 6.2 `tilo-sandbox-web`; SC-01, SC-06, E-RED, E-RES). Ticket spec:
the SE orchestrator's "## P8-07" section fixes `tilo_sandbox_web:app` as the
public interface and `services/sandbox-web/seed/<slug>.yaml` as the seed
shape (`slug`, `name`, `kind`, `pages`, plus kind-specific data). Everything
here is a pure function or a constant -- no fixtures -- so it can be used
directly in `@pytest.mark.parametrize` at collection time, before any
fixture would run. Module name is unique across the repo per SE rule 0.16.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"

SC01_SLUGS = ["ledgerly", "beacontrack", "fluxpoint"]
SC06_SLUGS = ["riverside-kitchens", "northgate-renovations", "maple-stone-builders"]
RED_SLUG = "redteam-notes"

# PRD 16.2/6.2: every link is relative or points to *.example / *.invalid.
ALLOWED_LINK_RE = re.compile(r"^https?://[a-z0-9.\-]+\.(example|invalid)(?:[/?#].*)?$")

_ZERO_WIDTH_BIDI = "​‌‍﻿‮‭⁦⁧⁨⁩"


def load_seed(slug: str) -> dict[str, Any]:
    return yaml.safe_load((SEED_DIR / f"{slug}.yaml").read_text(encoding="utf-8"))


def all_seed_files() -> list[Path]:
    return sorted(SEED_DIR.glob("*.yaml"))


def all_seed_pages() -> list[tuple[str, str]]:
    """(slug, page_key) for every page in every committed seed file."""
    out: list[tuple[str, str]] = []
    for f in all_seed_files():
        seed = yaml.safe_load(f.read_text(encoding="utf-8"))
        out.extend((seed["slug"], page) for page in seed["pages"])
    return out


def all_scalars(value: Any) -> list[str]:
    """Every leaf scalar in a seed data structure, stringified -- for a
    generic "the page shows the seed's own numbers" check that needs no
    scenario-specific code (PRD 6.2)."""
    out: list[str] = []
    if isinstance(value, dict):
        for v in value.values():
            out.extend(all_scalars(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(all_scalars(v))
    elif value is not None:
        out.append(str(value))
    return out


class _VisibleText(HTMLParser):
    """Strips tags, comments and script/style content -- approximates what
    a sighted reader (or a naive text-scraping agent) would actually see."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(data)


def visible_text(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return " ".join("".join(parser.chunks).split())


_CSS_MARKER = {
    "display-none": r"display:\s*none",
    "visibility-hidden": r"visibility:\s*hidden",
    "zero-font-size": r"font-size:\s*0(?:px|em|%)?\b",
    "white-on-white": r"(#?fff\w{0,3}|white)[\s\S]{0,200}(#?fff\w{0,3}|white)",
    "offscreen-position": r"(text-indent:\s*-\d|left:\s*-\d{2,}px)",
}


def technique_ok(html: str, entry: dict[str, Any]) -> bool:
    """True when `entry` (a manifest row) is hidden from a sighted reader by
    exactly the technique it claims, on the rendered page `html`."""
    technique = entry["technique"]
    text = visible_text(html)

    if technique == "link-smuggling":
        href = entry["href"]
        return href in html and "collect.exfil.invalid" not in text

    payload = entry["payload"]
    if technique in ("zero-width-chars", "homoglyph-bidi"):
        has_marker = any(c in _ZERO_WIDTH_BIDI for c in payload)
        stripped = "".join(c for c in payload if c not in _ZERO_WIDTH_BIDI)
        return has_marker and payload in html and stripped not in text

    if payload not in html or payload in text:
        return False  # not present, or not actually hidden
    if technique == "html-comment":
        return re.search(r"<!--[\s\S]*?" + re.escape(payload) + r"[\s\S]*?-->", html) is not None
    if technique == "alt-title-attr":
        return re.search(r'(alt|title)="[^"]*' + re.escape(payload), html) is not None
    if technique == "aria-hidden":
        return 'aria-hidden="true"' in html
    return re.search(_CSS_MARKER[technique], html, re.IGNORECASE) is not None
