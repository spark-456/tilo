"""Meeting deletion drains indexed follow-up data and retries after a tombstone."""

from types import SimpleNamespace

import pytest
from _ppl11a_lib import OWNER, SAM
from _ppl11c_lib import meeting_rig
from fastapi import HTTPException
from google.api_core.exceptions import FailedPrecondition
from test_FR_MTG_08_draft_retention import DB, Query
from tilo_api.followup_draft_retention import DraftRetention
from tilo_api.people_writes import Writer, remove_meeting
from tilo_people.errors import VersionConflict


class IndexedQuery(Query):
    def where(self, *, filter):  # noqa: A002
        return IndexedQuery(self.db, self.path, (*self.filters, filter), self.count)

    def limit(self, count):
        return IndexedQuery(self.db, self.path, self.filters, count)

    def stream(self):
        self.db.queries.append((self.path, [(f.field_path, f.op_string, f.value) for f in self.filters], self.count))
        rows = []
        for path, doc in sorted(self.db.docs.items()):
            if not path.startswith(self.path + "/"):
                continue
            snapshot = self.db.read(path)
            if all(snapshot.get(f.field_path) == f.value for f in self.filters):
                rows.append(snapshot)
        yield from rows[: self.count]


@pytest.fixture
def drafts():
    db = DB()
    db.collection = lambda path: IndexedQuery(db, path)
    policy = DraftRetention(db, org_id="org_tilo", clock=lambda: 100.0, source_valid=lambda *args: True)

    def put(key, owner=OWNER, meeting="mt_a", bound=policy):
        row = bound.envelope(owner, key, {"body": "private"}, source={"meeting_id": meeting}, expires_at=200.0)
        path = bound.path(owner, key)
        db.document(path).create(row)
        return path

    return SimpleNamespace(db=db, policy=policy, put=put)


def test_FR_MTG_10_indexed_meeting_erasure_preserves_other_scope(drafts):
    c = drafts
    foreign = DraftRetention(c.db, org_id="org_other", clock=lambda: 100.0, source_valid=lambda *args: True)
    removed = [c.put("body"), c.put("body#emitted")]
    kept = [c.put("other", owner=SAM), c.put("other_meeting", meeting="mt_b"), c.put("foreign", bound=foreign)]
    assert c.policy.erase_meeting(OWNER, "mt_a", limit=1) == 1
    assert c.policy.erase_meeting(OWNER, "mt_a", limit=200) == 1
    assert all(path not in c.db.docs for path in removed)
    assert all(path in c.db.docs for path in kept)
    for path, filters, limit in c.db.queries:
        assert path == "orgs/org_tilo/followup_drafts"
        assert filters == [("owner", "==", OWNER), ("source.meeting_id", "==", "mt_a")]
        assert 1 <= limit <= 200


def test_FR_MTG_10_drain_freshly_rereads_before_complete(drafts, monkeypatch):
    c = drafts
    c.put("initial")
    original = c.policy.erase_meeting
    calls = []

    def late(owner, meeting_id, *, limit=200):
        result = original(owner, meeting_id, limit=limit)
        if not calls:
            c.put("late")
        calls.append(result)
        return result

    monkeypatch.setattr(c.policy, "erase_meeting", late)
    c.policy.erase_meeting_complete(OWNER, "mt_a", passes=3, limit=1)
    assert not c.db.docs and len(calls) >= 2
    assert len(c.db.queries) > len(calls), "completion needs a fresh indexed reread"


@pytest.mark.parametrize("churn", [False, True])
def test_FR_MTG_10_bounded_incomplete_or_precondition_churn_returns_503(drafts, monkeypatch, churn):
    c = drafts
    for index in range(4):
        c.put(str(index))
    if churn:
        original = c.db.document

        def document(path):
            ref = original(path)
            ref.delete = lambda **kwargs: (_ for _ in ()).throw(FailedPrecondition("changed"))
            return ref

        monkeypatch.setattr(c.db, "document", document)
    with pytest.raises(HTTPException) as refused:
        c.policy.erase_meeting_complete(OWNER, "mt_a", passes=2, limit=1)
    assert refused.value.status_code == 503 and c.db.docs
    assert len(c.db.queries) <= 5, "drain cannot loop indefinitely"


@pytest.fixture
def deletion(people_rig):
    rig = meeting_rig(people_rig)
    return rig, Writer(rig.stores, rig.org, OWNER, rig.clock, rig.redactor)


def test_FR_MTG_10_cleanup_after_tombstone_and_retry_after_failure(deletion):
    rig, writer = deletion
    calls = []

    def cleanup(owner, meeting_id):
        assert rig.stored("meetings", meeting_id)["status"] == "deleted"
        calls.append((owner, meeting_id))
        if len(calls) == 1:
            raise HTTPException(503, "store_unavailable")

    with pytest.raises(HTTPException) as refused:
        remove_meeting(writer, rig.artifacts, "mt_q4_plan", cleanup=cleanup)
    assert refused.value.status_code == 503
    version = rig.version_of("meetings", "mt_q4_plan")
    assert remove_meeting(writer, rig.artifacts, "mt_q4_plan", cleanup=cleanup)["status"] == "deleted"
    assert rig.version_of("meetings", "mt_q4_plan") == version
    assert calls == [(OWNER, "mt_q4_plan")] * 2


@pytest.mark.parametrize("failure", ["owner", "cas"])
def test_FR_MTG_10_cleanup_never_runs_before_owner_or_successful_cas(deletion, monkeypatch, failure):
    rig, writer = deletion
    calls = []
    if failure == "owner":
        writer.actor = SAM
    else:

        def conflict(*args, **kwargs):
            raise VersionConflict("changed")

        monkeypatch.setattr(rig.stores.meetings, "replace", conflict)
    with pytest.raises(HTTPException) as refused:
        remove_meeting(writer, rig.artifacts, "mt_q4_plan", cleanup=lambda *args: calls.append(args))
    assert refused.value.status_code == (404 if failure == "owner" else 409)
    assert calls == [] and rig.stored("meetings", "mt_q4_plan")["status"] != "deleted"


@pytest.mark.parametrize("actor", [OWNER, SAM])
def test_FR_MTG_10_actual_route_uses_lazy_door_and_scoped_cleanup(people_rig, drafts, monkeypatch, actor):
    from tilo_api import store_door

    rig = meeting_rig(people_rig)
    policy = DraftRetention(drafts.db, org_id=rig.org, clock=lambda: 100.0, source_valid=lambda *args: True)
    paths = [
        drafts.put("body", meeting="mt_q4_plan", bound=policy),
        drafts.put("body#emitted", meeting="mt_q4_plan", bound=policy),
    ]
    kept = drafts.put("different", meeting="mt_other", bound=policy)
    opened = []

    def door():
        assert rig.stored("meetings", "mt_q4_plan")["status"] == "deleted"
        opened.append(True)
        return SimpleNamespace(client=drafts.db)

    monkeypatch.setenv("TILO_API_STORE", "firestore")
    monkeypatch.setattr(store_door, "open_api_store", door)
    rig.as_user(actor)
    response = rig.post("/v1/meetings/mt_q4_plan/delete")
    assert response.status_code == (200 if actor == OWNER else 404), response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert bool(opened) is (actor == OWNER)
    assert all((path in drafts.db.docs) is (actor != OWNER) for path in paths)
    assert kept in drafts.db.docs
    if actor == OWNER:
        assert rig.post("/v1/meetings/mt_q4_plan/delete").status_code == 200
