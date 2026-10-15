from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from _browser_lib import FakeWeb, button, doc, textbox
from tilo_browser.skill_replay import (
    JsonlRecordingStore,
    RecordedEvent,
    RecordingSession,
    compile_recording,
    replay,
)


class FakeRouter:
    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.requests = []

    def generate(self, role: str, request: Any) -> Any:
        self.requests.append((role, request))
        body = self.replies.pop(0)
        return SimpleNamespace(
            outcome="ok",
            response=SimpleNamespace(text=json.dumps(body)),
        )


class ApprovalGate:
    def __init__(self, approved: bool) -> None:
        self.approved = approved
        self.calls: list[dict[str, Any]] = []

    def execute(self, *, perform: Any, **action: Any) -> Any:
        self.calls.append(action)
        if not self.approved:
            raise PermissionError("person approval required")
        return perform()


def test_SKILL_REPLAY_recording_masks_secure_fields_and_is_owner_scoped(tmp_path: Path) -> None:
    store = JsonlRecordingStore(tmp_path)
    session = RecordingSession(store, owner="person_1", recording_id="rec_1")
    secret = "pw-" + "A7kP9xQ2mN4b"
    event = session.record(
        kind="type",
        url="https://ledgerly.example/search",
        target="Password",
        selector="#password",
        value=secret,
        secure_field=True,
    )

    assert event.value is None
    assert event.selector is None
    assert event.target == "secure field"
    persisted = (tmp_path / "person_1" / "rec_1.jsonl").read_text(encoding="utf-8")
    assert secret not in persisted
    assert store.read("person_1", "rec_1") == [event]
    assert store.read("person_2", "rec_1") == []
    with pytest.raises(ValueError):
        store.append("person_1", "rec_1", event)


def test_SKILL_REPLAY_replays_against_current_accessible_targets_and_verifies(make_rig) -> None:
    web = FakeWeb()
    web.add(
        "https://ledgerly.example/search",
        title="Product search",
        text="Search the catalog",
        tree=doc(textbox("query", "Search products"), button("open-growth", "Open Growth")),
        links={"open-growth": "https://ledgerly.example/growth"},
    )
    web.add(
        "https://ledgerly.example/growth",
        title="Growth plan",
        text="Growth plan selected. API access included.",
        tree=doc(button("save", "View details")),
    )
    rig = make_rig(web, allow=("ledgerly.example",))
    events = [
        RecordedEvent.create(sequence=1, kind="navigate", url="https://ledgerly.example/search"),
        RecordedEvent.create(
            sequence=2,
            kind="type",
            url="https://ledgerly.example/search",
            target="Search products",
            selector="#old-query-id",
            value="Growth",
        ),
        RecordedEvent.create(
            sequence=3,
            kind="click",
            url="https://ledgerly.example/search",
            target="Growth plan",
            selector="#old-growth-id",
        ),
    ]
    router = FakeRouter(
        [
            {
                "steps": [
                    {"sequence": 1, "intent": "Open product search", "expected": "Product search"},
                    {"sequence": 2, "intent": "Search for Growth", "expected": ""},
                    {"sequence": 3, "intent": "Open the Growth plan", "expected": "Growth plan selected"},
                ]
            },
            {"sequence": 1, "target_ref": None},
            {"sequence": 2, "target_ref": "query"},
            {"sequence": 3, "target_ref": "open-growth"},
        ]
    )
    steps = compile_recording(events, router, role="specialist")
    gate = ApprovalGate(True)

    completed = replay(steps, rig.worker, router, role="specialist", gate=gate)

    assert [step["sequence"] for step in completed] == [1, 2, 3]
    assert rig.driver.typed == [("query", "Growth")]
    assert rig.driver.clicked == ["open-growth"]
    assert completed[-1]["url"].endswith("/growth")
    assert gate.calls == [
        {
            "action": "click",
            "url": "https://ledgerly.example/search",
            "target": "button Open Growth",
            "destination": None,
        }
    ]
    assert all(role == "specialist" for role, _ in router.requests)
    assert len(router.requests) == 4


