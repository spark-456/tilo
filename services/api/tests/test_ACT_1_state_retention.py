"""ACT-1 / FR-MEM-09: card and stop content shares the trusted draft deadline."""

from types import SimpleNamespace

import pytest
import test_FR_MTG_08_autopilot_factory as factory_tests
from fastapi import HTTPException
from test_FR_MTG_08_autopilot_factory import context, result  # noqa: F401
from test_FR_MTG_08_draft_retention import DB
from tilo_api.draft_firestore import FirestoreDraftStore
from tilo_api.followup_autopilot_state import FirestoreCards, FirestoreStops


@pytest.fixture
def retained():
    c = SimpleNamespace(db=DB(), now=100.0, alive=True)

    def check():
        if not c.alive:
            raise HTTPException(409, "followup_unavailable")

    c.drafts = FirestoreDraftStore(c.db, org_id="org_tilo").bind(
        owner="u_owner",
        source={"meeting_id": "mt_a", "world_id": "w_a", "run_id": "r_a"},
        expires_at=200.0,
        clock=lambda: c.now,
        before_publication=check,
    )
    scope = dict(org_id="org_tilo", owner="u_owner", world_id="w_a", run_id="r_a", drafts=c.drafts)
    c.cards, c.stops = FirestoreCards(c.db, **scope), FirestoreStops(c.db, **scope)
    return c


@pytest.mark.parametrize("invalid", ["deleted", "expired"])
def test_ACT_1_FR_MEM_09_source_deletion_and_expiry_refuse_state_reads_and_writes(retained, invalid):
    c = retained
    assert c.cards.create("u_owner", "card", {"body": "private"})
    assert c.cards.create("#artifacts", "artifact", {"user_id": "u_owner", "card_id": "card"})
    c.stops.add("u_owner", "card")
    assert c.cards.get("u_owner", "card") == {"body": "private"}
    assert c.stops.pending() == [("u_owner", "card")]
    for row in c.db.docs.values():
        assert row["source"] == c.drafts._source
        assert row["expires_at"] == 200.0 and row["owner"] == "u_owner"
    c.alive = invalid != "deleted"
    c.now = 200.0 if invalid == "expired" else 100.0
    before = len(c.db.attempted_ops)
    for call in (
        lambda: c.cards.get("u_owner", "card"),
        lambda: c.cards.get("#artifacts", "artifact"),
        c.stops.pending,
        lambda: c.cards.create("u_owner", "late", {}),
        lambda: c.cards.put("u_owner", "card", {}),
        lambda: c.stops.add("u_owner", "late"),
    ):
        with pytest.raises(HTTPException) as refused:
            call()
        assert refused.value.status_code == 409
    assert len(c.db.attempted_ops) == before


def test_ACT_1_FR_MEM_09_state_cannot_accept_legacy_or_foreign_source_or_deadline(retained):
    c = retained
    c.cards.create("u_owner", "card", {"body": "private"})
    path = c.cards._path("u_owner", "card")
    row = c.db.docs[path].copy()
    for changed in ({"source": {"meeting_id": "mt_other"}}, {"expires_at": 300.0}, {"owner": "u_other"}):
        c.db.docs[path] = row | changed
        assert c.cards.get("u_owner", "card") is None
    c.db.docs[path] = {"payload": row["payload"]}
    assert c.cards.get("u_owner", "card") is None
    c.db.docs.pop(path)
    with pytest.raises(HTTPException):
        c.cards.put("u_owner", "card", {})
    assert path not in c.db.docs


def test_ACT_1_FR_MEM_09_production_factory_writes_bound_card_and_artifact_index():
    c = factory_tests.rig.__wrapped__()
    publication = c.Emit()
    publication.drafts = FirestoreDraftStore(c.db, org_id="org_tilo").bind(
        owner="u_owner",
        source={"meeting_id": "mt_a"},
        expires_at=200.0,
        clock=lambda: 100.0,
        before_publication=lambda: None,
    )
    preview = c.factory("w_meet", "r_meet", "u_owner", publication).preview("u_owner", context(), result())
    # Existing factory acceptance uses ready/T3/L1: ready is a preview, awaiting the owner's gate.
    assert (preview.status, preview.tier, preview.level) == ("ready", "T3", "L1")
    assert any(part["type"] == "approval.requested" for part in c.emitted)
    assert c.outbox.all_entries() == []
    assert c.db.docs
    for row in c.db.docs.values():
        assert row["source"] == {"meeting_id": "mt_a"}
        assert row["owner"] == "u_owner" and row["expires_at"] == 200.0
