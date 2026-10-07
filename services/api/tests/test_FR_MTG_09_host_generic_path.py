"""FR-MTG-09 (MTG09-b, API half), the Opus security review's requirement: `create_meeting_event` must stay OFF the
generic planned-unit gate path, OR the draft must be re-validated in the adapter (MH-02, MH-03, the meeting title
pattern). A planned unit is whatever a Director drafted: its item is a model's output and its recipients come from the
generic resolver, so nothing the host route checks (an owner, a same-org attendee list, a window) holds for it.

The test registers the real `MeetingHostAdapter` (fake broker, fake calendar) in the generic run's adapter map, which is
the worst case: a composition root that wires every adapter into every run. Then a unit plans `create_meeting_event`
with an item that LOOKS like the draft (`kind: meeting_event`, the owner's id, attendees equal to the resolver's
recipients) but breaks one of the rules. Whatever the builder chose (the plan is refused, the gate refuses the action,
or the adapter re-validates), the run ends failed and the calendar sees no request: no insert, no invitation.
"""

from __future__ import annotations

import copy
import json

import pytest
from _clint1_lib import FLOW_USER, seam
from _clint2_lib import (
    ScriptedRunner,
    base_plan,
    build_run_flow,
    covering_policy,
    wait_for,
)
from _mtg09b_lib import (
    ACTION_TYPE,
    ATTACKER,
    CONNECTOR_ID,
    IST,
    T_END,
    T_START,
    FakeBroker,
    FakeHostCalendar,
    block_network,
)
from tilo_connectors.adapters.meeting_host import MeetingHostAdapter
from tilo_connectors.meeting_host import InMemoryReceiptStore
from tilo_connectors.registry import load_registry

NOW = "2026-10-06T10:00:00.000Z"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


class _StoreSource:
    """The adapter's ArtifactSource over the run's artifact store: the hash-checked read, as the parsed JSON."""

    def __init__(self, store, scope_of) -> None:
        self._store, self._scope_of = store, scope_of

    def get(self, artifact_id: str, version: int) -> dict:
        raw = self._store.read(self._scope_of(), {"artifact_id": artifact_id, "version": version})
        return json.loads(raw)


class _DraftRunner(ScriptedRunner):
    """Every unit succeeds as usual, except U4, whose one output is the JSON the attack needs."""

    def __init__(self, timeline: list[str], content: bytes) -> None:
        super().__init__(timeline)
        self.content = content

    async def run(self, unit, context):
        if unit["id"] != "U4":
            return await super().run(unit, context)
        from tilo_harness.executor import UnitOutcome, UnitOutput  # noqa: PLC0415

        self.ran.append("U4")
        output = UnitOutput(media_type="application/json", content=self.content)
        return UnitOutcome(success=True, summary="Drafted the invitation.", outputs=(output,))


def _host_plan(approach_id: str, budget_cap: float) -> dict:
    plan = base_plan(approach_id, budget_cap)
    plan["units"][3]["connectors"] = [CONNECTOR_ID]
    plan["units"][3]["actions"] = [ACTION_TYPE]
    plan["gates"][0]["action_type"] = ACTION_TYPE
    return plan


def _draft(**over) -> dict:
    recipients = over.pop("attendees", ["colleague@example.com"])
    draft = {
        "v": "1.0",
        "kind": "meeting_event",
        "meeting_id": "mt_planned",
        "owner": FLOW_USER,
        "title": "Weekly sync",
        "start": T_START,
        "end": T_END,
        "time_zone": IST,
        "attendees": recipients,
        "conference": "hangoutsMeet",
        "send_updates": "all",
        "guests_can_invite_others": False,
        "guests_can_modify": False,
        "guests_can_see_other_guests": False,
    }
    draft.update(over)
    return draft


CASES = {
    "MH-02-three-hours": _draft(end="2030-01-15T12:00:00.000Z"),
    "MH-02-end-before-start": _draft(end="2030-01-15T08:00:00.000Z"),
    "meeting-title-pattern-a-link": _draft(title="Join at https://evil.example/x"),
    "MH-03-an-outsider-who-is-no-person-of-the-org": _draft(attendees=[ATTACKER]),
}


