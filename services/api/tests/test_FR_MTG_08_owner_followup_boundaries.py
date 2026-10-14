"""Offline boundary coverage: explicit mode, one shared budget and guarded publication."""

import json
from types import SimpleNamespace

import pytest
from _mtg08_lib import answer
from _ppl11a_lib import OWNER
from _sec16_lib import make_caps
from test_FR_MTG_08_owner_followup import followup, replace, run  # noqa: F401
from tilo_api import deps, team_access
from tilo_api.meeting_followup import draft_owner_followup
from tilo_api.people_writes import Refusal
from tilo_memory.artifacts import Scope
from tilo_providers.safety import FakeSafetyProvider


@pytest.mark.parametrize("demo", ["none", "principal", "request"])
def test_FR_MTG_08_owner_explicit_mode_and_both_demo_sources(followup, monkeypatch, demo):  # noqa: F811
    c, modes = followup, []
    router = deps.router_for_mode("replay")
    monkeypatch.setattr(deps, "get_work_mode", lambda *args: "live" if demo != "none" else "replay")
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: modes.append(("router", mode)) or router)
    monkeypatch.setattr(deps, "get_safety", lambda mode: modes.append(("safety", mode)) or FakeSafetyProvider())
    c.request.state.demo_session = demo == "request"
    card = draft_owner_followup(
        c.request,
        c.writer,
        c.rig.event_store,
        c.rig.artifacts,
        "mt_q4_plan",
        principal=deps.Principal(OWNER, "owner", demo_session=demo == "principal"),
        switches=c.switches,
        budget=2,
        events=c.rig.events,
        drafts=c.drafts,
        autopilot_factory=c.factory,
        recipients=["u_priya"],
        allowance=c.allowance,
        allowance_cap=c.allowance_cap,
    )
    assert card.tier == "T3" and card.level == "L1"
    assert modes == [("router", "replay"), ("safety", "replay")]
    assert len(c.calls) == 1 and c.calls[0][2] == 2
    assert c.switches.ledger.spent_minor(OWNER) == 0
    assert c.line.entries() == [] and c.line.api.sent == []


def two_open_items(c):
    scope = Scope(c.rig.org, c.meeting["world_id"], OWNER)
    doc = json.loads(c.rig.artifacts.read(scope, c.meeting["minutes"]))
    second = next(item for item in doc["action_items"] if item["work_item_id"] == "wi_launch_note")
    second["state"] = "verified"
    ref = c.rig.put_doc(scope, "art_two_open_items", doc, created_at=doc["generated_at"])
    replace(c, "meetings", "mt_q4_plan", minutes=ref.doc["artifact"])
    replace(c, "work_items", "wi_launch_note", status="open", confirmed_by=c.meeting["minutes_confirmed_by"])


@pytest.mark.parametrize("flip", [False, True])
def test_FR_MTG_08_owner_fake_live_multi_nudge_charges_each_call_and_rereads_switch(
    followup,  # noqa: F811
    monkeypatch,
    flip,
):  # noqa: F811
    c, safety_calls, modes = followup, [], []
    two_open_items(c)
    caps = make_caps()
    c.request.app.dependency_overrides[deps.get_spend_caps] = lambda: caps
    monkeypatch.setattr(team_access, "user_cap_minor", lambda *args: caps.uid_lifetime_minor)
    router = deps.router_for_mode("replay")
    monkeypatch.setattr(deps, "get_work_mode", lambda *args: "live")

    class Router:
        def generate(self, role, request, *, budget):
            result = router.generate(role, request, budget=budget)
            result.budget = 1
            return result

    class Safety:
        def check(self, text):
            safety_calls.append(text)
            # First nudge's output screen is its final provider call. The next
            # nudge must reread the switch before screening or generating.
            if flip and len(safety_calls) == 2:
                c.switches.flags.set("replay_only", True, reason="offline test")
            return {"flagged": False}

    monkeypatch.setattr(deps, "router_for_mode", lambda mode: modes.append(("router", mode)) or Router())
    monkeypatch.setattr(deps, "get_safety", lambda mode: modes.append(("safety", mode)) or Safety())
    cards = run(c, None)
    expected = 1 if flip else 2
    assert len(cards) == expected and len(c.calls) == expected and len(safety_calls) == 2 * expected
    assert c.switches.ledger.spent_minor(OWNER) == 3 * expected * caps.unit_reserve_minor
    assert modes == [("router", "live"), ("safety", "live")]
    assert c.line.entries() == [] and c.line.api.sent == []


