"""DEMO-BROWSER: a page read in the visible browser is several recorded steps the person can watch.

Live world w_1R0J8CGNDT3864C7Q0W3QG0YE5 (20 Oct 17:03): reading en.wikipedia.org was one act (extract) between open and
close, so the panel had one frame to show. A read now looks through the page first: it scrolls down twice and then
reads, each a real read-only action recorded as `browser.acted` with its own frame (HR-1), in the order tilo-browser
served them. The page text is still the whole page's.
"""

from __future__ import annotations

from test_DEMO_BROWSER_STEP import FakeRpc, FakeRun
from tilo_api.browser_step import READ_SCROLLS, BrowseStepExecutor
from tilo_browser.session import SessionRefused


class StrictRpc(FakeRpc):
    def __init__(self):
        super().__init__()
        self.served = 0

    def act(self, session, body):
        if body["step"] != self.served + 1:
            raise SessionRefused("step_cap")
        self.served += 1
        return super().act(session, body)


def _read():
    run, rpc = FakeRun(), StrictRpc()
    text = BrowseStepExecutor(run, rpc, lambda *_: None).read_page(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B1",
        url="https://en.wikipedia.org/wiki/Main_Page", host="en.wikipedia.org",
    )  # fmt: skip
    return text, run, rpc


def test_DEMO_BROWSER_a_read_scrolls_through_the_page_then_reads_it():
    text, run, rpc = _read()
    assert READ_SCROLLS >= 1
    assert text == "First. Second. Third."
    assert rpc.calls == ["start", *["scroll"] * READ_SCROLLS, "extract", "end"]
    acted = [data for kind, data in run.events if kind == "browser.acted"]
    assert [a["kind"] for a in acted] == ["scroll"] * READ_SCROLLS + ["extract"]
    assert [a["step"] for a in acted] == list(range(1, READ_SCROLLS + 2))
    assert all(a["frame"] for a in acted), "every step is a real recorded frame"
    assert acted[0]["caption"] == "Scrolling down" and acted[-1]["caption"] == "Reading en.wikipedia.org"
    started, stopped = run.events[0][1], run.events[-1][1]
    assert started["max_steps"] == READ_SCROLLS + 1
    assert stopped == {"session": started["session"], "outcome": "done", "steps": READ_SCROLLS + 1}


def test_DEMO_BROWSER_every_frame_of_a_read_is_kept_under_its_own_id():
    _text, run, _rpc = _read()
    frames = [data["frame"]["artifact_id"] for kind, data in run.events if kind != "browser.stopped"]
    assert len(set(frames)) == READ_SCROLLS + 2
    assert set(run.seams.artifacts.saved) == set(frames)