def _wire(rf, draft: dict) -> tuple[FakeHostCalendar, FakeBroker]:
    from tilo_api import deps  # noqa: PLC0415

    calendar, broker = FakeHostCalendar(), FakeBroker()
    root = rf.flow.app  # the same app the run flow installed its seams on
    registry = load_registry(deps._REPO_ROOT / "config" / "connectors.yaml")  # noqa: SLF001
    rf.registry = registry
    adapter = MeetingHostAdapter(
        declaration=registry.get(CONNECTOR_ID),
        broker=broker,
        transport=calendar,
        artifacts=_StoreSource(rf.rig.store, lambda: rf.scope()),
        owner_of=lambda world_id: FLOW_USER,
        receipts=InMemoryReceiptStore(),
        clock=lambda: NOW,
        emit=lambda part: None,
        sleep=lambda seconds: None,
    )
    root.dependency_overrides[seam(deps, "get_connector_adapters")] = lambda: {CONNECTOR_ID: adapter}
    rf.runner = _DraftRunner(rf.timeline, json.dumps(draft, sort_keys=True).encode())
    recipients = list(draft["attendees"])

    def compile_plan(*, brief, approach, budget_cap, context=None):
        rf.compile_calls.append({"cap": budget_cap})
        rf.last_plan = _host_plan(approach["id"], budget_cap)
        return copy.deepcopy(rf.last_plan)

    def resolve(*, unit, action_type, item, brief):
        return {"destination": "primary", "recipients": recipients, "known_recipients": []}

    rf.compile_plan, rf.resolve_action = compile_plan, resolve
    policy = covering_policy(FLOW_USER)
    policy |= {"id": "pol_host_ask", "action_type": ACTION_TYPE}
    policy["scope"] = {**policy["scope"], "connectors": [CONNECTOR_ID]}
    rf.store.policies["pol_host_ask"] = policy
    return calendar, broker


def _run_to_the_end(rf) -> list:
    """Start, approve the task, approve every gate card, and wait for the run to end one way or the other."""
    rf.start()
    assert rf.approve().status_code == 200
    answered: set[str] = set()

    def ended():
        cards = rf.cards()
        if cards.status_code == 200:
            for card in cards.json():
                if card["id"] in answered:
                    continue
                if card["kind"] == "gate":
                    answered.add(card["id"])
                    rf.answer(card["id"], "approve")
                elif card["kind"] == "needs_you":  # a T3 action always asks "go ahead?" first (must-ask): o2 goes
                    answered.add(card["id"])
                    rf.answer(card["id"], "o2")
        return rf.events("world.failed") or rf.events("world.completed")

    try:
        return wait_for(ended, timeout=25, what="the run to end")
    except AssertionError as exc:
        cards = rf.cards().json() if rf.cards().status_code == 200 else []
        seen = [e["type"] for e in rf.events()]
        raise AssertionError(f"{exc}; events {seen}; cards {[(c['kind'], c['rung']) for c in cards]}") from None


@pytest.mark.parametrize("draft", list(CASES.values()), ids=list(CASES))
def test_FR_MTG_09_a_generic_planned_unit_cannot_bypass_the_host_validation(repo_root, draft):
    rf = build_run_flow(repo_root)
    try:
        calendar, broker = _wire(rf, draft)
        ended = _run_to_the_end(rf)
        assert calendar.requests == [], "no insert reached the calendar for a draft that breaks a host rule"
        assert calendar.invitations == {} and calendar.events == {}, "no event, no invitation"
        assert rf.events("data.transfer") == [], "nothing crossed the bridge"
        assert not [e for e in rf.outbox_store.all_entries() if e["state"] == "sent"]
        assert ended[0]["type"] == "world.failed", "the unit's invitation was refused, so the run stopped"
    finally:
        rf.close()
