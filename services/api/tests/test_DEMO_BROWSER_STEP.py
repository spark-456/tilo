"""DEMO-BROWSER-STEP: one recorded event per fake browser action, without a paid call."""

import base64
import hashlib
import json
from types import SimpleNamespace

from tilo_browser.session import SessionRefused
from tilo_memory.artifacts import Scope


class FakeArtifacts:
    def __init__(self):
        self.saved = {}
        self.ident = ""

    def with_new_id(self, source):
        self.ident = source()
        return self

    def put(self, scope, new):
        ref = {"artifact_id": self.ident, "version": 1}
        self.saved[self.ident] = new.content
        return SimpleNamespace(ref=ref)

    def head(self, scope, ref):
        return SimpleNamespace(ref=ref) if ref["artifact_id"] in self.saved else None

    def read(self, scope, ref):
        return self.saved[ref["artifact_id"]]


class FakeRun:
    org_id, world_id, run_id, owner = "org_demo", "w_demo", "r_demo", "u_demo"

    def __init__(self):
        self.scope = Scope(self.org_id, self.world_id, self.owner)
        self.seams = SimpleNamespace(artifacts=FakeArtifacts())
        self.store = SimpleNamespace(browser_controls={})
        self.events = []
        self.charges = []

    def put(self, kind, actor, target, summary, data, **kwargs):
        self.events.append((kind, data))
        self.charges.append(kwargs.get("credits", 0))
        return {"id": f"e_{len(self.events)}"}


class FakeRpc:
    def __init__(self):
        self.calls = []

    @staticmethod
    def frame(session, step, kind, text=""):
        return {
            "session": session,
            "step": step,
            "kind": kind,
            "url": "https://example.org/search",
            "target_box": {"x": 10, "y": 20, "width": 100, "height": 30},
            "screenshot_artifact": {
                "mime_type": "image/png",
                "sha256": hashlib.sha256(b"PNG-frame").hexdigest(),
                "base64": base64.b64encode(b"PNG-frame").decode(),
            },
            "text": text,
            "masked": 1,
            "blocked": 0,
            "login_required": False,
        }

    def start(self, body):
        self.calls.append("start")
        return self.frame(body["session"], 0, "start")

    def act(self, session, body):
        self.calls.append(body["action"]["kind"])
        return self.frame(session, body["step"], body["action"]["kind"], "First. Second. Third.")

    def end(self, session):
        self.calls.append("end")
        return self.frame(session, 1, "end")


def test_DEMO_BROWSER_STEP_records_only_completed_actions_and_returns_extracted_text():
    from tilo_api.browser_step import BrowseStepExecutor

    run, rpc = FakeRun(), FakeRpc()
    actions = iter([{"kind": "extract"}, {"kind": "done"}])
    result = BrowseStepExecutor(run, rpc, lambda goal, frame, text: next(actions)).execute(
        unit={"id": "U1", "district": "D1"},
        agent="A_s1",
        building="B2",
        goal="Search example.org for X and summarize the top 3",
        hosts=["example.org"],
    )
    assert result.success
    assert "First. Second. Third." in result.outputs[0].content.decode()
    assert [kind for kind, _ in run.events] == ["browser.started", "browser.acted", "browser.stopped"]
    # A read has no point on the page, so it carries no cursor (owner, 21 Oct: never a decorative dot); pointer steps
    # carry theirs (test_DEMO_BROWSER_REAL_ACTIONS).
    assert "target_box" not in run.events[1][1]
    assert len(run.seams.artifacts.saved) == 2
    assert rpc.calls == ["start", "extract", "end"]


def test_DEMO_BROWSER_STEP_dispatches_only_the_pinned_browse_action():
    from tilo_api.run_tools import taught_browse_step

    run = SimpleNamespace(skill_plan=[{"tool": "web", "action": "browse_web", "text": "Find three results"}])
    assert taught_browse_step(run, {"id": "U1", "unit_type": "taught_step"})["text"] == "Find three results"
    assert taught_browse_step(run, {"id": "U2", "unit_type": "taught_step"}) is None
    assert taught_browse_step(run, {"id": "U1", "unit_type": "deliver"}) is None


