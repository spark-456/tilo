"""Generic Sandbox Web service behaviour (PRD 6.2 `tilo-sandbox-web`, 6.3
ingress, 12.3 browser-worker safety, 16.2/16.3 egress hygiene). These hold
for every seeded site regardless of scenario, per 6.2's "generic code, seed
data only" rule -- one parametrized test per page, not per scenario.
"""

from __future__ import annotations

import re

import pytest
from _sandbox_web_testlib import ALLOWED_LINK_RE, all_seed_pages

PAGES = all_seed_pages()


def test_PRD_6_2_healthz_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200


@pytest.mark.parametrize("slug,page", PAGES, ids=[f"{s}/{p}" for s, p in PAGES])
def test_PRD_6_2_every_seeded_page_returns_200(client, slug, page):
    resp = client.get(f"/s/{slug}/{page}")
    assert resp.status_code == 200


@pytest.mark.parametrize("slug,page", PAGES, ids=[f"{s}/{p}" for s, p in PAGES])
def test_PRD_6_2_security_headers_are_set(client, slug, page):
    resp = client.get(f"/s/{slug}/{page}")
    assert resp.headers.get("x-robots-tag") == "noindex"
    csp = resp.headers.get("content-security-policy", "")
    assert csp, "every response needs a Content-Security-Policy header"
    assert "default-src 'self'" in csp  # PRD default: "strict ... no external sources"
    assert "http://" not in csp and "https://" not in csp


def test_PRD_6_2_head_is_supported(client):
    slug, page = PAGES[0]
    resp = client.head(f"/s/{slug}/{page}")
    assert resp.status_code == 200
    assert resp.content == b""


@pytest.mark.parametrize("slug,page", PAGES, ids=[f"{s}/{p}" for s, p in PAGES])
def test_PRD_6_2_post_refused_outside_the_quote_form(client, slug, page):
    if page == "quote":
        pytest.skip("the one page that accepts POST (SC-06 quote form)")
    resp = client.post(f"/s/{slug}/{page}")
    assert resp.status_code == 405


@pytest.mark.parametrize(
    "path",
    [
        "/s/ledgerly/../../etc/passwd",
        "/s/does-not-exist/pricing",
        "/s/ledgerly/does-not-exist",
        "/s/%2e%2e/pricing",
        "/s/ledgerly%2f..%2f..%2fetc%2fpasswd",
    ],
)
def test_PRD_6_2_path_traversal_and_unknown_slugs_return_404(client, path):
    resp = client.get(path)
    assert resp.status_code == 404


@pytest.mark.parametrize("slug,page", PAGES, ids=[f"{s}/{p}" for s, p in PAGES])
def test_PRD_6_2_rendering_is_byte_for_byte_deterministic(client, slug, page):
    first = client.get(f"/s/{slug}/{page}")
    second = client.get(f"/s/{slug}/{page}")
    assert first.content == second.content


@pytest.mark.parametrize("slug,page", PAGES, ids=[f"{s}/{p}" for s, p in PAGES])
def test_PRD_16_2_no_link_points_outside_example_or_invalid(client, slug, page):
    html = client.get(f"/s/{slug}/{page}").text
    for url in re.findall(r'(?:href|src)="([^"]+)"', html):
        if "://" not in url:
            continue  # relative link: always fine, never proxied (PRD 6.2)
        assert ALLOWED_LINK_RE.match(url), f"{slug}/{page} links outside .example/.invalid: {url}"


def test_PRD_6_2_manifest_lists_every_site_and_every_red_injection(client):
    manifest = client.get("/manifest.json").json()
    slugs = {s["slug"] for s in manifest["sites"]}
    assert {"ledgerly", "riverside-kitchens", "redteam-notes"} <= slugs
    ids = {inj["id"] for inj in manifest["injections"]}
    assert ids == {f"RED-{i:02d}" for i in range(1, 12)}
    for inj in manifest["injections"]:
        assert inj["expected"] == "flagged_or_blocked"
        for bait in inj["bait"]:
            assert bait.rsplit("@", 1)[-1].endswith(".invalid")
