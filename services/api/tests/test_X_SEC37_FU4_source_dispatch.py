"""X-SEC37-FU4: source erasure closes dispatch, including a lease-time race."""

from types import SimpleNamespace

import pytest
from _adr35_l2_lib import Clock, Rig, entry, outbox_id
from test_ACT_1_state_retention import retained  # noqa: F401
from test_FR_CON_02_ADR35_L2_gate_and_tick import sweep  # noqa: F401
from tilo_connectors import Outbox
from tilo_connectors.fakes import FakeGmail


@pytest.mark.parametrize("kind", ["memory", "firestore"])
@pytest.mark.parametrize("gone", ["meeting", "person", "world", "unreadable"])
def test_X_SEC37_FU4_source_checked_after_claim_before_send(kind, gone):
    rig, gmail, clock = Rig(kind), FakeGmail(), Clock()
    store = rig.make()
    rig.put(store, entry(1), entry(2))
    claims = []
    original = store._claim_for_sending

    def claim(*args):
        result = original(*args)
        claims.append(args[0])
        return result

    store._claim_for_sending = claim

    def valid(row):
        assert row["id"] in claims, "fresh source check must follow the claim"
        if row["id"] == outbox_id(1):
            if gone == "unreadable":
                raise RuntimeError("offline")
            return False
        return True

    outbox = Outbox(store, {"gmail": gmail}, emit=lambda part: None, clock=clock, source_valid=valid)
    outbox.dispatch_due()
    assert store.get(outbox_id(1))["state"] == "failed"
    assert store.get(outbox_id(2))["state"] == "sent"
    assert len(gmail.sent) == 1


def test_X_SEC37_FU4_sweep_passes_fresh_source_check():
    from tilo_api.outbox_firestore import sweep_due

    rig, gmail = Rig("firestore"), FakeGmail()
    store = rig.make()
    rig.put(store, entry(1))
    sweep_due(store, {"gmail": gmail}, rig.clock, lambda world: False, source_valid=lambda row: False)
    assert store.get(outbox_id(1))["state"] == "failed" and not gmail.sent


def test_X_SEC37_FU4_tick_abandons_removed_world_instead_of_pausing_forever(sweep):  # noqa: F811
    sweep.outbox._insert_if_absent(entry(1))
    sweep.store.worlds.clear()
    assert sweep.tick().status_code == 200
    assert sweep.outbox.get(outbox_id(1))["state"] == "failed" and not sweep.gmail.sent


@pytest.mark.parametrize("meeting", [None, "mt_a"])
@pytest.mark.parametrize("default_clock", [False, True])
def test_X_SEC37_FU4_cleanup_abandons_only_matching_source(monkeypatch, meeting, default_clock):
    from tilo_api import followup_outbox_sources as sources

    rig = Rig("memory")
    store = rig.make()
    rig.put(store, entry(1, key="autopilot:c1"), entry(2, key="autopilot:c2"))
    rows = [
        SimpleNamespace(
            to_dict=lambda: {
                "org_id": "org_tilo",
                "owner": "u_owner",
                "source": {"meeting_id": "mt_a"},
                "payload": '{"world_id":"w_adr35_a","card_id":"c1"}',
            }
        )
    ]
    query = SimpleNamespace(where=lambda **kw: query, stream=lambda: iter(rows))
    monkeypatch.setattr(sources, "followup_retention", lambda *args: [None, SimpleNamespace(_query=lambda: query)])
    sources.cancel_source_entries(
        None, "org_tilo", "u_owner", meeting, store=store, clock=None if default_clock else rig.clock
    )
    assert store.get(outbox_id(1))["state"] == "failed"
    assert store.get(outbox_id(2))["state"] == "queued"


@pytest.mark.parametrize("gone", [None, "meeting", "person", "world", "card", "expired", "run"])
def test_X_SEC37_FU4_retained_source_requires_current_person_meeting_world(retained, gone):  # noqa: F811
    from tilo_api.followup_outbox_sources import source_valid

    c = retained
    c.cards.create("u_owner", "card", {"card_id": "card", "world_id": "w_a"})
    row = entry(1, world="w_a", key="autopilot:card") | {"run_id": "r_a"}
    meeting = SimpleNamespace(record={"org_id": "org_tilo", "owner": "u_owner", "world_id": "w_a", "status": "ended"})
    if gone == "meeting":
        meeting.record["status"] = "deleted"
    people = SimpleNamespace(
        persons=SimpleNamespace(get=lambda *args: None if gone == "person" else object()),
        meetings=SimpleNamespace(get=lambda *args: meeting),
    )
    world = None if gone == "world" else SimpleNamespace(owner="u_owner", run_id="r_b" if gone == "run" else "r_a")
    if gone == "card":
        c.db.docs.clear()
    assert source_valid(row, world, people, c.db, "org_tilo", 200.0 if gone == "expired" else 100.0) == (gone is None)