def test_DEMO_BROWSER_STEP_owner_stop_closes_session_without_next_action():
    from tilo_api.browser_step import BrowseStepExecutor

    run, rpc = FakeRun(), FakeRpc()

    def propose(goal, frame, text):
        run.store.browser_controls[rpc.session] = "stop"
        return {"kind": "extract"}

    original = rpc.start

    def start(body):
        rpc.session = body["session"]
        return original(body)

    rpc.start = start
    result = BrowseStepExecutor(run, rpc, propose).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2", goal="Read", hosts=["example.org"]
    )
    assert not result.success
    assert rpc.calls == ["start", "extract", "end"]
    assert [kind for kind, _ in run.events] == [
        "browser.started",
        "browser.acted",
        "browser.controlled",
        "browser.stopped",
    ]
    assert run.events[-1][1]["steps"] == 1


def test_DEMO_BROWSER_STEP_unavailable_service_has_plain_failure():
    from tilo_api.browser_step import BrowseStepExecutor

    class OfflineRpc:
        def start(self, body):
            raise SessionRefused("browser_unavailable", 503)

    result = BrowseStepExecutor(FakeRun(), OfflineRpc(), lambda goal, frame, text: {}).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2", goal="Read", hosts=["example.org"]
    )
    assert not result.success
    assert "unavailable" in result.reason


def test_DEMO_BROWSER_STEP_records_only_actual_model_charges():
    from tilo_api.browser_step import BrowseStepExecutor

    run = FakeRun()
    proposals = iter([({"kind": "extract"}, 0.3), ({"kind": "done"}, 0.1)])
    result = BrowseStepExecutor(run, FakeRpc(), lambda goal, frame, text: next(proposals)).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2", goal="Read", hosts=["example.org"]
    )
    assert result.success
    assert run.charges == [0, 0.3, 0.1]


def test_DEMO_BROWSER_STEP_wikipedia_search_demo_records_navigation_then_read():
    from tilo_api.browser_step import BrowseStepExecutor
    from tilo_providers.fake_browser import FakeBrowserProvider
    from tilo_providers.interfaces import GenerateRequest

    run, rpc, model = FakeRun(), FakeRpc(), FakeBrowserProvider()

    def propose(goal, frame, extracted):
        return json.loads(
            model.generate(GenerateRequest(prompt=f"Goal: {goal}\nExtracted page text: {extracted}")).text
        )

    result = BrowseStepExecutor(run, rpc, propose).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2",
        goal="Search https://en.wikipedia.org for Ada Lovelace and summarize the top 3",
        hosts=["en.wikipedia.org"],
    )
    assert result.success
    assert rpc.calls == ["start", "navigate", "extract", "end"]
    assert [e[0] for e in run.events] == ["browser.started", "browser.acted", "browser.acted", "browser.stopped"]
    assert result.outputs[0].content == b"First. Second. Third."


def test_DEMO_BROWSER_STEP_lost_service_records_a_valid_safe_stop():
    from tilo_api.browser_step import BrowseStepExecutor

    class LostRpc(FakeRpc):
        def act(self, session, body):
            raise SessionRefused("session_lost", 404)

        def end(self, session):
            raise SessionRefused("session_lost", 404)

    run = FakeRun()
    result = BrowseStepExecutor(run, LostRpc(), lambda goal, frame, text: {"kind": "extract"}).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2", goal="Read", hosts=["example.org"]
    )
    assert not result.success
    assert run.events[1][1]["reason"] == "engine_error"
    assert run.events[-1][1]["outcome"] == "session_lost"


def test_DEMO_BROWSER_STEP_model_prompt_uses_contract_point_grid_and_safe_actions():
    from tilo_api.run_tools import browser_proposal_prompt

    prompt = browser_proposal_prompt("Search the page", "Three results")
    assert "0–999" in prompt or "0-999" in prompt
    assert '{"kind":"click","at":{"x":500,"y":500}}' in prompt
    assert '{"kind":"type","at":{"x":500,"y":500},"text":"query","submit":false}' in prompt
    assert "Never type passwords" in prompt
    assert "Never submit" in prompt


def test_DEMO_BROWSER_STEP_proposal_names_approved_hosts():
    from tilo_api.browser_step import BrowseStepExecutor

    seen = []

    def propose(goal, frame, extracted):
        seen.append(goal)
        return {"kind": "extract"} if len(seen) == 1 else {"kind": "done"}

    result = BrowseStepExecutor(FakeRun(), FakeRpc(), propose).execute(
        unit={"id": "U1", "district": "D1"}, agent="A_s1", building="B2", goal="Read", hosts=["example.org"]
    )
    assert result.success
    assert "Approved hosts: example.org" in seen[0]
