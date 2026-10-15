from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from _browser_lib import FakeWeb, button, doc, textbox
from tilo_browser.skill_recording import JsonlRecordingStore, RecordedEvent, RecordingSession
from tilo_browser.skill_replay import ReplayNeedsHelp, compile_recording, replay


class FakeRouter:
    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies, self.calls = list(replies), 0

    def generate(self, role: str, request: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(outcome="ok", response=SimpleNamespace(text=json.dumps(self.replies.pop(0))))


class Gate:
    def __init__(self, approved: bool) -> None:
        self.approved, self.actions = approved, []

    def execute(self, *, action: str, url: str, target: str, destination: str | None, perform: Any) -> Any:
        self.actions.append((action, url, target, destination))
        if not self.approved:
            raise PermissionError("person approval required")
        return perform()


def test_SKILL_REPLAY_adapts_targets_scrolls_and_verifies(make_rig, tmp_path) -> None:
    web = FakeWeb()
    web.add(
        "https://ledgerly.example/search",
        title="Product search",
        text="Search catalog",
        tree=doc(textbox("query", "Search products"), button("more", "Search results"), button("open", "Open Growth")),
        links={"open": "https://ledgerly.example/growth"},
    )
    web.add(
        "https://ledgerly.example/growth",
        title="Growth",
        text="Growth plan selected",
        tree=doc(button("info", "Details")),
    )
    record = make_rig(web, allow=("ledgerly.example",))
    session = RecordingSession(JsonlRecordingStore(tmp_path), record.worker, owner="owner", recording_id="r1")
    session.record(kind="navigate", url="https://ledgerly.example/search")
    record.worker.navigate("https://ledgerly.example/search")
    session.record(
        kind="type",
        url="https://ledgerly.example/search",
        target="Search products",
        selector="#query",
        value="Growth",
    )
    session.record(kind="scroll", url="https://ledgerly.example/search", target="Search results")
    session.record(kind="click", url="https://ledgerly.example/search", target="Growth plan", selector="#old-link")
    events = JsonlRecordingStore(tmp_path).read("owner", "r1")
    model = FakeRouter(
        {
            "steps": [
                {"sequence": 1, "intent": "Open search", "expected": "Product search"},
                {"sequence": 2, "intent": "Search Growth", "expected": ""},
                {"sequence": 3, "intent": "Bring results into view", "expected": ""},
                {"sequence": 4, "intent": "Open Growth plan", "expected": "Growth plan selected"},
            ]
        },
        {"sequence": 1, "target_ref": None},
        {"sequence": 2, "target_ref": "query"},
        {"sequence": 3, "target_ref": "more"},
        {"sequence": 4, "target_ref": "open"},
    )
    steps = compile_recording(events, model, role="specialist")
    run = make_rig(web, allow=("ledgerly.example",))

    result = replay(steps, run.worker, model, role="specialist", gate=Gate(True))

    assert [row["sequence"] for row in result] == [1, 2, 3, 4]
    assert run.driver.typed == [("query", "Growth")]
    assert run.driver.scrolled == ["more"] and run.driver.clicked == ["open"]
    assert result[-1]["url"].endswith("/growth") and model.calls == 5


@pytest.mark.parametrize("kind,ref,destination", [("submit", "send", None), ("download", "file", "chosen/report.pdf")])
def test_SKILL_REPLAY_side_effects_need_gate(kind, ref, destination, make_rig) -> None:
    url = "https://ledgerly.example/report"
    web = FakeWeb()
    web.add(url, title="Report", tree=doc(button(ref, "Continue")))
    rig = make_rig(web, allow=("ledgerly.example",))
    rig.worker.navigate(url)
    event = RecordedEvent.create(
        sequence=1, kind=kind, url=url, target="Continue", selector=f"#{ref}", destination=destination
    )
    steps = compile_recording(
        [event], FakeRouter({"steps": [{"sequence": 1, "intent": "Continue", "expected": ""}]}), role="specialist"
    )
    gate = Gate(False)

    with pytest.raises(PermissionError, match="person approval"):
        replay(steps, rig.worker, FakeRouter({"sequence": 1, "target_ref": ref}), role="specialist", gate=gate)

    assert gate.actions == [(kind, url, "button Continue", destination)]
    assert rig.driver.clicked == [] and rig.driver.downloaded == []


def test_SKILL_REPLAY_refuses_target_not_in_current_tree(make_rig) -> None:
    url = "https://ledgerly.example/search"
    rig = make_rig(FakeWeb(), allow=("ledgerly.example",))
    event = RecordedEvent.create(sequence=1, kind="click", url=url, target="Missing")
    steps = compile_recording(
        [event], FakeRouter({"steps": [{"sequence": 1, "intent": "Click", "expected": ""}]}), role="specialist"
    )

    with pytest.raises(ReplayNeedsHelp, match="no safe target"):
        replay(
            steps,
            rig.worker,
            FakeRouter({"sequence": 1, "target_ref": "not-present"}),
            role="specialist",
            gate=Gate(True),
        )
