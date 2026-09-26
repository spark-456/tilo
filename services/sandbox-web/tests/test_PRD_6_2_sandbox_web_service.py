"""Generic Sandbox Web service behaviour (PRD 6.2, 6.3, 12.3, 16.2/16.3): one test per page, not per scenario."""

from __future__ import annotations

import re

import pytest
from _sandbox_web_testlib import ALLOWED_LINK_RE, all_seed_pages

PAGES = all_seed_pages()


def test_PRD_6_2_healthz_ok(client):
    assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize("slug,page", PAGES, ids=[f"{s}/{p}" for s, p in PAGES])
def test_PRD_6_2_every_page_is_ok_deterministic_and_safe(client, slug, page):
    first = client.get(f"/s/{slug}/{page}")
    second = client.get(f"/s/{slug}/{page}")
    head = client.head(f"/s/{slug}/{page}")
    assert first.status_code == 200 and head.status_code == 200 and head.content == b""
    assert first.content == second.content, "rendering must be byte-for-byte deterministic"
    if page != "quote":
        assert client.post(f"/s/{slug}/{page}").status_code == 405

    assert first.headers.get("x-robots-tag") == "noindex"
    csp = first.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp and "http://" not in csp and "https://" not in csp
    for url in re.findall(r'(?:href|src)="([^"]+)"', first.text):
        if "://" in url:
            assert ALLOWED_LINK_RE.match(url), f"{slug}/{page} links outside .example/.invalid: {url}"


@pytest.mark.parametrize(
    "path",
    "/s/ledgerly/../../etc/passwd /s/does-not-exist/pricing /s/ledgerly/does-not-exist "
    "/s/%2e%2e/pricing /s/ledgerly%2f..%2f..%2fetc%2fpasswd".split(),
)
def test_PRD_6_2_path_traversal_and_unknown_slugs_return_404(client, path):
    resp = client.get(path)
    assert resp.status_code == 404
