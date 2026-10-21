"""DEMO-BROWSER (owner, 21 Oct: "the agentic browser isnt working like an agentic browser, but rather like a screenshot
playlist ... the cursor must do some real work, not just pretend").

* Only a step where the mouse acts at a point (a click, typing into a field, a scroll's wheel) carries a target_box,
  the cursor the person sees; a read or an address opened carries none.
* Typing with submit true is captioned as typing and pressing Enter (the words stay out of the event, BR-13).
* A page of a site the person named is used through the BR-01 loop (the computer_use model points, code decides): asked
  for a search address it starts on the site's front page so the search is typed there; any other page is read with
  no model, as before.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest
from test_DEMO_BROWSER_STEP import FakeRpc, FakeRun
from tilo_api.browser_step import READ_SCROLLS, BrowseStepExecutor

SEARCH_BOX = {"x": 330, "y": 70, "width": 400, "height": 36}


PNG = b"\x89PNG\r\n\x1a\n" + b"frame"  # PNG magic bytes: the model's media part checks them (LW-06)


class PointingRpc(FakeRpc):
    """tilo-browser's answers: an inspect names the element at the point; each act returns where the mouse acted."""

    def __init__(self):
        super().__init__()
        self.starts: list[dict] = []

    @staticmethod
    def frame(session, step, kind, text=""):
        found = FakeRpc.frame(session, step, kind, text)
        found["screenshot_artifact"] = {
            "mime_type": "image/png",
            "sha256": hashlib.sha256(PNG).hexdigest(),
            "base64": base64.b64encode(PNG).decode(),
        }
        return found

    def start(self, body):
        self.starts.append(body)
        return super().start(body)

    def inspect(self, session, at):
        self.calls.append("inspect")
        facts = {"tag": "input", "role": "textbox", "name": "Search", "input_type": "search", "editable": True,
                 "secure": False, "form_method": "get", "link_host": None, "download": False}  # fmt: skip
        return {"session": session, "facts": facts, "digest": "0" * 64, "target_box": SEARCH_BOX}

    def act(self, session, body):
        result = super().act(session, body)
        return {**result, "target_box": SEARCH_BOX if body["action"]["kind"] == "type" else result["target_box"]}


STEPS = [
    {"kind": "type", "at": {"x": 440, "y": 110}, "text": "population of Japan", "submit": True},
    {"kind": "click", "at": {"x": 200, "y": 300}},
    {"kind": "scroll", "direction": "down"},
    {"kind": "extract"},
    {"kind": "done"},
]


def _execute(steps=STEPS, **extra):
    run, rpc = FakeRun(), PointingRpc()
    replies = iter(steps)
    result = BrowseStepExecutor(run, rpc, lambda goal, frame, text: next(replies)).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2", goal="Find", hosts=["example.org"], **extra
    )
    return result, run, rpc


def test_DEMO_BROWSER_only_pointer_steps_carry_a_cursor():
    result, run, _rpc = _execute()
    assert result.success
    acted = [data for kind, data in run.events if kind == "browser.acted"]
    assert [a["kind"] for a in acted] == ["type", "click", "scroll", "extract"]
    assert acted[0]["target_box"] == SEARCH_BOX, "typing: the field the keys went into"
    assert "target_box" in acted[1] and "target_box" in acted[2], "a click and a wheel act at a point"
    assert "target_box" not in acted[3], "a read has no point on the page"
    started = next(data for kind, data in run.events if kind == "browser.started")
    assert "target_box" not in started


def test_DEMO_BROWSER_typing_with_enter_is_captioned_without_the_words():
    _result, run, _rpc = _execute()
    typed = next(data for kind, data in run.events if kind == "browser.acted" and data["kind"] == "type")
    assert typed["caption"] == "Typing in Search and pressing Enter"
    assert typed["chars"] == len("population of Japan")
    assert "Japan" not in json.dumps([data for _kind, data in run.events])  # BR-13: never the typed words


def test_DEMO_BROWSER_a_session_opens_the_address_it_is_given():
    _result, _run, rpc = _execute([{"kind": "extract"}, {"kind": "done"}], start="https://example.org/wiki/Japan")
    assert rpc.starts[0]["start_url"] == "https://example.org/wiki/Japan"
    _result, _run, rpc = _execute([{"kind": "extract"}, {"kind": "done"}])
    assert rpc.starts[0]["start_url"] == "https://example.org/"


def test_DEMO_BROWSER_a_read_points_where_the_wheel_turned_and_not_at_the_read():
    run, rpc = FakeRun(), PointingRpc()
    BrowseStepExecutor(run, rpc, lambda *_: None).read_page(
        unit={"id": "U2", "district": "D1"},
        agent="A_s2",
        building="B2",
        url="https://example.org/a",
        host="example.org",
    )
    acted = [data for kind, data in run.events if kind == "browser.acted"]
    assert [("target_box" in a) for a in acted] == [True] * READ_SCROLLS + [False]


