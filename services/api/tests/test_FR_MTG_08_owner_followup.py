"""Confirmed minutes use directory recipients and real offline approval/outbox plumbing."""

from types import SimpleNamespace

import pytest
from _chn_wire1_lib import make_wire_line, real_check_is_live
from _mtg08_lib import MemoryDraftStore, answer
from _ppl11a_lib import OWNER, PRIYA, SAM
from _ppl11c_lib import meeting_rig
from _sec16_lib import make_caps, make_ledger
from starlette.requests import Request
from tilo_api import deps, spend
from tilo_api.people_writes import Refusal, Writer
from tilo_channels.autopilot import Autopilot
from tilo_metering.flags import InMemoryFlagStore
from tilo_people.stores import meeting_tombstone
from tilo_providers.safety import FakeSafetyProvider


@pytest.fixture
def followup(people_rig, monkeypatch):
    rig = meeting_rig(people_rig)
    writer = Writer(rig.stores, rig.org, OWNER, rig.clock, rig.redactor)
    meeting = rig.stored("meetings", "mt_q4_plan")
    rig.event_store.worlds[meeting["world_id"]] = deps.WorldRecord(OWNER, {}, run_id="r_meeting_q4_plan_1")
    request = Request({"type": "http", "app": SimpleNamespace(dependency_overrides={})})
    request.state.uid = OWNER
    line, drafts = make_wire_line(), MemoryDraftStore()
    calls, during = [], []

    class Router:
        def generate(self, role, request, *, budget):
            calls.append((role, request, budget))
            for mutate in during:
                mutate()
            body = (
                request.prompt.split("<<<ITEM\n", 1)[1].split("\nITEM>>>")[0]
                if "<<<ITEM" in request.prompt
                else "The rate sheet goes to Acme this week."
            )
            return SimpleNamespace(response=SimpleNamespace(text=answer(body), tool_calls=()), outcome="ok", budget=0)

    monkeypatch.setattr(deps, "get_work_mode", lambda *args: "replay")
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: Router())
    monkeypatch.setattr(deps, "get_safety", lambda mode: FakeSafetyProvider())
    switches = spend.Switches(InMemoryFlagStore(), make_ledger(make_caps()))

    def factory(world_id, run_id, owner, emit):
        b = line.bench
        return Autopilot(
            drafter=b.rig.svc, reader=b.rig.reader, contacts=b.contacts, policy=b.policy,
            outbox=line.spy, cards=b.cards, clock=b.rig.clock, emit=emit,
            world_id=world_id, run_id=run_id, world_owner=owner,
        )  # fmt: skip

    return SimpleNamespace(**locals())


def run(c, recipients=(PRIYA,), budget=2):
    from tilo_api.meeting_followup import draft_owner_followup

    return draft_owner_followup(
        c.request, c.writer, c.rig.event_store, c.rig.artifacts, "mt_q4_plan",
        principal=deps.Principal(OWNER, "owner"), switches=c.switches, budget=budget,
        events=c.rig.events, drafts=c.drafts, autopilot_factory=c.factory,
        recipients=None if recipients is None else list(recipients),
    )  # fmt: skip


def replace(c, store, record_id, **changes):
    records = getattr(c.rig.real, store)
    old = records.get(c.rig.org, record_id)
    records.replace({**old.record, **changes}, expected_version=old.version)


@pytest.mark.parametrize("change", ["actor", "uid", "world", "factory", "future", "expired", "outsider", "budget"])
def test_FR_MTG_08_owner_preflight_refuses_without_provider_card_or_outbox(followup, change):
    c = followup
    recipients, budget = (PRIYA,), 2
    if change == "actor":
        c.writer.actor = SAM
    elif change == "uid":
        c.request.state.uid = SAM
    elif change == "world":
        c.rig.event_store.worlds[c.meeting["world_id"]].owner = SAM
    elif change == "factory":
        original = c.factory
        c.factory = lambda world, run, owner, emit: original("w_wrong", run, owner, emit)
    elif change == "future":
        replace(c, "meetings", "mt_q4_plan", minutes_confirmed_by={"by": OWNER, "at": "2099-01-01T00:00:00.000Z"})
    elif change == "expired":
        c.writer.now = c.meeting["delete_minutes_after"]
    elif change == "outsider":
        recipients = ("u_meera",)
    else:
        budget = float("nan")
    with pytest.raises(Refusal):
        run(c, recipients, budget)
    assert c.calls == [] and c.line.bench.cards.dump() == "{}" and c.line.entries() == []


def test_FR_MTG_08_owner_directory_retry_and_retained_minutes(followup):
    c = followup
    c.writer.now = c.meeting["delete_transcript_after"]
    real_check_is_live()
    first = run(c)
    assert first.tier == "T3" and first.level == "L1" and first.to == ("priya@example.com",)
    assert c.line.bench.cards.get(OWNER, first.card_id)["thread_id"] is None
    assert c.line.entries() == [] and c.line.api.sent == []
    assert run(c).card_id == first.card_id and len(c.calls) == 1
    replace(c, "persons", PRIYA, email="priya.changed@example.com")
    changed = run(c)
    assert changed.card_id != first.card_id and changed.to == ("priya.changed@example.com",)
    assert c.line.entries() == [] and c.line.api.sent == []


def test_FR_MTG_08_owner_nudges_only_confirmed_open_item(followup):
    c = followup
    cards = run(c, None)
    assert len(cards) == 1 and cards[0].to == ("priya@example.com",)
    assert cards[0].tier == "T3" and cards[0].level == "L1"
    assert c.line.bench.cards.get(OWNER, cards[0].card_id)["thread_id"] is None
    assert "Sam drafts" not in c.calls[0][1].prompt
    assert c.line.entries() == [] and c.line.api.sent == []


@pytest.mark.parametrize("target", ["meetings", "persons", "work_items"])
def test_FR_MTG_08_owner_generation_race_has_no_card_or_outbox(followup, target):
    c = followup
    ids = {"meetings": "mt_q4_plan", "persons": PRIYA, "work_items": "wi_rate_sheet"}
    changes = {
        "meetings": meeting_tombstone(c.meeting),
        "persons": {"email": "changed@example.com"},
        "work_items": {"status": "done"},
    }
    c.during.append(lambda: replace(c, target, ids[target], **changes[target]))
    with pytest.raises(Refusal):
        run(c)
    assert c.line.bench.cards.dump() == "{}" and c.line.entries() == [] and c.line.api.sent == []


@pytest.mark.parametrize("status", ["proposed", "done", "dropped"])
def test_FR_MTG_08_owner_ineligible_items_never_nudged(followup, status):
    c = followup
    replace(c, "work_items", "wi_rate_sheet", status=status)
    assert run(c, None) == [] and c.calls == [] and c.line.entries() == []


def test_FR_MTG_08_owner_partial_gate_publication_retries(followup, monkeypatch):
    c, failures = followup, []
    original = c.rig.events.append

    def append(world, part):
        if part["type"] == "approval.requested" and not failures:
            failures.append(True)
            raise RuntimeError("offline publication failure")
        return original(world, part)

    monkeypatch.setattr(c.rig.events, "append", append)
    with pytest.raises(RuntimeError):
        run(c)
    assert run(c).tier == "T3" and len(c.calls) == 1 and c.line.entries() == [] and c.line.api.sent == []