@pytest.mark.parametrize("remaining", [(1.25, 0.5), (0, 0), (99, 1)])
def test_FR_MTG_08_owner_multiple_nudges_share_nonincreasing_budget(followup, monkeypatch, remaining):  # noqa: F811
    c, budgets = followup, []
    two_open_items(c)

    class Router:
        def generate(self, role, request, *, budget):
            budgets.append(budget)
            body = request.prompt.split("<<<ITEM\n", 1)[1].split("\nITEM>>>")[0]
            return SimpleNamespace(
                response=SimpleNamespace(text=answer(body), tool_calls=()),
                outcome="ok",
                # Real Router returns credits left after its estimate, never more than sent.
                # Invalid/inflated raw usage is pinned separately by the allowance tests.
                budget=min(budget, remaining[len(budgets) - 1]),
            )

    monkeypatch.setattr(deps, "router_for_mode", lambda mode: Router())
    cards = run(c, None)
    if remaining[0] == 0:
        assert budgets == [2] and len(cards) == 1
    else:
        assert budgets == [2, min(2, remaining[0])] and len(cards) == 2
        assert {card.to for card in cards} == {("priya@example.com",), ("sam@example.com",)}
    assert all(card.tier == "T3" and card.level == "L1" for card in cards)
    assert c.line.entries() == [] and c.line.api.sent == []


def remove_minutes(c, target):
    artifact_id = c.meeting["minutes"]["artifact_id"]
    backend = c.rig.meta if target == "metadata" else c.rig.blobs
    keys = backend.paths("") if target == "metadata" else backend.keys("")
    matching = [key for key in keys if artifact_id in key]
    assert matching
    for key in matching:
        backend.delete(key)


@pytest.mark.parametrize("target", ["metadata", "blob"])
@pytest.mark.parametrize("when", ["preflight", "generation", "publication"])
def test_FR_MTG_08_owner_missing_minutes_never_publish_draft_or_gate(
    followup,  # noqa: F811
    monkeypatch,
    target,
    when,
):  # noqa: F811
    c = followup

    def mutate():
        remove_minutes(c, target)

    if when == "preflight":
        mutate()
    elif when == "generation":
        c.during.append(mutate)
    else:
        original = c.drafts.create

        def create(uid, key, doc):
            result = original(uid, key, doc)
            if doc.get("draft"):
                mutate()
            return result

        monkeypatch.setattr(c.drafts, "create", create)
    with pytest.raises(Refusal) as refused:
        run(c)
    assert refused.value.status_code == 409
    assert len(c.calls) == (0 if when == "preflight" else 1)
    assert c.rig.events.calls == []
    assert c.line.bench.cards.dump() == "{}" and c.line.entries() == [] and c.line.api.sent == []


def test_FR_MTG_08_owner_changed_minutes_pointer_blocks_publication(followup, monkeypatch):  # noqa: F811
    c = followup
    scope = Scope(c.rig.org, c.meeting["world_id"], OWNER)
    doc = json.loads(c.rig.artifacts.read(scope, c.meeting["minutes"]))
    doc["summary"][0]["text"] = "The confirmed summary changed."
    ref = c.rig.put_doc(scope, "art_changed_minutes", doc, created_at=doc["generated_at"])
    original = c.drafts.create

    def create(uid, key, value):
        result = original(uid, key, value)
        if value.get("draft"):
            replace(c, "meetings", "mt_q4_plan", minutes=ref.doc["artifact"])
        return result

    monkeypatch.setattr(c.drafts, "create", create)
    with pytest.raises(Refusal) as refused:
        run(c)
    assert refused.value.status_code == 409 and len(c.calls) == 1
    assert c.rig.events.calls == []
    assert c.line.bench.cards.dump() == "{}" and c.line.entries() == [] and c.line.api.sent == []


def test_FR_MTG_08_owner_failed_artifact_publication_retry_announces_before_approval(followup, monkeypatch):  # noqa: F811
    c, failures = followup, []
    original = c.rig.events.append

    def append(world, part):
        if part["type"] == "artifact.created" and not failures:
            failures.append(True)
            raise RuntimeError("offline artifact publication failure")
        return original(world, part)

    monkeypatch.setattr(c.rig.events, "append", append)
    with pytest.raises(RuntimeError):
        run(c)
    assert c.rig.events.calls == [] and c.line.bench.cards.dump() == "{}"
    card = run(c)
    assert card.tier == "T3" and len(c.calls) == 1
    types = [call.part["type"] for call in c.rig.events.calls]
    assert types[0] == "artifact.created" and "approval.requested" in types[1:]
    events = list(c.rig.event_store.events[c.meeting["world_id"]])
    assert [event["type"] for event in events] == ["artifact.created", "approval.requested"]
    artifact = events[0]["data"]["artifact"]
    assert run(c).card_id == card.card_id and len(c.calls) == 1
    assert c.rig.event_store.events[c.meeting["world_id"]] == events
    assert c.rig.event_store.events[c.meeting["world_id"]][0]["data"]["artifact"] == artifact
    assert c.line.entries() == [] and c.line.api.sent == []