# --- the research reader: a named site is used by the model, another page is read ---


class FakeModel:
    """The computer_use role, recorded: one contract action per call (no paid call)."""

    def __init__(self, steps):
        self.steps, self.prompts, self.deadlines, self.frames = iter(steps), [], [], []

    def generate_budgeted(self, request, budget, deadline=None):
        self.prompts.append(request.prompt)
        self.deadlines.append(deadline)
        self.frames.append(request.parts[0].data)
        return SimpleNamespace(text=json.dumps(next(self.steps))), 0.0


def _reader(monkeypatch, steps=STEPS, typed=("wikipedia.org",)):
    from tilo_api import run_tools

    rpc = PointingRpc()
    monkeypatch.setattr(run_tools, "research_browser", lambda mode: rpc)
    monkeypatch.setattr(run_tools.BoundRunRunner, "building_of", lambda self, unit: "B2")
    run = FakeRun()
    run.brief = {"goal": "Open wikipedia.org and find the population of Japan"}
    runner = object.__new__(run_tools.BoundRunRunner)
    model = FakeModel(steps)
    runner.run_owner, runner.mode, runner.budget = run, "live", None
    runner.providers, runner.typed, runner.hosts = {"computer_use": model}, frozenset(typed), set(typed)
    runner.browser_lock, runner.safety, runner.frame_pages = threading.Lock(), FakeSafety(), {}
    return runner.page_reader({"id": "U2", "district": "D1", "title": "Find the figure"}, "A_s2"), rpc, run, model


def test_DEMO_BROWSER_a_named_sites_search_is_typed_on_its_front_page(monkeypatch):
    read, rpc, run, model = _reader(monkeypatch)
    text = read("https://en.wikipedia.org/w/index.php?title=Special%3ASearch&search=population", "en.wikipedia.org")
    assert text == "First. Second. Third."
    assert rpc.starts[0]["start_url"] == "https://en.wikipedia.org/"
    assert rpc.starts[0]["allow_hosts"][0] == "en.wikipedia.org" and "*.wikipedia.org" in rpc.starts[0]["allow_hosts"]
    assert rpc.calls == ["start", "inspect", "type", "inspect", "click", "scroll", "extract", "end"]
    assert len(model.prompts) == 4, "the read ends the session: no call is spent on saying done"
    assert "find the population of Japan" in model.prompts[0]


def test_DEMO_BROWSER_a_named_sites_page_opens_where_it_was_asked(monkeypatch):
    read, rpc, _run, _model = _reader(monkeypatch, steps=[{"kind": "scroll", "direction": "down"}, {"kind": "done"}])
    assert read("https://en.wikipedia.org/wiki/Japan", "en.wikipedia.org") == "First. Second. Third."
    assert rpc.starts[0]["start_url"] == "https://en.wikipedia.org/wiki/Japan"
    assert rpc.calls == ["start", "scroll", "extract", "end"]


def test_DEMO_BROWSER_another_sites_page_is_read_with_no_model(monkeypatch):
    read, rpc, _run, model = _reader(monkeypatch)
    assert read("https://news.example.net/story", "news.example.net") == "First. Second. Third."
    assert model.prompts == []
    assert rpc.calls == ["start", *["scroll"] * READ_SCROLLS, "extract", "end"]


@pytest.mark.parametrize(
    ("host", "named"),
    [
        ("en.wikipedia.org", True),
        ("www.wikipedia.org", True),
        ("wikipedia.org", True),
        ("notwikipedia.org", False),
        ("wikipedia.org.example.net", False),
    ],
)
def test_DEMO_BROWSER_a_named_site_covers_its_subdomains_only(monkeypatch, host, named):
    from tilo_api import run_tools

    runner = object.__new__(run_tools.BoundRunRunner)
    runner.typed = frozenset({"www.wikipedia.org"})
    assert runner.named_site(host) is named


class FakeSafety:
    """The run's safety screen, recorded: flags text that holds `flag`."""

    def __init__(self, flag: str = "<<flag>>"):
        self.flag, self.screened = flag, []

    def check(self, text):
        self.screened.append(text)
        return {"flagged": self.flag in text}


def test_DEMO_BROWSER_a_session_the_model_cannot_finish_is_read_in_the_browser_without_it(monkeypatch):
    read, rpc, run, _model = _reader(monkeypatch, steps=[{"kind": "fly"}] * 3)
    assert read("https://en.wikipedia.org/wiki/Japan", "en.wikipedia.org") == "First. Second. Third."
    assert rpc.calls == ["start", "end", "start", *["scroll"] * READ_SCROLLS, "extract", "end"]
    assert [kind for kind, _ in run.events].count("browser.started") == 2