def test_SKILL_REPLAY_requires_person_approval_before_submit(make_rig) -> None:
    web = FakeWeb()
    web.add(
        "https://ledgerly.example/quote",
        title="Quote form",
        text="Review your quote",
        tree=doc(button("submit", "Get quote")),
    )
    rig = make_rig(web, allow=("ledgerly.example",))
    step = compile_recording(
        [
            RecordedEvent.create(
                sequence=1,
                kind="submit",
                url="https://ledgerly.example/quote",
                target="Get quote",
                selector="#submit",
            )
        ],
        FakeRouter([{"steps": [{"sequence": 1, "intent": "Submit the reviewed quote", "expected": ""}]}]),
        role="specialist",
    )
    gate = ApprovalGate(False)
    rig.worker.navigate("https://ledgerly.example/quote")

    with pytest.raises(PermissionError, match="person approval"):
        replay(step, rig.worker, FakeRouter([{"sequence": 1, "target_ref": "submit"}]), role="specialist", gate=gate)

    assert gate.calls == [
        {
            "action": "submit",
            "url": "https://ledgerly.example/quote",
            "target": "button Get quote",
            "destination": None,
        }
    ]
    assert rig.driver.clicked == []


def test_SKILL_REPLAY_requires_person_approval_before_download_and_shows_destination(make_rig) -> None:
    web = FakeWeb()
    web.add("https://ledgerly.example/report", title="Report", tree=doc(button("download", "Download PDF")))
    rig = make_rig(web, allow=("ledgerly.example",))
    destination = str(Path("chosen-folder") / "report.pdf")
    compile_router = FakeRouter([{"steps": [{"sequence": 1, "intent": "Download the report", "expected": ""}]}])
    event = RecordedEvent.create(
        sequence=1,
        kind="download",
        url="https://ledgerly.example/report",
        target="Download PDF",
        selector="#download",
        destination=destination,
    )
    steps = compile_recording([event], compile_router, role="specialist")
    gate = ApprovalGate(False)
    rig.worker.navigate("https://ledgerly.example/report")
    chooser = FakeRouter([{"sequence": 1, "target_ref": "download"}])

    with pytest.raises(PermissionError, match="person approval"):
        replay(steps, rig.worker, chooser, role="specialist", gate=gate)

    assert gate.calls == [
        {
            "action": "download",
            "url": "https://ledgerly.example/report",
            "target": "button Download PDF",
            "destination": destination,
        }
    ]
    assert len(chooser.requests) == 1


def test_SKILL_REPLAY_rejects_model_target_outside_current_page(make_rig) -> None:
    web = FakeWeb()
    web.add("https://ledgerly.example/search", title="Search", tree=doc(button("right", "Right target")))
    rig = make_rig(web, allow=("ledgerly.example",))
    event = RecordedEvent.create(
        sequence=1, kind="click", url="https://ledgerly.example/search", target="Target", selector="#target"
    )
    compile_router = FakeRouter([{"steps": [{"sequence": 1, "intent": "Select target", "expected": ""}]}])
    steps = compile_recording([event], compile_router, role="specialist")
    chooser = FakeRouter([{"sequence": 1, "target_ref": "not-on-page"}])

    with pytest.raises(RuntimeError, match="no safe target"):
        replay(steps, rig.worker, chooser, role="specialist", gate=ApprovalGate(True))

    assert rig.driver.clicked == []


def test_SKILL_REPLAY_replays_scroll_and_sign_in_pause_drops_page_content(make_rig) -> None:
    web = FakeWeb()
    web.add(
        "https://ledgerly.example/search",
        title="Search",
        tree=doc(button("results", "Search results")),
    )
    rig = make_rig(web, allow=("ledgerly.example",))
    rig.worker.navigate("https://ledgerly.example/search")
    event = RecordedEvent.create(
        sequence=1, kind="scroll", url="https://ledgerly.example/search", target="Search results"
    )
    steps = compile_recording(
        [event],
        FakeRouter([{"steps": [{"sequence": 1, "intent": "Bring results into view", "expected": ""}]}]),
        role="specialist",
    )

    replay(
        steps,
        rig.worker,
        FakeRouter([{"sequence": 1, "target_ref": "results"}]),
        role="specialist",
        gate=ApprovalGate(False),
    )
    pause = RecordedEvent.create(
        sequence=2,
        kind="sign_in_pause",
        url="https://ledgerly.example/login",
        target="credentials",
        selector="#password",
        value="private-value",
        observation="password private-value",
    )

    assert rig.driver.scrolled == ["results"]
    assert pause.target == "sign-in required"
    assert pause.selector is None and pause.value is None and pause.observation == ""
