"""RT-02, RT-03, RT-07: scope at write, readable scope first then ranking, deletion. Fakes only (EFF-01)."""

from __future__ import annotations

import pytest
from _chunk_testlib import ALICE, BOB, CARA, NOW, ORG, TEAM, doc, make_store
from tilo_memory.chunks import ChunkError, ChunkRetention
from tilo_memory.erasure import REQUIRED_STORES, ErasureRequest, erase_user, verify_erasure

SAME = "quarterly budget review with the finance partners"


def _ids(hits):
    return [h.id for h in hits]


def test_RT_03_identical_text_and_vector_across_two_owners_never_cross():
    store, backend, _, _ = make_store()
    store.index(doc(ALICE, SAME, source_id="pb_alice"))
    store.index(doc(BOB, SAME, source_id="pb_bob"))
    mine = store.search(ORG, ALICE, SAME)
    theirs = store.search(ORG, BOB, SAME)
    assert [h.source["id"] for h in mine] == ["pb_alice"]
    assert [h.source["id"] for h in theirs] == ["pb_bob"]
    assert store.search(ORG, CARA, SAME) == []  # nothing of her own: no query at all
    assert backend.queries == [("owner", ALICE), ("owner", BOB)]  # one query per readable scope, filter inside it


def test_RT_03_a_blank_wildcard_or_unknown_caller_is_refused_before_any_query():
    store, backend, embedder, _ = make_store()
    store.index(doc(ALICE, SAME))
    embedder.calls.clear()
    for caller in ("", "*", "u_*", "u_alice ", "u_stranger", None):
        with pytest.raises(ChunkError):
            store.search(ORG, caller, SAME)
    with pytest.raises(ChunkError):
        store.search("org_other", ALICE, SAME)
    assert backend.queries == [] and embedder.calls == []


def test_RT_03_team_chunks_reach_current_members_only_and_a_removed_member_is_refused():
    store, backend, _, rules = make_store()
    store.index(doc(ALICE, SAME, kind="deliverable", source_id="art_one", team=TEAM, world_id="wd_one"))
    assert store.search(ORG, BOB, SAME) == []  # not a member
    rules.teams[BOB] = [TEAM]
    assert len(store.search(ORG, BOB, SAME)) == 1
    assert ("team_id", TEAM) in backend.queries
    rules.teams[BOB] = []  # removed from the team: no team scope is queried any more
    assert store.search(ORG, BOB, SAME) == []


def test_RT_03_a_revoked_share_and_a_pin_made_personal_are_refused_at_the_re_check():
    store, _, _, rules = make_store()
    store.index(doc(ALICE, SAME, kind="deliverable", source_id="art_one", team=TEAM, world_id="wd_one"))
    store.index(doc(ALICE, SAME + " pin", source_id="pb_team", team=TEAM))
    rules.teams[BOB] = [TEAM]
    hits = store.search(ORG, BOB, SAME)
    assert len(hits) == 2
    rules.denied.update(_ids(hits))  # the share is revoked and the pin became personal: the sources now refuse
    assert store.search(ORG, BOB, SAME) == []
    assert len(store.search(ORG, ALICE, SAME)) == 0  # the team chunks are not her own scope either (owner scope)...


def test_RT_03_a_re_check_that_fails_to_run_drops_the_hit():
    store, _, _, rules = make_store()
    store.index(doc(ALICE, SAME))

    def boom(*_args):
        raise RuntimeError("store down")

    rules.readable = boom  # type: ignore[method-assign]
    assert store.search(ORG, ALICE, SAME) == []


def test_RT_02_uploads_minutes_and_notes_are_never_team_chunks():
    store, _, _, _ = make_store()
    for kind, source_id in (("upload", "art_up"), ("minutes", "mt_one"), ("memory_item", "mem_one")):
        with pytest.raises(ChunkError):
            store.index(doc(ALICE, SAME, kind=kind, source_id=source_id, team=TEAM))
    with pytest.raises(ChunkError):  # a team deliverable names its world
        store.index(doc(ALICE, SAME, kind="deliverable", source_id="art_one", team=TEAM))
    with pytest.raises(ChunkError):  # ids and kinds must agree
        store.index(doc(ALICE, SAME, kind="pin", source_id="art_one"))


def test_RT_07_source_deleted_chunks_gone_and_an_edit_replaces_the_old_passages():
    store, backend, _, _ = make_store()
    store.index(doc(ALICE, "first paragraph here\n\nsecond paragraph there", source_id="pb_one"))
    store.index(doc(BOB, SAME, source_id="pb_bob"))
    store.index(doc(ALICE, "only the new text", source_id="pb_one"))
    assert [h.text for h in store.search(ORG, ALICE, "text")] == ["only the new text"]
    assert store.delete_for_source(ORG, "pin", "pb_one") == 1
    assert store.search(ORG, ALICE, "text") == []
    assert len(store.search(ORG, BOB, SAME)) == 1  # another owner's chunks stay
    assert backend.for_source(ORG, "pin", "pb_one") == []


def test_RT_07_a_new_artifact_version_replaces_the_old_versions_chunks():
    store, backend, _, _ = make_store()
    store.index(doc(ALICE, "version one text", kind="upload", source_id="art_up", version=1))
    store.index(doc(ALICE, "version two text", kind="upload", source_id="art_up", version=2))
    assert [d["source"]["version"] for d in backend.for_source(ORG, "upload", "art_up")] == [2]


def test_RT_07_the_daily_sweep_deletes_chunks_whose_source_is_gone_or_whose_retention_passed():
    store, backend, _, rules = make_store()
    store.index(doc(ALICE, "kept text", source_id="pb_keep"))
    store.index(doc(ALICE, "orphan text", source_id="pb_gone"))
    store.index(doc(ALICE, "old text", source_id="pb_old", expires_at="2026-10-01T00:00:00.000Z"))
    rules.gone_ids.update(d["id"] for d in backend.for_source(ORG, "pin", "pb_gone"))
    assert store.sweep(ORG) == 2
    assert [d["source"]["id"] for d in backend.scan(ORG)] == ["pb_keep"]


def test_FR_MEM_09_RT_07_erasure_removes_every_chunk_of_the_user_and_verify_agrees():
    store, backend, _, _ = make_store()
    store.index(doc(ALICE, SAME, source_id="pb_alice"))
    store.index(doc(BOB, SAME, source_id="pb_bob"))

    class Empty:
        def records(self):
            return []

        def delete(self, record_id):
            raise AssertionError("nothing to delete")

    registry = {name: Empty() for name in REQUIRED_STORES} | {"firestore_chunks": ChunkRetention(backend, ORG)}
    assert not verify_erasure(registry, ALICE).ok
    report = erase_user(registry, ErasureRequest(ALICE, NOW), now=NOW)
    assert report.complete and report.removed["firestore_chunks"] == 1
    assert verify_erasure(registry, ALICE).ok
    assert len(store.search(ORG, BOB, SAME)) == 1
