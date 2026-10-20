"""DEMO-BROWSER: "Use the browser to open wikipedia.org and summarise today's featured article" (live run
r_7XBRE64F21E6SJ3AN2QVKZEFJZ, world w_02GXQ03ZA2DKY4RAV8R7CAMKD5, 21 Oct).

* The Director's brief named the site as www.wikipedia.org, and the person's own words were not read, so the
  allowlist was ['*.www.wikipedia.org', 'www.wikipedia.org']: en.wikipedia.org was refused and the browser never
  opened. A named site is now the whole site: "x.org" or "www.x.org" allows x.org and *.x.org, and the person's own
  request is read too.
* The unit read nothing, wrote "I cannot provide a summary ... could not be retrieved" and the run said Done. A unit
  whose page reads were all refused, with no search result and nothing handed to it, now fails with one plain reason.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import test_RUN_FAIL_1_tool_unit_after_answer as rig
from test_DEMO_BROWSER_STEP import FakeRun
from tilo_api import deps, run_tools
from tilo_api.run_tools import brief_texts
from tilo_api.web_tools import FetchTool, allow_entries, typed_hosts
from tilo_browser.egress import EgressPolicy
from tilo_harness.executor import UnitContext, UnitOutcome

ASKED = "Use the browser to open wikipedia.org and summarise today's featured article"


def test_DEMO_BROWSER_a_named_www_site_is_the_whole_site():
    policy = EgressPolicy(allow_entries(set(), {"www.wikipedia.org"}))
    for url in ("https://en.wikipedia.org/wiki/Main_Page", "https://wikipedia.org/", "https://www.wikipedia.org/"):
        assert policy.check(url).allowed, url
    assert not policy.check("https://wikipedia.org.evil.example/").allowed


def test_DEMO_BROWSER_the_persons_own_words_name_the_site_too():
    run = SimpleNamespace(
        brief={"goal": "Open www.wikipedia.org and summarise today's featured article"},
        intake_answers=(),
        world_id="w_demo",
        store=SimpleNamespace(events={"w_demo": [{"type": "world.requested", "data": {"title": ASKED}}]}),
    )
    assert {"wikipedia.org", "www.wikipedia.org"} <= typed_hosts(brief_texts(run))


def test_DEMO_BROWSER_the_read_opens_in_the_browser_for_a_www_named_site():
    reads: list[str] = []
    service = SimpleNamespace(archive_store=None)

    def browser(url, host):
        reads.append(url)
        return "Today's featured article."

    tool = FetchTool(
        FakeRun(), service, set(), {"id": "U1", "district": "D1"}, SimpleNamespace(agent_id="A_s1"), {},
        browser=browser, typed=frozenset({"www.wikipedia.org"}),
    )  # fmt: skip
    assert tool.run({"url": "https://en.wikipedia.org/wiki/Main_Page"}).content == "Today's featured article."
    assert reads == ["https://en.wikipedia.org/wiki/Main_Page"]


def test_DEMO_BROWSER_a_unit_whose_reads_were_all_refused_fails_with_a_plain_reason(tmp_path, monkeypatch):
    run, *_ = rig._run(tmp_path, monkeypatch, cap=40)
    run.brief = {**run.brief, "goal": ASKED}
    bound = run.seams.runner.bind_run(run, run.seams.open_archive(org_id=deps.ORG_ID, run_id=rig.RUN))

    class ClaimsDone:  # the live model: one refused read, then a "could not be retrieved" result marked done
        def __init__(self, *args, tools=None, **kwargs):
            self.tools = tools

        async def run(self, unit, context):
            result = self.tools.get("fetch_url").run({"url": "https://elsewhere.example/page"})
            assert result.content.startswith("(not read:")
            return UnitOutcome(True, "I cannot provide a summary: the page could not be retrieved.")

    monkeypatch.setattr(run_tools, "DefaultUnitRunner", ClaimsDone)
    unit = {"id": "U1", "unit_type": "research", "title": "Read the page", "role": "specialist", "district": "D1",
            "skills": [], "connectors": [], "actions": [], "depends_on": []}  # fmt: skip
    run.plan = {"units": [unit]}  # the run is not started: its plan is this one unit, with nothing upstream
    run.store.events.setdefault(rig.WORLD, [])
    outcome = asyncio.run(bound.run(unit, UnitContext(agent_id="A_s1", skills=(), brief=run.brief)))

    assert outcome.success is False
    assert "elsewhere.example" in outcome.reason and "name it in your task" in outcome.reason
    assert outcome.reason.endswith(".") and outcome.reason.count(". ") == 0
