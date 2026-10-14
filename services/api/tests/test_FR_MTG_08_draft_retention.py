"""Trusted metadata denies stale draft bodies and markers; indexed cleanup stays scoped."""

import copy
from types import SimpleNamespace

import pytest
from _ppl11c_fs_fake import FakeFirestore
from fastapi import HTTPException

ORG, OWNER, OTHER = "org_tilo", "u_owner", "u_other"
BODY = {"draft": {"body": "Private confirmed minutes"}, "status": "ready"}


class Query:
    def __init__(self, db, path, filters=(), count=200):
        self.db, self.path, self.filters, self.count = db, path, filters, count

    def where(self, *, filter):  # noqa: A002
        return Query(self.db, self.path, (*self.filters, filter), self.count)

    def limit(self, count):
        return Query(self.db, self.path, self.filters, count)

    def stream(self):
        self.db.queries.append((self.path, [(f.field_path, f.op_string, f.value) for f in self.filters], self.count))
        rows = []
        for path, doc in sorted(self.db.docs.items()):
            if not path.startswith(self.path + "/"):
                continue
            if all(
                doc.get(f.field_path) == f.value
                if f.op_string == "=="
                else doc.get(f.field_path, float("inf")) <= f.value
                for f in self.filters
            ):
                rows.append(self.db.read(path))
        yield from rows[: self.count]


class DB(FakeFirestore):
    def __init__(self):
        super().__init__()
        self.queries = []

    def collection(self, path):
        return Query(self, path)


@pytest.fixture
def rig():
    from tilo_api.followup_draft_retention import DraftRetention

    db = DB()
    c = SimpleNamespace(db=db, now=100.0, alive=True)
    c.source = {
        "meeting_id": "mt_a",
        "world_id": "w_a",
        "run_id": "r_a",
        "minutes": {"artifact_id": "art_minutes", "version": 1},
        "confirmed_at": "2026-10-14T03:00:00.000Z",
    }
    c.policy = DraftRetention(
        db, org_id=ORG, clock=lambda: c.now, source_valid=lambda owner, source: c.alive and source == c.source
    )
    return c


def put(c, key="draft", value=BODY, owner=OWNER, policy=None):
    policy = policy or c.policy
    row = policy.envelope(owner, key, copy.deepcopy(value), source=c.source, expires_at=200.0)
    path = policy.path(owner, key)
    c.db.document(path).create(row)
    return path


@pytest.mark.parametrize("invalid", ["erased", "expired"])
def test_FR_MTG_08_owner_erasure_or_expiry_denies_bodies_and_emit_markers(rig, invalid):
    c = rig
    for key, value in [("draft", BODY), ("draft#emitted", {}), ("draft#emit0", {})]:
        path = put(c, key, value)
        assert c.policy.read(OWNER, key, c.db.docs[path]) == value
    if invalid == "erased":
        c.alive = False
    else:
        c.now = 200.0
    for key in ["draft", "draft#emitted", "draft#emit0"]:
        assert c.policy.read(OWNER, key, c.db.docs[c.policy.path(OWNER, key)]) is None
        with pytest.raises(HTTPException) as refused:
            c.policy.envelope(OWNER, key, BODY, source=c.source, expires_at=200.0)
        assert refused.value.status_code == 409


def test_FR_MTG_08_metadata_and_marker_idempotency_while_source_valid(rig):
    c = rig
    path = put(c, "draft#emitted", {})
    row = c.db.docs[path]
    assert row["owner"] == OWNER and row["org_id"] == ORG and row["source"] == c.source
    assert row["expires_at"] == 200.0 and row["created_at"] == 100.0
    c.now = 199.9
    assert c.policy.read(OWNER, "draft#emitted", row) == {}
    assert c.policy.path(OWNER, "draft#emitted") == path
    assert c.policy.read(OTHER, "draft#emitted", row) is None
    assert c.policy.read(OWNER, "different", row) is None
    assert c.policy.read(OWNER, "draft", {"payload": row["payload"]}) is None


def test_FR_MTG_08_indexed_owner_erasure_preserves_other_owner_org(rig):
    from tilo_api.followup_draft_retention import DraftRetention

    c = rig
    other_org = DraftRetention(c.db, org_id="org_other", clock=lambda: c.now, source_valid=lambda *args: True)
    owned = [put(c), put(c, "draft#emitted", {})]
    kept = [put(c, owner=OTHER), put(c, policy=other_org)]
    assert c.policy.erase_owner(OWNER, limit=1) == 1
    assert c.policy.erase_owner(OWNER, limit=10) == 1
    assert c.policy.erase_owner(OWNER, limit=10) == 0
    assert all(p not in c.db.docs for p in owned) and all(p in c.db.docs for p in kept)
    assert all(filters == [("owner", "==", OWNER)] for _, filters, _ in c.db.queries)
    assert all(path == f"orgs/{ORG}/followup_drafts" for path, _, _ in c.db.queries)


def test_FR_MTG_08_indexed_expiry_cleans_body_and_marker_exact_boundary(rig):
    c = rig
    owned = [put(c), put(c, "draft#emitted", {})]
    c.now = 200.0
    assert c.policy.purge_expired(limit=1) == 1
    assert c.policy.purge_expired(limit=10) == 1
    assert all(p not in c.db.docs for p in owned)
    assert all(filters == [("expires_at", "<=", 200.0)] for _, filters, _ in c.db.queries)


def test_FR_MTG_08_late_write_after_source_erasure_cannot_resurrect_content(rig):
    c = rig
    row = c.policy.envelope(OWNER, "draft", BODY, source=c.source, expires_at=200.0)
    c.alive = False
    c.db.document(c.policy.path(OWNER, "draft")).create(row)  # late IO after source deletion
    assert c.policy.read(OWNER, "draft", row) is None
    with pytest.raises(HTTPException):
        c.policy.envelope(OWNER, "draft", BODY, source=c.source, expires_at=200.0)
    assert c.policy.erase_owner(OWNER, limit=10) == 1


def test_FR_MTG_08_source_failure_and_malformed_cleanup_are_closed(rig):
    c = rig

    def fail(*args):
        raise RuntimeError("private source")

    c.policy.source_valid = fail
    with pytest.raises(HTTPException) as refused:
        c.policy.envelope(OWNER, "draft", BODY, source=c.source, expires_at=200.0)
    assert refused.value.status_code == 503 and refused.value.detail == "store_unavailable"
    for owner in ["", "../u_other", "u_*"]:
        with pytest.raises(ValueError):
            c.policy.erase_owner(owner)
    assert c.db.attempted_ops == []


def test_FR_MTG_08_changed_source_refuses_stored_body_and_marker(rig):
    c = rig
    paths = [put(c), put(c, "draft#emitted", {})]
    c.source["minutes"]["version"] = 2
    for key, path in zip(["draft", "draft#emitted"], paths, strict=True):
        assert c.policy.read(OWNER, key, c.db.docs[path]) is None
    assert all(c.db.docs[p]["source"]["minutes"]["version"] == 1 for p in paths)
