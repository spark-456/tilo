"""DEMO-BROWSER (BR-02, FR-CON-07): which pages a run's visible browser and its fetches may open.

Live run w_3Q2PR0CRTEX2THFH5DHSECPPGM (20 Oct) asked "Open wikipedia.org, search for "Eiffel Tower" and give me the 5
most interesting facts". Its unit loaded summarise-public-url, whose only tool is fetch_url, and the run's allowlist
held only the hosts of https URLs: nothing, so every read was refused and the browser never opened. BR-02: the hosts
the person typed, and a used taught skill's hosts, each also count as `*.<host>` (wikipedia.org covers
en.wikipedia.org); the hosts of search results stay exact.
"""

from __future__ import annotations

from types import SimpleNamespace

import test_RUN_FAIL_1_tool_unit_after_answer as rig
from test_DEMO_BROWSER_STEP import FakeRpc, FakeRun
from tilo_api import deps, run_tools
from tilo_api.web_tools import FetchTool, allow_entries


class RecordingService:
    def __init__(self) -> None:
        self.allowed: list[tuple[str, ...]] = []
        self.archive_store = SimpleNamespace(get_bytes=lambda *_: b"Page text read directly.")

    def fetch(self, url, *, allow_hosts, **_):
        self.allowed.append(tuple(allow_hosts))
        return SimpleNamespace(sha256="abc", media_type="text/plain", archive_ref="ar_1")


def _tool(service, *, hosts=(), typed=(), browser=None):
    unit, context = {"id": "U1", "district": "D1"}, SimpleNamespace(agent_id="A_s1")
    return FetchTool(FakeRun(), service, set(hosts), unit, context, {}, browser=browser, typed=frozenset(typed))


def test_DEMO_BROWSER_typed_hosts_cover_their_subdomains_and_search_hosts_stay_exact() -> None:
    assert allow_entries({"news.example.net"}, {"wikipedia.org"}) == [
        "*.wikipedia.org",
        "wikipedia.org",
        "news.example.net",
    ]


def test_DEMO_BROWSER_a_page_anywhere_on_a_named_site_opens_in_the_browser() -> None:
    reads: list[str] = []

    def browser(url, host):
        reads.append(url)
        return "Today's featured article."

    tool = _tool(RecordingService(), hosts={"news.example.net"}, typed={"wikipedia.org"}, browser=browser)
    assert tool.run({"url": "https://en.wikipedia.org/wiki/Main_Page"}).content == "Today's featured article."
    tool.run({"url": "https://sub.news.example.net/x"})  # a search host is not widened
    assert reads == ["https://en.wikipedia.org/wiki/Main_Page"]


def test_DEMO_BROWSER_a_direct_read_gets_the_same_allowlist() -> None:
    service = RecordingService()
    _tool(service, hosts={"news.example.net"}, typed={"wikipedia.org"}).run({"url": "https://en.wikipedia.org/"})
    assert service.allowed == [("*.wikipedia.org", "wikipedia.org", "news.example.net")]


def test_DEMO_BROWSER_the_research_browser_opens_a_page_of_the_site_the_person_named(tmp_path, monkeypatch) -> None:
    run, _state, _asking, _models = rig._run(tmp_path, monkeypatch, cap=40)
    run.brief = {**run.brief, "goal": "Use the browser to open wikipedia.org and summarise today's featured article"}
    bound = run.seams.runner.bind_run(run, run.seams.open_archive(org_id=deps.ORG_ID, run_id=rig.RUN))
    bound.run_owner = FakeRun()  # the allowlist is the bound run's; events go to a world that needs no layout
    bodies: list[dict] = []

    class Rpc(FakeRpc):
        def start(self, body):
            bodies.append(body)
            return super().start(body)

    monkeypatch.setattr(run_tools, "research_browser", lambda mode: Rpc())
    monkeypatch.setattr(run_tools.BoundRunRunner, "building_of", lambda self, unit: "B1")
    read = bound.page_reader({"id": "U1", "district": "D1", "unit_type": "research"}, "A_s1")
    assert read is not None

    assert read("https://en.wikipedia.org/wiki/Main_Page", "en.wikipedia.org") == "First. Second. Third."
    assert bodies[0]["start_url"] == "https://en.wikipedia.org/wiki/Main_Page"
    assert bodies[0]["allow_hosts"][:3] == ["en.wikipedia.org", "*.wikipedia.org", "wikipedia.org"]


def test_DEMO_BROWSER_a_taught_browse_step_starts_on_its_host_and_may_open_its_subdomains() -> None:
    hosts = run_tools.browse_hosts({"hosts": ["youtube.com"]}, {"news.example.net"}, frozenset({"wikipedia.org"}))
    assert hosts[0] == "youtube.com"  # the session starts here
    assert {"*.youtube.com", "*.wikipedia.org", "wikipedia.org", "news.example.net"} <= set(hosts)
    assert len(hosts) <= 20


def test_DEMO_BROWSER_a_taught_browse_step_without_hosts_starts_on_a_named_site_never_a_pattern() -> None:
    hosts = run_tools.browse_hosts({}, set(), frozenset({"wikipedia.org"}))
    assert hosts[0] == "wikipedia.org"
    assert run_tools.browse_hosts({}, set(), frozenset()) == []
