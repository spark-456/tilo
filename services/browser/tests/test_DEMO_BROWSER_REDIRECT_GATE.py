"""DEMO-BROWSER (BR-02, SEC-09): every redirect hop of a page navigation passes the egress gate.

Playwright calls a route handler only for the first URL of a redirect chain, so a hop has to be gated another way.
These tests drive a real headless Chromium against a server on 127.0.0.1 (no outside network) and skip when no
Chromium is installed. The gate is a plain function here: the driver must ask it about the hop, and a refused hop's
page must not stay open to be captured, read or clicked.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.slow


class _Pages(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        port = self.server.server_address[1]
        if self.path == "/away":  # a redirect to another host name of the same server
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{port}/landed")
            self.end_headers()
            return
        if self.path == "/stay":  # a redirect on the same host
            self.send_response(302)
            self.send_header("Location", "/landed")
            self.end_headers()
            return
        body = b"<html><body><p>Landed page text</p></body></html>"
        if self.path == "/framed":  # YouTube-like: the page loads, then an iframe asks another host (sign-in check)
            body = f"<html><body><p>Framed page text</p><iframe src='http://localhost:{port}/landed'></iframe>".encode()
        if self.path == "/leaves":  # the page itself navigates to another host
            body = f"<html><body><script>location.href='http://localhost:{port}/landed'</script>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture()
def driver_for():
    from tilo_browser.playwright_engine import PlaywrightDriver

    made = []

    def make(gate):
        try:
            driver = PlaywrightDriver(gate, {"width": 800, "height": 600})
        except Exception as exc:  # no Chromium in this environment
            pytest.skip(f"headless Chromium is not available: {type(exc).__name__}")
        made.append(driver)
        return driver

    yield make
    for driver in made:
        driver.close()


def _only(host):
    asked = []

    def gate(url, redirect_from=None):
        asked.append((url, redirect_from))
        return urlsplit(url).hostname == host

    return gate, asked


def test_DEMO_BROWSER_redirect_hop_to_another_host_is_gated_and_its_page_discarded(server, driver_for):
    gate, asked = _only("127.0.0.1")
    driver = driver_for(gate)
    out = driver.goto(f"http://127.0.0.1:{server}/away")
    hop = f"http://localhost:{server}/landed"
    assert (hop, f"http://127.0.0.1:{server}/away") in asked  # the hop was asked about, with where it came from
    assert out["aborted"] == hop
    assert out["final_url"] == "about:blank"
    assert "Landed page text" not in driver.page_text()


def test_DEMO_BROWSER_allowed_redirect_hop_still_lands(server, driver_for):
    gate, asked = _only("127.0.0.1")
    driver = driver_for(gate)
    out = driver.goto(f"http://127.0.0.1:{server}/stay")
    assert out["aborted"] is None
    assert out["final_url"] == f"http://127.0.0.1:{server}/landed"
    assert (f"http://127.0.0.1:{server}/landed", f"http://127.0.0.1:{server}/stay") in asked
    assert "Landed page text" in driver.page_text()


def test_DEMO_BROWSER_a_blocked_iframe_does_not_refuse_the_page_it_is_on(server, driver_for):
    """Live 20 Oct 17:09-17:12: every YouTube page loads, then an iframe opens accounts.google.com/ServiceLogin
    (Google's passive sign-in check); the egress gate blocks that iframe (as it must) and the whole session was
    refused. The iframe is still asked about and blocked; only the page's own navigation decides the session."""
    gate, asked = _only("127.0.0.1")
    driver = driver_for(gate)
    driver.goto(f"http://127.0.0.1:{server}/framed")
    driver.page.wait_for_timeout(500)  # the iframe asks after the page is ready
    out = driver._outcome()
    assert any(url == f"http://localhost:{server}/landed" for url, _ in asked)  # the iframe was gated and refused
    assert out["aborted"] is None
    assert out["final_url"] == f"http://127.0.0.1:{server}/framed"
    assert "Framed page text" in driver.page_text()


def test_DEMO_BROWSER_a_page_that_navigates_itself_off_the_allowlist_is_still_refused(server, driver_for):
    gate, _asked = _only("127.0.0.1")
    driver = driver_for(gate)
    out = driver.goto(f"http://127.0.0.1:{server}/leaves")
    driver.page.wait_for_timeout(500)  # the page's own script navigates after it loads
    out = driver._outcome()
    assert out["aborted"] == f"http://localhost:{server}/landed"


def test_DEMO_BROWSER_worker_refuses_a_navigation_whose_redirect_leaves_the_allowlist(server, driver_for):
    from tilo_browser.egress import Decision, EgressBlocked
    from tilo_browser.worker import BrowserWorker

    class Engine:
        def new_context(self, worker_gate):
            return driver_for(worker_gate)

    class Policy:  # EgressPolicy never allows an IP literal, so the local server needs a stand-in with its shape
        def __init__(self):
            self.blocked = []

        def check(self, url, redirect_from=None):
            ok = urlsplit(url).hostname == "127.0.0.1"
            decision = Decision(ok, "allowed" if ok else "host_not_allowlisted", url, None, "http", redirect_from)
            if not ok:
                self.blocked.append(decision)
            return decision

    policy = Policy()
    worker = BrowserWorker(Engine(), policy)
    with pytest.raises(EgressBlocked):
        worker.navigate(f"http://127.0.0.1:{server}/away")
    assert [d.redirect_from for d in policy.blocked] == [f"http://127.0.0.1:{server}/away"]
