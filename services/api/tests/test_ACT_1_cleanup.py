"""ACT-1 / PE-16 / FR-MTG-10 / FR-MEM-09: called cleanup removes follow-up content."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.api_core.exceptions import FailedPrecondition
from test_ACT_1_state_retention import retained  # noqa: F401
from test_FR_MTG_08_draft_retention import Query
from tilo_api.draft_firestore import FirestoreDraftStore
from tilo_api.followup_autopilot_state import FirestoreCards, FirestoreStops
from tilo_api.followup_draft_retention import followup_retention
from tilo_api.people_firestore import firestore_people_stores
from tilo_people.stores import erase_person


class Indexed(Query):
    def where(self, *, filter):  # noqa: A002
        return Indexed(self.db, self.path, (*self.filters, filter), self.count)

    def limit(self, count):
        return Indexed(self.db, self.path, self.filters, count)

    def stream(self):
        self.db.queries.append((self.path, self.filters, self.count))
        for path, row in list(self.db.docs.items()):
            if self.path in ("cards", "stops"):
                selected = path.split("/")[-2] == self.path
            else:
                selected = path.startswith(self.path + "/")
            if not selected:
                continue
            snapshot = self.db.read(path)
            snapshot.reference = SimpleNamespace(path=path)
            if all(
                snapshot.get(f.field_path) == f.value if f.op_string == "==" else snapshot.get(f.field_path) <= f.value
                for f in self.filters
            ):
                yield snapshot
                self.count -= 1
                if not self.count:
                    return


@pytest.fixture
def cleanup(retained):  # noqa: F811
    c = retained
    c.db.collection = c.db.collection_group = lambda path: Indexed(c.db, path)
    c.drafts.create("u_owner", "body", {"body": "private"})
    c.drafts.create("u_owner", "body#emitted", {})
    c.cards.create("u_owner", "card", {"body": "private"})
    c.stops.add("u_owner", "card")
    c.policies = followup_retention(c.db, "org_tilo", lambda: c.now)
    return c


@pytest.mark.parametrize("path", ["meeting", "owner", "expiry"])
def test_ACT_1_cleanup_delete_then_unreadable_all_state(cleanup, path):
    c = cleanup
    kept = set()
    for original, row in list(c.db.docs.items()):
        foreign = original.replace("org_tilo", "org_other")
        c.db.docs[foreign] = row | {"org_id": "org_other"}
        other = original.rsplit("/", 1)[0] + "/" + "b" * 64
        c.db.docs[other] = row | {"owner": "u_other", "expires_at": 300.0}
        kept.update((foreign, other))
        if path == "meeting":
            unrelated = original.rsplit("/", 1)[0] + "/" + "c" * 64
            c.db.docs[unrelated] = row | {"source": {"meeting_id": "mt_b"}}
            kept.add(unrelated)
    if path == "expiry":
        c.now = 200.0
    for policy in c.policies:
        if path == "meeting":
            policy.erase_meeting_complete("u_owner", "mt_a")
        elif path == "owner":
            policy.erase_owner_complete("u_owner")
        else:
            policy.purge_expired()
    assert set(c.db.docs) == kept
    c.now = 100.0
    assert c.cards.get("u_owner", "card") is None and c.stops.pending() == []
    assert c.drafts.get("u_owner", "body") is None and c.drafts.get("u_owner", "body#emitted") is None


def test_ACT_1_PE_16_erase_person_calls_cleanup_after_source_tombstone(people_rig, cleanup):
    from _ppl11a_lib import OWNER
    from _ppl11c_lib import meeting_rig

    rig = meeting_rig(people_rig)
    own_state(cleanup, rig.org, "mt_q4_plan")
    calls = []
    hook = firestore_people_stores(cleanup.db).erase_followup

    def erase(org, user):
        assert rig.stored("meetings", "mt_q4_plan")["status"] == "deleted"
        calls.append((org, user))
        hook(org, user)

    erase_person(replace(rig.stores, erase_followup=erase), rig.org, OWNER)
    assert calls == [(rig.org, OWNER)]
    assert not any(path.startswith(f"orgs/{rig.org}/") for path in cleanup.db.docs)


def own_state(c, org, meeting):
    bound = FirestoreDraftStore(c.db, org_id=org).bind(
        owner="u_owner",
        source={"meeting_id": meeting},
        expires_at=200.0,
        clock=lambda: 100.0,
        before_publication=lambda: None,
    )
    scope = dict(org_id=org, owner="u_owner", world_id="w_a", run_id="r_a", drafts=bound)
    bound.create("u_owner", "body", {"body": "private"})
    bound.create("u_owner", "body#emitted", {})
    FirestoreCards(c.db, **scope).create("u_owner", "card", {"body": "private"})
    FirestoreStops(c.db, **scope).add("u_owner", "card")
    return bound


def test_ACT_1_FR_MTG_10_delete_route_removes_draft_card_stop(people_rig, cleanup, monkeypatch):
    from _ppl11c_lib import meeting_rig
    from tilo_api import store_door

    rig = meeting_rig(people_rig)
    bound = own_state(cleanup, rig.org, "mt_q4_plan")
    monkeypatch.setenv("TILO_API_STORE", "firestore")
    monkeypatch.setattr(store_door, "open_api_store", lambda: SimpleNamespace(client=cleanup.db))
    assert rig.post("/v1/meetings/mt_q4_plan/delete").status_code == 200
    assert not any(path.startswith(f"orgs/{rig.org}/") for path in cleanup.db.docs)
    assert bound.get("u_owner", "body") is None


def test_ACT_1_FR_MEM_09_authenticated_scheduler_calls_expiry_cleanup(clear_flow, cleanup, monkeypatch):
    from _fr_agt_14_lib import SchedApi
    from tilo_api import deps, store_door

    rig = SchedApi(clear_flow, monkeypatch)
    bound = own_state(cleanup, deps.ORG_ID, "mt_a")
    monkeypatch.setenv("TILO_API_STORE", "firestore")
    opened = []

    def door():
        opened.append(True)
        return SimpleNamespace(client=cleanup.db)

    monkeypatch.setattr(store_door, "open_api_store", door)
    assert rig.tick("forged").status_code == 401 and not opened
    assert rig.tick().status_code == 200 and opened
    assert not any(path.startswith(f"orgs/{deps.ORG_ID}/") for path in cleanup.db.docs)
    assert bound.get("u_owner", "body") is None


def test_ACT_1_cleanup_incomplete_owner_drain_refuses_success(cleanup, monkeypatch):
    c = cleanup
    original = c.db.document

    def document(path):
        ref = original(path)
        ref.delete = lambda **kwargs: (_ for _ in ()).throw(FailedPrecondition("rival"))
        return ref

    monkeypatch.setattr(c.db, "document", document)
    with pytest.raises(HTTPException) as refused:
        c.policies[0].erase_owner_complete("u_owner")
    assert refused.value.status_code == 503 and c.db.docs
