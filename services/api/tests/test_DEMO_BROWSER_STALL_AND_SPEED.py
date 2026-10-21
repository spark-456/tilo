"""DEMO-BROWSER (live 21 Oct, w_6XM54KZPP649VRD7E7AHF9JQXA: the panel sat on "Opened www.wikipedia.org" for 5+ minutes
while each computer_use call waited out its request timeout, 5xx, retried; owner: "the entire agentic process is too
slow").

* Every browser model call carries the router's PL-03 deadline (BROWSER_CALL_SECONDS, the fallback profile given its
  share), and gets one more try; before it, the run records BROWSER_BUSY_LINE (the Story and the browser panel say it).
* The model sees the frame at most MODEL_FRAME_SIDE pixels a side (points are on the 0..999 grid; fewer image tokens).
* A research read ends its session at the first read: no model call is spent on saying done.
* When the model cannot finish a named site's read, the browser still uses the site with no model: it reads the front
  page, which gives the site's own search address, then opens that search for the step's words and reads it.
"""

from __future__ import annotations

import io
import threading
import time
from types import SimpleNamespace

import pytest
from PIL import Image
from test_DEMO_BROWSER_REAL_ACTIONS import STEPS, FakeModel, FakeSafety, PointingRpc
from test_DEMO_BROWSER_STEP import FakeRun
from tilo_api.browser_step import BrowseStepExecutor

SEARCH = "https://en.wikipedia.org/w/index.php?search={words}"


def _png(width, height):
    out = io.BytesIO()
    Image.new("RGB", (width, height), "#468").save(out, "PNG")
    return out.getvalue()


class SummaryRun(FakeRun):
    """FakeRun that also keeps each event's summary (the line the Story shows)."""

    def __init__(self):
        super().__init__()
        self.lines: list[tuple[str, str]] = []

    def put(self, kind, actor, target, summary, data, **kwargs):
        self.lines.append((kind, summary))
        return super().put(kind, actor, target, summary, data, **kwargs)


class SiteRpc(PointingRpc):
    """A read of the site's front page ends with tilo-browser's search line, as the real one does."""

    def __init__(self):
        super().__init__()
        self.opened: dict[str, str] = {}

    def start(self, body):
        self.opened[body["session"]] = body["start_url"]
        return super().start(body)

    def act(self, session, body):
        result = super().act(session, body)
        if body["action"]["kind"] == "extract" and self.opened[session] == "https://wikipedia.org/":
            line = f"\nSearch this site: {SEARCH} (put the words to look for in place of {{words}})"
            result = {**result, "text": "Wikipedia front page." + line}
        return result


def _runner(monkeypatch, model, rpc, run=None):
    from tilo_api import run_tools

    monkeypatch.setattr(run_tools, "research_browser", lambda mode: rpc)
    monkeypatch.setattr(run_tools.BoundRunRunner, "building_of", lambda self, unit: "B2")
    monkeypatch.setattr(run_tools, "pause", lambda _seconds: None)
    run = run or SummaryRun()
    run.brief = {"goal": "Open wikipedia.org and find the tallest building in India"}
    runner = object.__new__(run_tools.BoundRunRunner)
    runner.run_owner, runner.mode, runner.budget = run, "live", None
    runner.providers, runner.typed, runner.hosts = {"computer_use": model}, frozenset({"wikipedia.org"}), set()
    runner.browser_lock, runner.safety, runner.frame_pages = threading.Lock(), FakeSafety(), {}
    return runner, run


UNIT = {"id": "U2", "district": "D1", "title": "Find the tallest building in India", "role": "specialist"}


def _context():
    return SimpleNamespace(agent_id="A_s2", upstream=(), skills=())


def test_DEMO_BROWSER_every_browser_model_call_has_a_short_deadline(monkeypatch):
    from tilo_api import run_tools

    model = FakeModel(STEPS)
    runner, _run = _runner(monkeypatch, model, SiteRpc())
    before = time.monotonic()
    runner.site_reading(UNIT, _context())
    assert len(model.deadlines) == 4
    for deadline in model.deadlines:
        assert deadline.first_share == run_tools.BROWSER_FIRST_SHARE
        assert before < deadline.at <= time.monotonic() + run_tools.BROWSER_CALL_SECONDS
    assert run_tools.BROWSER_CALL_SECONDS <= 20


