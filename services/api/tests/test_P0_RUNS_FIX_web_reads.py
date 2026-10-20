"""P0-RUNS-FIX (owner, 20 Oct: "its all failed ... i cant see any agentic ai browser"): live runs asked fetch_url for
https://www.google.com, the allowlist refused it, and the unit wrote "could not fetch" as its result. Now:
* a search-engine URL is never fetched: with a query it becomes a web_search, without one the model is told to search;
* a refused host is one skipped source with a plain note, never a failed tool call;
* a page on an allowlisted host is read in the visible Tilo browser (open, extract, close: recorded browser.* events
  with real frames), read-only and with no model; without a browser the page is fetched and the reply says so.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_DEMO_BROWSER_STEP import FakeRpc, FakeRun
from tilo_api.browser_step import READ_SCROLLS, BrowseStepExecutor
from tilo_api.web_tools import BROWSER_FALLBACK_NOTE, FetchTool, search_engine_host
from tilo_browser.fetch import FetchBlocked
from tilo_browser.session import SessionRefused
from tilo_harness.tools import ToolResult


class FakeService:
    def __init__(self, blocked: bool = False) -> None:
        self.blocked, self.urls = blocked, []
        self.archive_store = SimpleNamespace(get_bytes=lambda *_: b"Plain page text.")

    def fetch(self, url, **_):
        self.urls.append(url)
        if self.blocked:
            raise FetchBlocked("host_not_allowlisted", url, host="www.example.net", allowlist=("wikipedia.org",))
        return SimpleNamespace(sha256="abc", media_type="text/plain", archive_ref="ar_1")


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def run(self, args):
        self.queries.append(args["query"])
        return ToolResult(json.dumps({"sources": [{"title": "Asura - Wikipedia"}]}))


def _fetch(service=None, *, browser=None, hosts=("en.wikipedia.org",)):
    unit = {"id": "U2", "district": "D1"}
    search = FakeSearch()
    tool = FetchTool(
        FakeRun(), service or FakeService(), set(hosts), unit, SimpleNamespace(agent_id="A_s2"), {}, search=search,
        browser=browser,
    )  # fmt: skip
    return tool, search


@pytest.mark.parametrize(
    "host", ["www.google.com", "google.com", "www.google.co.in", "bing.com", "duckduckgo.com", "search.yahoo.com"]
)
def test_P0_RUNS_FIX_search_engines_are_recognised(host) -> None:
    assert search_engine_host(host)


@pytest.mark.parametrize("host", ["en.wikipedia.org", "britannica.com", "docs.python.org", "googleblog.com"])
def test_P0_RUNS_FIX_ordinary_sites_are_not_search_engines(host) -> None:
    assert not search_engine_host(host)


def test_P0_RUNS_FIX_a_google_search_url_becomes_a_web_search() -> None:
    service = FakeService()
    tool, search = _fetch(service)
    result = tool.run({"url": "https://www.google.com/search?q=asura+mythology"})
    assert search.queries == ["asura mythology"] and service.urls == []
    assert "Asura - Wikipedia" in result.content


def test_P0_RUNS_FIX_a_bare_search_engine_page_tells_the_agent_to_search() -> None:
    service = FakeService()
    tool, search = _fetch(service)
    result = tool.run({"url": "https://www.google.com"})
    assert service.urls == [] and search.queries == []
    assert "web_search" in result.content and "www.google.com" in result.content


def test_P0_RUNS_FIX_a_blocked_host_is_a_skipped_source_not_a_failure() -> None:
    tool, _ = _fetch(FakeService(blocked=True))
    result = tool.run({"url": "https://www.example.net/page"})
    assert result.content.startswith("(not read:") and "host_not_allowlisted" in result.content


def test_P0_RUNS_FIX_an_allowlisted_page_is_read_in_the_visible_browser() -> None:
    run, rpc = FakeRun(), FakeRpc()
    executor = BrowseStepExecutor(run, rpc, lambda *_: None)
    unit = {"id": "U2", "district": "D1"}

    text = executor.read_page(
        unit=unit, agent="A_s2", building="B2", url="https://example.org/search", host="example.org"
    )

    assert text == "First. Second. Third."
    # DEMO-BROWSER: the read looks through the page (READ_SCROLLS scrolls) before it extracts
    assert rpc.calls == ["start", *["scroll"] * READ_SCROLLS, "extract", "end"]
    kinds = [kind for kind, _ in run.events]
    assert kinds == ["browser.started", *["browser.acted"] * (READ_SCROLLS + 1), "browser.stopped"]
    started, acted, stopped = run.events[0][1], run.events[-2][1], run.events[-1][1]
    assert started["frame"] and acted["frame"], "every recorded step carries its real frame"
    assert acted["kind"] == "extract" and acted["verdict"] == "done" and acted["caption"] == "Reading example.org"
    assert stopped["outcome"] == "done" and stopped["steps"] == READ_SCROLLS + 1


def test_P0_RUNS_FIX_fetch_uses_the_browser_for_allowlisted_hosts_only() -> None:
    reads: list[tuple[str, str]] = []
    service = FakeService()

    def browser(url, host):
        reads.append((url, host))
        return "Text the browser read."

    tool, _ = _fetch(service, browser=browser)
    assert tool.run({"url": "https://en.wikipedia.org/wiki/Asura"}).content == "Text the browser read."
    assert reads == [("https://en.wikipedia.org/wiki/Asura", "en.wikipedia.org")] and service.urls == []

    tool.run({"url": "https://elsewhere.example/page"})
    assert len(reads) == 1, "a host outside the allowlist never opens the browser"


def test_P0_RUNS_FIX_an_unavailable_browser_falls_back_to_fetch_and_says_so() -> None:
    service = FakeService()

    def browser(url, host):
        raise SessionRefused("browser_unavailable", 503)

    tool, _ = _fetch(service, browser=browser)
    result = tool.run({"url": "https://en.wikipedia.org/wiki/Asura"})
    assert service.urls == ["https://en.wikipedia.org/wiki/Asura"]
    assert result.content == BROWSER_FALLBACK_NOTE + "Plain page text."


def test_P0_RUNS_FIX_replay_and_dev_runs_open_no_browser(monkeypatch) -> None:
    from tilo_api.run_tools import research_browser

    monkeypatch.setenv("TILO_BROWSER_URL", "https://tilo-browser.example.run.app")
    assert research_browser("replay") is None
    assert research_browser("live") is not None
    monkeypatch.delenv("TILO_BROWSER_URL")
    assert research_browser("live") is None


def test_P0_RUNS_FIX_the_browser_may_follow_a_result_redirect_to_known_hosts_only() -> None:
    bodies: list[dict] = []

    class Recording(FakeRpc):
        def start(self, body):
            bodies.append(body)
            return super().start(body)

    also = tuple(f"h{n}.example.org" for n in range(30))
    BrowseStepExecutor(FakeRun(), Recording(), lambda *_: None).read_page(
        unit={"id": "U2", "district": "D1"},
        agent="A_s2",
        building="B2",
        url="https://example.org/",
        host="example.org",
        also=also,
    )
    assert bodies[0]["allow_hosts"][0] == "example.org" and len(bodies[0]["allow_hosts"]) == 20
