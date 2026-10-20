"""DEMO-BROWSER: when the browser cannot open a page, the World says so in one plain sentence with what to try.

Live 20 Oct 17:09-17:12: three "Open youtube.com in the browser ..." runs got a refused session, read the page directly
and the person saw only "The agent is reading a web page": no browser and no reason. The research reader now records
one agent.working line (the line the World shows on its own) naming the site and what to try, then lets the unit read
the page directly as before.
"""

from __future__ import annotations

import pytest
import test_RUN_FAIL_1_tool_unit_after_answer as rig
from test_DEMO_BROWSER_STEP import FakeRun
from tilo_api import deps, run_tools
from tilo_browser.session import SessionRefused


class SayingRun(FakeRun):
    def put(self, kind, actor, target, summary, data, **kwargs):
        self.said = [*getattr(self, "said", []), (kind, actor, target, summary, data)]
        return super().put(kind, actor, target, summary, data, **kwargs)


def _reader(tmp_path, monkeypatch, reason):
    run, *_ = rig._run(tmp_path, monkeypatch, cap=40)
    run.brief = {**run.brief, "goal": "Open youtube.com in the browser and tell me what is on the home page"}
    bound = run.seams.runner.bind_run(run, run.seams.open_archive(org_id=deps.ORG_ID, run_id=rig.RUN))
    bound.run_owner = SayingRun()

    class Refusing:
        def start(self, body):
            raise SessionRefused(reason, 403)

    monkeypatch.setattr(run_tools, "research_browser", lambda mode: Refusing())
    monkeypatch.setattr(run_tools.BoundRunRunner, "building_of", lambda self, unit: "B1")
    return bound.page_reader({"id": "U1", "district": "D1", "unit_type": "research"}, "A_s1"), bound.run_owner


@pytest.mark.parametrize(
    ("reason", "words"),
    [
        ("login_wall", "sign-in"),
        ("offsite_host", "add that site to your task"),
        ("browser_unavailable", "try the task again"),
    ],
)
def test_DEMO_BROWSER_a_refused_page_is_one_plain_sentence_with_what_to_try(tmp_path, monkeypatch, reason, words):
    read, owner = _reader(tmp_path, monkeypatch, reason)
    with pytest.raises(SessionRefused):  # the fetch tool then reads the page directly, as before
        read("https://www.youtube.com/", "www.youtube.com")
    ((kind, actor, target, summary, data),) = owner.said
    assert (kind, actor, target, data) == ("agent.working", "A_s1", "B1", {"unit": "U1"})
    assert "www.youtube.com" in summary and words in summary
    sentence = summary.replace("www.youtube.com", "the site")
    assert sentence.count(".") == 1 and sentence.endswith(".") and len(summary) <= 140