def test_DEMO_BROWSER_a_model_that_stays_busy_is_read_in_the_browser_without_it(monkeypatch):
    """Live 21 Oct: every computer_use call hit a quota or 503, the read fell to a direct fetch, which Wikipedia's
    list pages are too large for. Now the model gets one more try, then the page is read in the browser anyway."""
    from tilo_api import run_tools
    from tilo_providers.errors import QuotaError

    waits: list[float] = []
    monkeypatch.setattr(run_tools, "pause", waits.append)
    read, rpc, _run, model = _reader(monkeypatch)

    def busy(request, budget, deadline=None):
        model.prompts.append(request.prompt)
        raise QuotaError("rate limited")

    model.generate_budgeted = busy
    assert read("https://en.wikipedia.org/wiki/Japan", "en.wikipedia.org") == "First. Second. Third."
    assert waits == list(run_tools.BROWSER_RETRY_WAITS) and len(model.prompts) == 1 + len(waits)
    assert rpc.calls[-(READ_SCROLLS + 3) :] == ["start", *["scroll"] * READ_SCROLLS, "extract", "end"]


def test_DEMO_BROWSER_a_busy_model_that_comes_back_carries_on(monkeypatch):
    from tilo_api import run_tools
    from tilo_providers.errors import RetryableError

    monkeypatch.setattr(run_tools, "pause", lambda _seconds: None)
    read, rpc, _run, model = _reader(monkeypatch, steps=[{"kind": "extract"}, {"kind": "done"}])
    real, failures = model.generate_budgeted, iter([RetryableError("503")])

    def flaky(request, budget, deadline=None):
        error = next(failures, None)
        if error:
            raise error
        return real(request, budget, deadline)

    model.generate_budgeted = flaky
    assert read("https://en.wikipedia.org/wiki/Japan", "en.wikipedia.org") == "First. Second. Third."
    assert rpc.calls == ["start", "extract", "end"]


# --- a run whose task names a site: each research unit uses that site in the browser first ---


def _site_reader(monkeypatch, steps=STEPS, *, typed=("wikipedia.org",), safety=None, upstream=()):
    from tilo_api import run_tools

    _read, rpc, run, model = _reader(monkeypatch, steps=steps, typed=typed)  # its browser and model, a fresh runner

    runner = object.__new__(run_tools.BoundRunRunner)
    runner.run_owner, runner.mode, runner.budget = run, "live", None
    runner.providers, runner.typed, runner.hosts = {"computer_use": model}, frozenset(typed), set(typed)
    runner.browser_lock, runner.safety, runner.frame_pages = threading.Lock(), safety or FakeSafety(), {}
    context = SimpleNamespace(agent_id="A_s2", upstream=tuple(upstream), skills=())
    unit = {"id": "U2", "district": "D1", "title": "Find the tallest building in India", "role": "specialist"}
    return runner.site_reading(unit, context), rpc, run, model, runner


def test_DEMO_BROWSER_a_named_site_is_searched_from_its_front_page_for_the_units_step(monkeypatch):
    items, rpc, _run, model, runner = _site_reader(monkeypatch)
    assert rpc.starts[0]["start_url"] == "https://wikipedia.org/"
    assert rpc.calls == ["start", "inspect", "type", "inspect", "click", "scroll", "extract", "end"]
    assert "Find the tallest building in India" in model.prompts[0]
    assert [(i.unit_id, i.title, i.text, i.screening) for i in items] == [
        ("browser", "What Tilo's browser read on wikipedia.org", "First. Second. Third.", "clean")
    ]
    assert runner.safety.screened == ["First. Second. Third."], "screened like a tool result before any model sees it"


def test_DEMO_BROWSER_what_the_screen_does_not_clear_never_reaches_the_unit(monkeypatch):
    items, _rpc, _run, _model, _runner = _site_reader(monkeypatch, safety=FakeSafety(flag="Second"))
    assert items == ()


def test_DEMO_BROWSER_no_named_site_no_model_or_private_data_means_no_session(monkeypatch):
    from tilo_harness.unit_prompt import UpstreamItem

    items, rpc, *_ = _site_reader(monkeypatch, typed=())
    assert items == () and rpc.calls == []
    private = UpstreamItem("U1", "Mail", "text", screening="clean", private=True)
    items, rpc, *_ = _site_reader(monkeypatch, upstream=(private,))
    assert items == () and rpc.calls == [], "WT-04: a unit holding the person's private data has no web egress"


def test_DEMO_BROWSER_a_unit_reads_the_web_unless_its_skill_says_otherwise():
    from tilo_api.run_tools import uses_web

    assert uses_web(SimpleNamespace(skills=()))
    assert uses_web(SimpleNamespace(skills=(SimpleNamespace(tools_allowed=("web_search", "fetch_url")),)))
    assert not uses_web(SimpleNamespace(skills=(SimpleNamespace(tools_allowed=("read_email",)),)))


def test_DEMO_BROWSER_one_browser_session_at_a_time_in_a_run(monkeypatch):
    _items, _rpc, _run, _model, runner = _site_reader(monkeypatch, typed=())
    inside: list[bool] = []
    runner.one_session(lambda: inside.append(runner.browser_lock.locked()))
    assert inside == [True] and not runner.browser_lock.locked()