def test_DEMO_BROWSER_a_busy_model_is_said_before_the_next_try(monkeypatch):
    from tilo_api import run_tools
    from tilo_providers.router import RouterDeadlineError

    model = FakeModel(STEPS)
    real, failures = model.generate_budgeted, iter([RouterDeadlineError("ran out of time", [])])

    def slow_once(request, budget, deadline=None):
        error = next(failures, None)
        if error:
            raise error
        return real(request, budget, deadline)

    model.generate_budgeted = slow_once
    runner, run = _runner(monkeypatch, model, PointingRpc())
    items = runner.site_reading(UNIT, _context())
    assert items and items[0].text == "First. Second. Third."
    assert ("agent.working", run_tools.BROWSER_BUSY_LINE) in run.lines
    assert run_tools.BROWSER_BUSY_LINE == "The model is busy, so Tilo's browser is trying again."


def test_DEMO_BROWSER_the_model_sees_a_smaller_frame():
    from tilo_api.run_tools import MODEL_FRAME_SIDE, model_frame

    small = model_frame(_png(1200, 800))
    with Image.open(io.BytesIO(small)) as image:
        assert image.size == (MODEL_FRAME_SIDE, 512)
    already = _png(600, 400)
    assert model_frame(already) == already
    assert model_frame(b"\x89PNG\r\n\x1a\nnot a picture") == b"\x89PNG\r\n\x1a\nnot a picture"


def test_DEMO_BROWSER_a_read_ends_the_session_without_a_done_call():
    asked = []

    def propose(goal, frame, text):
        asked.append(goal)
        return [{"kind": "extract"}, {"kind": "done"}][len(asked) - 1]

    run, rpc = FakeRun(), PointingRpc()
    result = BrowseStepExecutor(run, rpc, propose).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2", goal="Find", hosts=["example.org"],
        finish_on_read=True,
    )  # fmt: skip
    assert result.success and len(asked) == 1
    assert run.events[-1][0] == "browser.stopped" and run.events[-1][1]["outcome"] == "done"


@pytest.mark.parametrize(
    "failure",
    ["invalid replies", "busy model"],
)
def test_DEMO_BROWSER_when_the_model_cannot_finish_the_site_is_still_searched_in_the_browser(monkeypatch, failure):
    from tilo_providers.errors import QuotaError

    model = FakeModel([{"kind": "fly"}] * 3)
    if failure == "busy model":

        def busy(request, budget, deadline=None):
            raise QuotaError("rate limited")

        model.generate_budgeted = busy
    rpc = SiteRpc()
    runner, run = _runner(monkeypatch, model, rpc)
    items = runner.site_reading(UNIT, _context())
    opened = [start["start_url"] for start in rpc.starts]
    assert opened[-2:] == [
        "https://wikipedia.org/",
        "https://en.wikipedia.org/w/index.php?search=Find+the+tallest+building+in+India",
    ], "the front page, then the site's own search for the step's words"
    assert rpc.calls[-7:] == ["start", "extract", "end", "start", "scroll", "extract", "end"]
    assert [i.text for i in items] == ["First. Second. Third."]
    captions = [line for kind, line in run.lines if kind == "browser.acted"]
    assert "Searching en.wikipedia.org" in captions, "the person sees the search happen"


def test_DEMO_BROWSER_the_run_budget_hands_the_deadline_to_the_router():
    from tilo_api.run_tools import RunBudget

    seen = {}

    def generate(role, request, *, budget, deadline=None):
        seen.update(role=role, budget=budget, deadline=deadline)
        return SimpleNamespace(budget=budget - 1.0)

    result, spent = RunBudget(10.0).call(generate, "computer_use", "request", deadline="the deadline")
    assert seen == {"role": "computer_use", "budget": 10.0, "deadline": "the deadline"} and spent == 1.0
