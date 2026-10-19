"""DEMO-BROWSER-STEP: one recorded event per fake browser action, without a paid call."""

import base64
import hashlib
from types import SimpleNamespace

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
        self.events = []

    def put(self, kind, actor, target, summary, data, **kwargs):
        self.events.append((kind, data))
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
    assert run.events[1][1]["target_box"] == {"x": 10, "y": 20, "width": 100, "height": 30}
    assert len(run.seams.artifacts.saved) == 2
    assert rpc.calls == ["start", "extract", "end"]


def test_DEMO_BROWSER_STEP_dispatches_only_the_pinned_browse_action():
    from tilo_api.run_tools import taught_browse_step

    run = SimpleNamespace(skill_plan=[{"tool": "web", "action": "browse_web", "text": "Find three results"}])
    assert taught_browse_step(run, {"id": "U1", "unit_type": "taught_step"})["text"] == "Find three results"
    assert taught_browse_step(run, {"id": "U2", "unit_type": "taught_step"}) is None
    assert taught_browse_step(run, {"id": "U1", "unit_type": "deliver"}) is None
