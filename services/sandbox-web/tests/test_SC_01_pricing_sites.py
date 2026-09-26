"""SC-01 competitor pricing sites (PRD 4.3 SC-01, 6.2): rendered numbers checked against the seed itself."""

from __future__ import annotations

import re

import pytest
from _sandbox_web_testlib import SC01_SLUGS, all_scalars, load_seed, visible_text

PAGE_KEYS = ["pricing", "product", "changelog", "old-pricing"]


@pytest.mark.parametrize("slug", SC01_SLUGS)
@pytest.mark.parametrize("page_key", PAGE_KEYS)
def test_SC_01_page_shows_the_seeds_own_numbers(client, slug, page_key):
    seed = load_seed(slug)
    resp = client.get(f"/s/{slug}/{page_key}")
    assert resp.status_code == 200
    text = visible_text(resp.text)
    for scalar in all_scalars(seed["pages"][page_key]):
        assert scalar in text, f"{slug}/{page_key} is missing seed value {scalar!r}"
    if slug == "ledgerly" and page_key == "pricing":
        assert re.search(r"monthly[^0-9]{0,20}19", resp.text), "seed values need their key as a label"


@pytest.mark.parametrize("slug", SC01_SLUGS)
def test_SC_01_archived_pricing_differs_and_changelog_explains_the_change(client, slug):
    seed = load_seed(slug)
    current = {p["name"]: p["monthly"] for p in seed["pages"]["pricing"]["plans"]}
    old = {p["name"]: p["monthly"] for p in seed["pages"]["old-pricing"]["plans"]}
    assert current != old, f"{slug}: the archive page must show a real historical price change"
    changed = {name for name in current if current[name] != old.get(name)}
    changelog_text = " ".join(e["note"] for e in seed["pages"]["changelog"]["entries"])
    assert any(str(current[name]) in changelog_text for name in changed)
