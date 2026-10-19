"""Fresh server time and meeting CAS guard offline follow-up publication."""

import json

import pytest
from _ppl11a_lib import OWNER, PRIYA
from test_FR_MTG_08_owner_followup import followup, replace  # noqa: F401
from test_FR_MTG_08_owner_followup_boundaries import remove_minutes
from tilo_api import deps
from tilo_api.meeting_followup import draft_owner_followup
from tilo_api.people_writes import Refusal
from tilo_people.errors import VersionConflict


def fresh_run(c):
    return draft_owner_followup(
        c.request, c.writer, c.rig.event_store, c.rig.artifacts, "mt_q4_plan",
        principal=deps.Principal(OWNER, "owner"), switches=c.switches, budget=2,
        events=c.rig.events, drafts=c.drafts, autopilot_factory=c.factory,
        recipients=[PRIYA], clock=lambda: c.time,
        allowance=c.allowance, allowance_cap=c.allowance_cap,
    )  # fmt: skip


def assert_unpublished(c):
    assert c.rig.events.calls == []
    assert c.line.bench.cards.dump() == "{}"
    assert c.line.entries() == [] and c.line.api.sent == []


@pytest.mark.parametrize("when", ["generation", "publication"])
def test_FR_MTG_08_fresh_clock_expiry_refuses(followup, monkeypatch, when):  # noqa: F811
    c = followup
    c.time = c.writer.now

    def expire():
        c.time = c.meeting["delete_minutes_after"]

    if when == "generation":
        c.during.append(expire)
    else:
        create = c.drafts.create

        def after_create(uid, key, doc):
            result = create(uid, key, doc)
            if doc.get("draft"):
                expire()
            return result

        monkeypatch.setattr(c.drafts, "create", after_create)
    with pytest.raises(Refusal) as refused:
        fresh_run(c)
    assert refused.value.status_code == 409
    assert len(c.calls) == 1
    assert_unpublished(c)


@pytest.mark.parametrize("change", ["confirmation", "pointer", "erasure", "run", "owner"])
def test_FR_MTG_08_fresh_source_generation_races_refuse(followup, change):  # noqa: F811
    c = followup
    c.time = c.writer.now

    def mutate():
        if change == "confirmation":
            replace(c, "meetings", "mt_q4_plan", minutes_confirmed_by=None)
        elif change == "pointer":
            replace(c, "meetings", "mt_q4_plan", minutes={"artifact_id": "art_rival_minutes", "version": 1})
        elif change == "erasure":
            remove_minutes(c, "metadata")
        elif change == "run":
            c.rig.event_store.worlds[c.meeting["world_id"]].run_id = "r_rival"
        else:
            c.rig.event_store.worlds[c.meeting["world_id"]].owner = PRIYA

    c.during.append(mutate)
    with pytest.raises(Refusal):
        fresh_run(c)
    assert_unpublished(c)


def test_FR_MTG_08_publication_CAS_rival_never_announces(followup, monkeypatch):  # noqa: F811
    c = followup
    c.time = c.writer.now
    calls = []
    records = c.rig.stores.meetings

    def rival(record, *, expected_version):
        calls.append(expected_version)
        raise VersionConflict("offline rival")

    monkeypatch.setattr(records, "replace", rival)
    with pytest.raises(Refusal) as refused:
        fresh_run(c)
    assert refused.value.status_code == 409 and calls
    assert_unpublished(c)


def test_FR_MTG_08_stable_CAS_preserves_confirmation_and_retry(followup, monkeypatch):  # noqa: F811
    c = followup
    c.time = c.writer.now
    records = c.rig.stores.meetings
    original = records.replace
    calls = []
    before = records.get(c.rig.org, "mt_q4_plan")

    def record_cas(record, *, expected_version):
        calls.append(expected_version)
        return original(record, expected_version=expected_version)

    monkeypatch.setattr(records, "replace", record_cas)
    first = fresh_run(c)
    second = fresh_run(c)
    assert first.tier == "T3" and first.level == "L1"
    assert second.card_id == first.card_id and len(c.calls) == 1
    after = records.get(c.rig.org, "mt_q4_plan")
    assert after.record == before.record
    assert after.version > before.version and calls == sorted(set(calls))
    # BQ-182 requires an artifact index beside the one actual approval card (autopilot_send.index_artifact).
    card = c.line.bench.cards.get(OWNER, first.card_id)
    artifact_id = card["item"]["artifact_id"]
    assert json.loads(c.line.bench.cards.dump()) == {
        f"{OWNER}/{first.card_id}": card,
        f"#artifacts/{artifact_id}": {"user_id": OWNER, "card_id": first.card_id},
    }
    assert c.line.entries() == [] and c.line.api.sent == []


def test_FR_MTG_08_owner_caller_passes_fresh_server_clock(followup):  # noqa: F811
    from tilo_api.owner_followup_caller import OwnerFollowupCaller
    from tilo_api.owner_minutes_caller import OwnerMinutesCaller

    c = followup
    c.time = c.writer.now
    owner = OwnerMinutesCaller(
        c.request, deps.Principal(OWNER, "owner"), c.rig.stores, c.rig.event_store,
        c.rig.artifacts, lambda: c.time, c.writer.redact, c.switches, c.rig.events, 2, c.allowance, c.allowance_cap,
    )  # fmt: skip
    caller = OwnerFollowupCaller(owner, c.drafts, c.factory)

    def expire():
        c.time = c.meeting["delete_minutes_after"]

    c.during.append(expire)
    with pytest.raises(Refusal):
        caller.draft("mt_q4_plan", recipients=[PRIYA])
    assert_unpublished(c)


def test_FR_MTG_08_factory_final_card_write_guard(followup, monkeypatch):  # noqa: F811
    c = followup
    c.time = c.writer.now
    factory = c.factory
    hook_calls = []

    def guarded_factory(world_id, run_id, owner, emit):
        ap = factory(world_id, run_id, owner, emit)
        create = ap._cards.create

        def final_create(uid, card_id, doc):
            c.time = c.meeting["delete_minutes_after"]
            hook_calls.append(True)
            emit.before_publication()
            return create(uid, card_id, doc)

        monkeypatch.setattr(ap._cards, "create", final_create)
        return ap

    c.factory = guarded_factory
    with pytest.raises(Refusal) as refused:
        fresh_run(c)
    assert refused.value.status_code == 409 and hook_calls
    assert not [e for e in c.rig.events.calls if e.part["type"] == "approval.requested"]
    assert c.line.bench.cards.dump() == "{}"
    assert c.line.entries() == [] and c.line.api.sent == []
