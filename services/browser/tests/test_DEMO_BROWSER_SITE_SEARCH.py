"""DEMO-BROWSER: "open wikipedia.org and find the population of Japan" searches the site the person named.

Typing into a site's search box and pressing its button is refused (a form submit needs a person), so the read of a page
tells the reader the site's own search address instead: from the page's GET search form, else from its OpenSearch
description (fetched inside the page, through the egress gate). The reader then opens that address like any page,
each step a recorded frame. Only an address inside the session's allowlist is told. Nothing reads the task's words.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from _browser_lib import FakeDriver, FakeEngine, FakeWeb, doc

URL = "https://example.org/page"


# --- the session: an extract ends with the site's search address when it is allowed ---


class SearchingDriver(FakeDriver):
    address: str | None = "https://example.org/search?q={words}"

    def search_address(self):
        return self.address


class SearchingEngine(FakeEngine):
    def new_context(self, gate):
        driver = SearchingDriver(self.web, gate, len(self.contexts))
        self.contexts.append(driver)
        return driver


def _read(address):
    from tilo_browser.session import BrowserSessions

    SearchingDriver.address = address
    web = FakeWeb()
    web.add(URL, title="Page", text="Public text", tree=doc())
    sessions = BrowserSessions(SearchingEngine(web))
    session = "bs_01JB7A0000000000000000SRC1"
    started = sessions.start(
        {
            "session": session,
            "world_id": "w_demo",
            "run_id": "r_demo",
            "unit_id": "U1",
            "allow_hosts": ["example.org"],
            "start_url": URL,
            "viewport": {"width": 1200, "height": 800},
        }
    )
    read = sessions.act(session, {"step": 1, "action": {"kind": "extract"}, "digest": None, "outbox_id": None})
    return started, read


def test_DEMO_BROWSER_a_read_ends_with_the_sites_own_search_address():
    started, read = _read("https://example.org/search?q={words}")
    assert read["text"].startswith("Public text")
    assert read["text"].endswith(
        "\nSearch this site: https://example.org/search?q={words} (put the words to look for in place of {words})"
    )
    assert started["text"] == ""  # only a read carries text


@pytest.mark.parametrize("address", [None, "https://elsewhere.example/search?q={words}", "javascript:alert(1)"])
def test_DEMO_BROWSER_no_search_line_without_an_allowed_address(address):
    _started, read = _read(address)
    assert "Search this site" not in read["text"]


# --- the driver: the address comes from the page's GET form, else its OpenSearch description (real Chromium) ---


class _Pages(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        pages = {
            "/form": "<form action='/w/index.php'><input type='hidden' name='title' value='Special:Search'>"
            "<input type='search' name='search'></form>",
            "/post": "<form method='post' action='/login'><input type='text' name='user'></form>",
            "/opensearch": "<link rel='search' type='application/opensearchdescription+xml' href='/os.xml'>",
            "/os.xml": "<OpenSearchDescription xmlns='http://a9.com/-/spec/opensearch/1.1/'>"
            "<Url type='text/html' template='http://127.0.0.1:PORT/find?q={searchTerms}'/></OpenSearchDescription>",
        }
        body = pages.get(self.path.split("?")[0], "<p>nothing</p>").replace("PORT", str(self.server.server_address[1]))
        self.send_response(200)
        self.send_header("Content-Type", "application/xml" if self.path.endswith(".xml") else "text/html")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Pages)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.mark.slow
def test_DEMO_BROWSER_the_driver_finds_a_get_form_or_an_opensearch_address(server):
    from tilo_browser.playwright_engine import PlaywrightDriver

    try:
        driver = PlaywrightDriver(lambda url, redirect_from=None: True, {"width": 800, "height": 600})
    except Exception as exc:  # no Chromium in this environment
        pytest.skip(f"headless Chromium is not available: {type(exc).__name__}")
    try:
        base = f"http://127.0.0.1:{server}"
        driver.goto(f"{base}/form")
        assert driver.search_address() == f"{base}/w/index.php?title=Special%3ASearch&search={{words}}"
        driver.goto(f"{base}/post")
        assert driver.search_address() is None  # a POST form is never a search address
        driver.goto(f"{base}/opensearch")
        assert driver.search_address() == f"{base}/find?q={{words}}"
    finally:
        driver.close()
