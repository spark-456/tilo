"""DEMO-BROWSER: the taught browse loop keeps going on a bad model reply and always reads the page it ends on.

BR-01: a reply that is not one contract action is refused as `invalid_action` and counts as a step; the session goes
on (until max_steps), it does not end. A live model also often says `done` without `extract`; the step then had no
page text and failed, though the person watched it reach the page. Code now reads the page it ends on (a read-only
extract, recorded like any other action) before it closes. The fake service checks step numbers as tilo-browser does.
"""

from __future__ import annotations

from test_DEMO_BROWSER_STEP import FakeRpc, FakeRun
from tilo_api.browser_step import BrowseStepExecutor
from tilo_browser.session import SessionRefused


class StrictRpc(FakeRpc):
    """tilo-browser refuses an act whose step is not the next one (`step_cap`)."""

    def __init__(self):
        super().__init__()
        self.served = 0

    def act(self, session, body):
        if body["step"] != self.served + 1:
            raise SessionRefused("step_cap")
        self.served += 1
        return super().act(session, body)


def _run(proposals):
    run, rpc = FakeRun(), StrictRpc()
    replies = iter(proposals)
    result = BrowseStepExecutor(run, rpc, lambda goal, frame, text: next(replies)).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2", goal="Read", hosts=["example.org"]
    )
    return result, run, rpc


def test_DEMO_BROWSER_an_invalid_reply_counts_as_a_step_and_the_session_goes_on():
    result, run, rpc = _run([{"kind": "fly"}, {"kind": "extract"}, {"kind": "done"}])
    assert result.success
    assert rpc.calls == ["start", "extract", "end"]
    acted = [data for kind, data in run.events if kind == "browser.acted"]
    assert [(a["verdict"], a["reason"]) for a in acted] == [("refused", "invalid_action"), ("done", None)]
    assert acted[0]["step"] < acted[1]["step"]


def test_DEMO_BROWSER_three_invalid_replies_in_a_row_stop_the_session():
    result, run, rpc = _run([{"kind": "fly"}] * 3 + [{"kind": "extract"}])
    assert not result.success and rpc.calls == ["start", "end"]
    assert run.events[-1][0] == "browser.stopped"


def test_DEMO_BROWSER_done_without_a_read_reads_the_page_it_ends_on():
    result, run, rpc = _run([{"kind": "scroll", "direction": "down"}, {"kind": "done"}])
    assert result.success and b"First. Second. Third." in result.outputs[0].content
    assert rpc.calls == ["start", "scroll", "extract", "end"]
    assert [kind for kind, _ in run.events] == ["browser.started", "browser.acted", "browser.acted", "browser.stopped"]
    assert run.events[-1][1]["outcome"] == "done"


def test_DEMO_BROWSER_the_model_is_told_to_search_by_address_not_by_pressing_search():
    """tilo-browser refuses a click on a form's submit control as needing a person, so a search runs as a navigate."""
    from tilo_api.run_tools import browser_proposal_prompt

    prompt = browser_proposal_prompt("Search the site for Ada Lovelace", "")
    assert "search address" in prompt and "instead of pressing" in prompt


def test_DEMO_BROWSER_the_model_reply_may_come_fenced():
    from tilo_api.run_tools import parse_action

    assert parse_action('```json\n{"kind": "done"}\n```') == {"kind": "done"}
    assert parse_action('{"kind": "scroll", "direction": "down"}') == {"kind": "scroll", "direction": "down"}
    assert parse_action("I will click the link") == {}
    assert parse_action('["not", "an", "object"]') == {}
