"""FR-MTG-08: durable draft bodies and markers require fresh request-bound source authority."""

import copy
from types import SimpleNamespace

import pytest
from _ppl11c_fs_fake import FakeFirestore
from fastapi import HTTPException
from tilo_api.draft_firestore import FirestoreDraftStore

OWNER, OTHER, ORG = "u_owner", "u_other", "org_tilo"
BODY = {"status": "ready", "draft": {"body": "Private confirmed minutes"}}
KEYS = [("draft", BODY), ("draft#emitted", {}), ("draft#emit0", {})]


@pytest.fixture
def rig():
    c = SimpleNamespace(db=FakeFirestore(), now=100.0, alive=True, checks=0)
    c.source = {"meeting_id": "mt_a", "minutes": {"artifact_id": "art_a", "version": 1}}

    def fresh():
        c.checks += 1
        if not c.alive:
            raise HTTPException(409, "followup_unavailable", headers={"Cache-Control": "no-store"})

    c.fresh = fresh
    c.raw = FirestoreDraftStore(c.db, org_id=ORG)
    c.bound = c.raw.bind(owner=OWNER, source=c.source, expires_at=200.0, clock=lambda: c.now, before_publication=fresh)
    return c


def closed(call, status):
    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == status
    assert caught.value.headers.get("Cache-Control") == "no-store"


def test_FR_MTG_08_raw_store_is_unbound_and_bind_does_not_mutate_it(rig):
    c = rig
    assert c.bound is not c.raw
    for store in [c.raw, FirestoreDraftStore(c.db, org_id=ORG)]:
        closed(lambda: store.get(OWNER, "draft"), 503)
        closed(lambda: store.create(OWNER, "draft", BODY), 503)
    assert c.db.attempted_ops == []


def test_FR_MTG_08_bound_owner_cannot_read_or_publish_as_another_owner(rig):
    c = rig
    closed(lambda: c.bound.create(OTHER, "draft", BODY), 503)
    closed(lambda: c.bound.get(OTHER, "draft"), 503)
    assert c.db.docs == {} and c.db.attempted_ops == []


def test_FR_MTG_08_body_and_markers_store_identical_retention_authority(rig):
    c = rig
    for key, value in KEYS:
        assert c.bound.create(OWNER, key, copy.deepcopy(value))
        assert c.bound.get(OWNER, key) == value
    for row in c.db.docs.values():
        assert row["retention_version"] == 1 and row["org_id"] == ORG
        assert row["owner"] == OWNER and row["source"] == c.source
        assert row["expires_at"] == 200.0 and row["created_at"] == 100.0
    assert c.checks >= 6


@pytest.mark.parametrize("invalid", ["deleted", "expired"])
def test_FR_MTG_08_deleted_or_expired_source_denies_body_and_marker_publication(rig, invalid):
    c = rig
    for key, value in KEYS:
        assert c.bound.create(OWNER, key, value)
    if invalid == "deleted":
        c.alive = False
    else:
        c.now = 200.0
    before = len(c.db.attempted_ops)
    for key, value in KEYS:
        try:
            result = c.bound.get(OWNER, key)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            assert result is None
        closed(lambda: c.bound.create(OWNER, key + "-late", value), 409)
    assert len(c.db.attempted_ops) == before


def test_FR_MTG_08_interleaved_binds_keep_independent_source_and_hook(rig):
    c = rig
    second = c.raw.bind(
        owner=OWNER,
        source={"meeting_id": "mt_b"},
        expires_at=300.0,
        clock=lambda: c.now,
        before_publication=lambda: None,
    )
    assert c.bound.create(OWNER, "draft", BODY)
    assert second.get(OWNER, "draft") is None
    assert second.create(OWNER, "draft", {"replacement": True}) is False
    assert second.create(OWNER, "other", {})
    assert c.bound.get(OWNER, "other") is None
    assert c.bound.get(OWNER, "draft") == BODY
    c.alive = False
    closed(lambda: c.bound.create(OWNER, "late", BODY), 409)
    assert second.create(OWNER, "independent", {})


def test_FR_MTG_08_binding_snapshots_caller_owned_source_metadata(rig):
    c = rig
    original = copy.deepcopy(c.source)
    c.source["minutes"]["version"] = 2
    assert c.bound.create(OWNER, "draft", BODY)
    assert next(iter(c.db.docs.values()))["source"] == original


def test_FR_MTG_08_legacy_and_tampered_envelopes_fail_closed(rig):
    c = rig
    assert c.bound.create(OWNER, "draft#emitted", {})
    path, row = next(iter(c.db.docs.items()))
    for change in [
        {"org_id": "org_other"},
        {"owner": OTHER},
        {"source": {"meeting_id": "mt_b"}},
        {"expires_at": 100.0},
        {"expires_at": 300.0},
        {"instruction_hash": "0" * 64},
    ]:
        c.db.put(path, {**row, **change})
        assert c.bound.get(OWNER, "draft#emitted") is None
    c.db.put(path, {"payload": row["payload"]})
    assert c.bound.get(OWNER, "draft#emitted") is None


@pytest.mark.parametrize("invalidate", ["expire", "delete"])
def test_FR_MTG_08_document_lookup_cannot_outlive_publication_authority(rig, monkeypatch, invalidate):
    c = rig
    document = c.db.document

    def delayed(path):
        if invalidate == "expire":
            c.now = 200.0
        else:
            c.alive = False
        return document(path)

    monkeypatch.setattr(c.db, "document", delayed)
    closed(lambda: c.bound.create(OWNER, "draft", BODY), 409)
    assert c.db.attempted_ops == []


def test_FR_MTG_08_valid_duplicate_preserves_first_and_postwrite_revalidates(rig, monkeypatch):
    c = rig
    assert c.bound.create(OWNER, "draft", BODY)
    assert c.bound.create(OWNER, "draft", {"replacement": True}) is False
    assert c.bound.get(OWNER, "draft") == BODY
    commit = c.db.commit

    def late_delete(ops):
        commit(ops)
        c.alive = False

    monkeypatch.setattr(c.db, "commit", late_delete)
    closed(lambda: c.bound.create(OWNER, "late", BODY), 409)
    closed(lambda: c.bound.get(OWNER, "late"), 409)
