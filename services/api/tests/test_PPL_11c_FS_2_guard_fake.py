"""PPL-11c-FS-2 guards: the stand-in client the FS-2 tests run on (`_ppl11c_fs2_fake.py`) behaves as Firestore does
where the tests lean on it. They pass today and stay green: if one fails, the fake changed, and every FS-2 verdict
is suspect. No production code is involved except the FS-1 person store, which must keep working on the fake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from _ppl11c_fs2_fake import SENTINEL, FakeFirestore2, is_record_path
from google.api_core import exceptions as gexc
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter


def test_PPL_11c_FS_2_guard_fake_a_transaction_that_read_a_document_which_then_changed_is_aborted_and_retried():
    db = FakeFirestore2()
    ref = db.document("orgs/o/lim/a")
    ref.set({"n": 0})
    attempts = []

    @firestore.transactional
    def bump(txn):
        attempts.append(1)
        seen = ref.get(transaction=txn).get("n")
        if len(attempts) == 1:
            ref.set({"n": 100})  # a rival commits between our read and our commit
        txn.update(ref, {"n": seen + 1})

    bump(db.transaction())
    assert len(attempts) == 2 and db.raw("orgs/o/lim/a") == {"n": 101}


def test_PPL_11c_FS_2_guard_fake_a_read_modify_write_outside_a_transaction_can_lose_an_update():
    db = FakeFirestore2()
    ref = db.document("orgs/o/lim/a")
    ref.set({"n": 0})
    first_view = ref.get().get("n")
    ref.set({"n": 5})
    ref.set({"n": first_view + 1})  # no transaction, no precondition: the 5 is gone
    assert db.raw("orgs/o/lim/a") == {"n": 1}


def test_PPL_11c_FS_2_guard_fake_preconditions_are_enforced():
    db = FakeFirestore2()
    ref = db.document("orgs/o/lim/a")
    ref.create({"n": 1})
    with pytest.raises(gexc.AlreadyExists):
        ref.create({"n": 2})
    snap = ref.get()
    ref.update({"n": 3})
    with pytest.raises(gexc.FailedPrecondition):
        ref.update({"n": 4}, option=db.write_option(last_update_time=snap.update_time))
    ref.update({"n": 5}, option=db.write_option(last_update_time=ref.get().update_time))
    with pytest.raises(gexc.NotFound):
        db.document("orgs/o/lim/none").update({"n": 1})
    assert db.raw("orgs/o/lim/a") == {"n": 5}


def test_PPL_11c_FS_2_guard_fake_transforms_dotted_updates_and_utc_timestamps():
    db = FakeFirestore2()
    ref = db.document("orgs/o/lim/a")
    ref.set({"n": 1, "hits": [1], "at": datetime(2026, 10, 7, 10, 0)})
    ref.update({"n": firestore.Increment(2), "hits": firestore.ArrayUnion([1, 2]), "m.k": 7})
    doc = db.raw("orgs/o/lim/a")
    assert doc["n"] == 3 and doc["hits"] == [1, 2] and doc["m"] == {"k": 7}
    assert doc["at"] == datetime(2026, 10, 7, 10, 0, tzinfo=UTC) and doc["at"].tzinfo is not None
    ref.update({"stamp": firestore.SERVER_TIMESTAMP})
    assert db.raw("orgs/o/lim/a")["stamp"].tzinfo is not None


def test_PPL_11c_FS_2_guard_fake_queries_filter_order_limit_and_see_only_their_own_collection():
    db = FakeFirestore2()
    for i, owner in enumerate(("a", "b", "a")):
        db.document(f"orgs/o/lim/d{i}").set({"owner": owner, "at": i})
    db.document("orgs/o/lim/d0/sub/x").set({"owner": "a", "at": 9})
    q = db.collection("orgs/o/lim").where(filter=FieldFilter("owner", "==", "a")).order_by("at", direction="DESCENDING")
    assert [s.id for s in q.stream()] == ["d2", "d0"]
    assert [s.id for s in q.limit(1).stream()] == ["d2"]
    assert [s.id for s in db.collection_group("sub").stream()] == ["x"]


def test_PPL_11c_FS_2_guard_fake_an_outage_refuses_before_anything_is_applied_and_names_no_path():
    db = FakeFirestore2()
    db.outage = lambda path: not is_record_path(path)
    with pytest.raises(gexc.ServiceUnavailable) as caught:
        db.document("orgs/o/lim/a").create({"n": 1})
    assert SENTINEL in str(caught.value) and db.raw("orgs/o/lim/a") is None
    db.document("orgs/o/people_work_item/wi_x").create({"version": 1, "record": {}})  # records are not out
    db.outage = None
    db.document("orgs/o/lim/a").create({"n": 1})


def test_PPL_11c_FS_2_guard_fake_the_nth_counted_operation_fails_and_a_lost_answer_still_lands():
    db = FakeFirestore2()
    db.arm_fault(2, applied=True)
    db.document("orgs/o/lim/a").create({"n": 1})  # operation 1
    with pytest.raises(gexc.DeadlineExceeded):
        db.document("orgs/o/lim/b").create({"n": 2})  # operation 2: lands, then fails
    assert db.raw("orgs/o/lim/b") == {"n": 2} and db.fault_fired
    db.document("orgs/o/lim/c").create({"n": 3})  # a fault fires once
    db.arm_fault(1, applied=False)
    with pytest.raises(gexc.DeadlineExceeded):
        db.document("orgs/o/lim/d").create({"n": 4})
    assert db.raw("orgs/o/lim/d") is None
    db.disarm()
    db.arm_fault(1)
    db.document("orgs/o/people_work_item/wi_x").create({"version": 1, "record": {}})  # a record write is not counted
    assert not db.fault_fired


def test_PPL_11c_FS_2_guard_fake_the_people_person_store_still_works_on_it():
    from _ppl11c_fs_lib import person, unique_org
    from tilo_api.people_firestore import firestore_people_stores

    db, org = FakeFirestore2(), unique_org()
    stores = firestore_people_stores(db)
    stores.persons.create_founder(person("u_f1", org, role="owner"))
    stores.persons.create(person("u_p1", org))
    assert [s.record["id"] for s in stores.persons.list(org)] == ["u_f1", "u_p1"]
    assert stores.persons.founded(org) is True
    assert db.limiter_docs() == {} and all(is_record_path(p) for p in db.docs)
    assert datetime.now(UTC) - timedelta(days=1) < db.server_now()
