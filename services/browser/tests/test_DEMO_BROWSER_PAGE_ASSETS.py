"""DEMO-BROWSER, owner decision 21 Oct ("Yes, let page images, styles, fonts and media load from any public host in
Tilo's browser"; BR-02 amendment, docs/open-questions.md BQ-BROWSER-ASSETS): a page's images, stylesheets, fonts and
media may load from any public host, so a page looks as it does to a person (Wikipedia's pictures come from
upload.wikimedia.org). Everything else stays on the allowlist: page navigations, clicks, searches, scripts, XHR,
frames. A public host is an https DNS name, not an internal one, whose addresses are all public (SSRF: no private,
loopback, link-local or metadata address); a query that carries a secret is still refused.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from tilo_browser.egress import EgressPolicy

ADDRESSES = {
    "upload.wikimedia.org": ["198.35.26.112"],
    "fonts.example.net": ["2606:4700::6810:84e5"],
    "intranet.example.com": ["10.1.2.3"],
    "rebound.example.com": ["93.184.216.34", "169.254.169.254"],
}


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    looked: list[str] = []

    def resolve(host, port):
        looked.append(host)
        if host not in ADDRESSES:
            raise OSError("no such host")
        return ADDRESSES[host]

    monkeypatch.setattr("tilo_browser.fetch.default_dns_resolver", resolve)
    return looked


def _policy():
    return EgressPolicy(["*.wikipedia.org", "wikipedia.org"])


def test_DEMO_BROWSER_an_asset_from_a_public_host_loads(dns):
    policy = _policy()
    decision = policy.check_asset("https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Tokyo.jpg")
    assert decision.allowed and decision.reason == "public_asset"
    assert policy.check_asset("https://fonts.example.net/inter.woff2").allowed
    assert policy.blocked == []
    policy.check_asset("https://upload.wikimedia.org/other.png")
    assert dns.count("upload.wikimedia.org") == 1, "a host is looked up once a session"


def test_DEMO_BROWSER_the_named_site_still_passes_as_before():
    decision = _policy().check_asset("https://en.wikipedia.org/static/images/logo.svg")
    assert decision.allowed and decision.reason == "allowed"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("https://intranet.example.com/logo.png", "host_not_allowlisted"),  # a private address
        ("https://rebound.example.com/pixel.gif", "host_not_allowlisted"),  # one metadata address is enough
        ("https://nowhere.example.org/a.png", "host_not_allowlisted"),  # does not resolve
        ("https://localhost/a.png", "host_not_allowlisted"),  # internal by name, never looked up
        ("https://metadata.google.internal/computeMetadata/v1/", "host_not_allowlisted"),
        ("https://10.0.0.7/a.png", "ip_literal"),
        ("http://upload.wikimedia.org/a.png", "scheme_not_allowed"),
    ],
)
def test_DEMO_BROWSER_an_asset_from_anywhere_else_is_blocked_and_counted(dns, url, reason):
    policy = _policy()
    decision = policy.check_asset(url)
    assert not decision.allowed and decision.reason == reason
    assert policy.blocked == [decision]
    assert "localhost" not in dns and "metadata.google.internal" not in dns


def test_DEMO_BROWSER_an_asset_query_never_carries_a_secret():
    secret = "AK" + "IA" + "ABCDEFGHIJKLMNOP"  # assembled at runtime: a fake key shape the masker catches
    decision = _policy().check_asset(f"https://upload.wikimedia.org/a.png?k={secret}")
    assert not decision.allowed and decision.reason == "sensitive_query"


def test_DEMO_BROWSER_a_navigation_to_a_public_host_stays_blocked():
    policy = _policy()
    assert not policy.check("https://upload.wikimedia.org/wikipedia/commons/a.jpg").allowed
    assert policy.blocked[-1].reason == "host_not_allowlisted"


def test_DEMO_BROWSER_the_worker_gates_only_a_first_asset_request_as_an_asset():
    from _browser_lib import FakeEngine, FakeWeb
    from tilo_browser.worker import BrowserWorker

    worker = BrowserWorker(FakeEngine(FakeWeb()), _policy())
    assert worker._gate("https://upload.wikimedia.org/a.png", asset=True)
    assert not worker._gate("https://upload.wikimedia.org/a.png")  # a navigation or any other request
    hop = worker._gate("https://upload.wikimedia.org/a.png", redirect_from="https://en.wikipedia.org/x", asset=True)
    assert not hop, "a redirect hop is checked against the allowlist"


# --- the real driver (headless Chromium): which requests it hands to the gate as assets ---


class _Pages(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        bodies = {
            "/": (
                "text/html",
                "<link rel='stylesheet' href='/s.css'><img src='/a.png'><script src='/x.js'></script><p>Page</p>",
            ),
            "/s.css": ("text/css", "p{color:red}"),
            "/x.js": ("text/javascript", "1;"),
        }
        kind, body = bodies.get(self.path, ("image/png", ""))
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.mark.slow
def test_DEMO_BROWSER_the_driver_asks_for_images_and_styles_as_assets_and_the_rest_as_requests(server):
    from tilo_browser.playwright_engine import PlaywrightDriver

    asked: list[tuple[str, bool]] = []

    def gate(url, redirect_from=None, asset=False):
        asked.append((url.removeprefix(server), asset))
        return True

    try:
        driver = PlaywrightDriver(gate, {"width": 800, "height": 600})
    except Exception as exc:  # no Chromium in this environment
        pytest.skip(f"headless Chromium is not available: {type(exc).__name__}")
    try:
        driver.goto(f"{server}/")
        driver.page.wait_for_load_state("load")
    finally:
        driver.close()
    seen = dict(asked)
    assert seen["/"] is False, "the page itself is a navigation"
    assert seen["/s.css"] is True and seen["/a.png"] is True
    assert seen["/x.js"] is False, "a script stays on the allowlist"
