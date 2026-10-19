"""PPL-11c-FS-2 (a), what the durable limiter and key store keep, how they fail and how a person's records are erased
(SEC-10; FR-MEM-09; PRD 16.5; PE-12 "ids only"; API_PPL_11c_FS_2.md section 3).

* The documents hold no personal data: no uid, no raw `Idempotency-Key`, no request or answer text; a key is stored
  hashed with its principal and route; every document is under `orgs/{deps.ORG_ID}/`, outside the people record
  collections, and carries `expires_at` (a Timestamp, so a TTL policy can delete it) no later than a day after the
  clock of the request that wrote it.
* Fail closed: when the store of the limiter is down, every people POST is the one fixed 503 `{"detail":
  "unavailable"}` (never a 500, never "let it through"), before anything is written; reads do not touch the limiter;
  nothing in the answer or the logs carries the library's error text, a key or a body.
* Erasure (FR-MEM-09): `limits_of(stores).erase_person(org_id, user_id)` deletes every counter and key record of that
  person, none of anyone else's, idempotently, and answers how many documents it deleted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM
from _ppl11c_fs2_fake import RECORD_COLLECTIONS, SENTINEL, is_record_path
from _ppl11c_fs2_lib import docs_text, firestore_rig, fresh_token
from _ppl11c_lib import MEETING_BODY, PERSON_BODY, WORK_ITEM_BODY, WRITES_PER_MINUTE

ROUTES = {  # route name -> (path, body, the person who may make it)
    "create work item": ("/v1/work-items", WORK_ITEM_BODY, PRIYA),
    "create meeting": ("/v1/meetings", MEETING_BODY, PRIYA),
    "create person": ("/v1/people", PERSON_BODY, OWNER),
    "done": ("/v1/work-items/wi_own1/done", {}, PRIYA),
    "edit": ("/v1/work-items/wi_own1/edit", {"title": "Water the ferns"}, PRIYA),
    "delete meeting": ("/v1/meetings/mt_q4_plan/delete", {}, OWNER),
}


def _down(path: str) -> bool:
    return not is_record_path(path)


def test_PPL_11c_FS_2_store_01_the_documents_hold_no_personal_data_no_key_and_no_text(people_rig):
    rig = firestore_rig(people_rig)
    marker, key_item, key_person, key_meeting = (fresh_token(x) for x in ("pii", "ki", "kp", "km"))
    keys = (key_item, key_person, key_meeting)
    rig.as_user(PRIYA)
    item = {**WORK_ITEM_BODY, "title": f"Audit {marker}", "due_text": f"before {marker}"}
    for _ in range(2):  # a create and its replay
        assert rig.client.post("/v1/work-items", json=item, headers={"Idempotency-Key": key_item}).status_code == 201
    meeting = {**MEETING_BODY, "title": f"Sync {marker}"}
    assert rig.client.post("/v1/meetings", json=meeting, headers={"Idempotency-Key": key_meeting}).status_code == 201
    rig.as_user(OWNER)
    person = {**PERSON_BODY, "display_name": f"Name {marker}", "email": f"{marker}@example.com"}
    assert rig.client.post("/v1/people", json=person, headers={"Idempotency-Key": key_person}).status_code == 201
    docs = rig.fake.limiter_docs()
    assert docs, "the counters and keys are in Firestore"
    text = docs_text(docs)
    for what, secret in {
        "marker": marker,
        "priya": PRIYA,
        "owner": OWNER,
        **{f"key {i}": k for i, k in enumerate(keys)},
    }.items():
        assert secret not in text, f"a stored document holds {what}"
    assert "example.com" not in text


def test_PPL_11c_FS_2_store_02_documents_live_under_the_org_and_outside_the_people_record_collections(people_rig):
    rig = firestore_rig(people_rig)
    created = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": fresh_token()})
    assert created.status_code == 201
    docs = rig.fake.limiter_docs()
    assert docs
    for path in docs:
        parts = path.split("/")
        assert parts[:2] == ["orgs", rig.org] and len(parts) >= 4, path
        assert parts[2] not in RECORD_COLLECTIONS, f"{path} is inside a people record collection"
    assert all(s.record["org_id"] == rig.org for s in rig.real.work_items.list(rig.org)), "the stores are untouched"


def test_PPL_11c_FS_2_store_03_a_counter_expires_no_sooner_than_the_minute_it_counts_and_within_a_day(people_rig):
    """`expires_at` is a timezone-aware datetime, so a Firestore TTL policy on it can delete the document; a counter
    must outlive the minute it counts (or the sweeper would forget attempts that still count) and nothing is kept for
    more than a day."""
    rig = firestore_rig(people_rig)
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201  # no key: the counter alone
    now = datetime.fromisoformat(rig.clock.replace("Z", "+00:00"))
    counter_only = rig.fake.limiter_docs()
    assert counter_only
    for path, doc in counter_only.items():
        stamp = doc.get("expires_at")
        assert isinstance(stamp, datetime) and stamp.tzinfo is not None, (path, type(stamp))
        assert now + timedelta(seconds=60) <= stamp <= now + timedelta(days=1, minutes=1), (path, stamp)


def test_PPL_11c_FS_2_store_04_nothing_of_a_key_a_body_or_the_store_error_reaches_the_logs(people_rig, caplog):
    rig = firestore_rig(people_rig)
    caplog.set_level(logging.DEBUG)
    key, marker = fresh_token("logkey"), fresh_token("logbody")
    body = {**WORK_ITEM_BODY, "title": f"Title {marker}"}
    for _ in range(2):
        assert rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key}).status_code == 201
    rig.fake.outage = _down
    down = rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
    assert down.status_code == 503
    for secret in (key, marker, SENTINEL):
        assert secret not in caplog.text, "a log line carries a key, a body or a library error"
        assert secret not in down.text


@pytest.mark.parametrize("route", list(ROUTES))
def test_PPL_11c_FS_2_store_05_a_store_outage_is_the_one_fixed_503_and_changes_nothing(people_rig, route, caplog):
    path, body, actor = ROUTES[route]
    rig = firestore_rig(people_rig)
    rig.as_user(actor)
    caplog.set_level(logging.DEBUG)
    snapshot, events, writes = rig.snapshot(), len(rig.events.calls), len(rig.fake.record_writes())
    key = fresh_token()
    headers = {"Idempotency-Key": key} if route.startswith("create") else {}
    rig.fake.outage = _down
    refused = rig.client.post(path, json=body, headers=headers)
    assert refused.status_code == 503, (refused.status_code, refused.text[:200])
    assert refused.json() == {"detail": "unavailable"}, "one fixed body"
    assert refused.headers["cache-control"] == "no-store"
    assert SENTINEL not in refused.text and SENTINEL not in caplog.text
    assert key not in caplog.text
    assert rig.snapshot() == snapshot and len(rig.events.calls) == events, "nothing was written, nothing said"
    assert len(rig.fake.record_writes()) == writes
    rig.fake.outage = None
    assert rig.client.post(path, json=body, headers=headers).status_code in (200, 201), "and it works again"


def test_PPL_11c_FS_2_store_06_reads_do_not_depend_on_the_limiter_store(people_rig):
    rig = firestore_rig(people_rig)
    rig.fake.outage = _down
    assert rig.get("/v1/work-items/wi_own1").status_code == 200
    assert rig.get("/v1/work-items").status_code == 200
    assert rig.plate().status_code == 200


def test_PPL_11c_FS_2_store_07_an_outage_never_lets_a_write_through_and_a_key_survives_it(people_rig):
    """Fail closed, and the key is not poisoned: the create refused during the outage is not remembered as done."""
    rig = firestore_rig(people_rig)
    key, body = fresh_token(), {**WORK_ITEM_BODY, "title": "Once, after the outage"}
    rig.fake.outage = _down
    assert rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key}).status_code == 503
    rig.fake.outage = None
    first = rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    again = rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
    assert again.content == first.content
    assert len([s for s in rig.real.work_items.list(rig.org) if s.record["title"] == body["title"]]) == 1


def test_PPL_11c_FS_2_store_08_erase_person_deletes_their_counter_and_keys_and_nobody_elses(people_rig):
    from tilo_api.people_limits import limits_of

    rig = firestore_rig(people_rig)
    priya_key, sam_key = fresh_token("pk"), fresh_token("sk")
    mine = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": priya_key})
    assert mine.status_code == 201
    for n in range(WRITES_PER_MINUTE - 1):
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201, n
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 429, "she is at her cap"
    rig.as_user(SAM)
    sam_item = {**WORK_ITEM_BODY, "title": "Sam's"}
    theirs = rig.client.post("/v1/work-items", json=sam_item, headers={"Idempotency-Key": sam_key})
    assert theirs.status_code == 201
    limits, before = limits_of(rig.stores), rig.fake.limiter_docs()
    removed = limits.erase_person(rig.org, PRIYA)
    after = rig.fake.limiter_docs()
    assert removed >= 1 and len(before) - len(after) == removed, (removed, len(before), len(after))
    assert after and set(after) < set(before), "Sam's documents are still there, and none was added"
    assert PRIYA not in docs_text(after)
    assert limits.erase_person(rig.org, PRIYA) == 0, "idempotent"
    assert rig.client.post("/v1/work-items", json=sam_item, headers={"Idempotency-Key": sam_key}).content == (
        theirs.content
    ), "nobody else's key moved"
    rig.as_user(PRIYA)
    fresh = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": priya_key})
    assert fresh.status_code == 201 and fresh.json()["id"] != mine.json()["id"], "her key and her count are gone"


def test_PPL_11c_FS_2_store_09_erase_person_refuses_a_malformed_id_and_deletes_nothing(people_rig):
    from tilo_api.people_limits import limits_of

    rig = firestore_rig(people_rig)
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201
    before = rig.fake.limiter_docs()
    limits = limits_of(rig.stores)
    assert callable(getattr(limits, "erase_person", None)), "the erase hook is missing"
    for org, user in ((rig.org, "not-a-user"), (rig.org, ""), (rig.org, "u_../x"), ("../..", PRIYA), ("", PRIYA)):
        with pytest.raises(Exception):  # noqa: B017, PT011 - the type is the builder's: a refusal, never a delete
            limits.erase_person(org, user)
    assert rig.fake.limiter_docs() == before


def test_PPL_11c_FS_2_store_10_an_erase_that_failed_can_be_run_again_to_completion(people_rig):
    """A store failure during an erase raises (the erase route must report it, FR-MEM-09: a partial erase is not
    reported as done); the same call again finishes the job and leaves none of the person's documents."""
    from tilo_api.people_limits import limits_of

    rig = firestore_rig(people_rig)
    for _ in range(3):
        created = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": fresh_token()})
        assert created.status_code == 201
    limits = limits_of(rig.stores)
    assert callable(getattr(limits, "erase_person", None)), "the erase hook is missing"
    rig.fake.arm_fault(1, applied=False)
    with pytest.raises(Exception):  # noqa: B017, PT011 - raising is the contract; the type is the builder's
        limits.erase_person(rig.org, PRIYA)
    assert rig.fake.fault_fired, "an erase reads or writes Firestore"
    rig.fake.disarm()
    assert limits.erase_person(rig.org, PRIYA) >= 1
    assert rig.fake.limiter_docs() == {}
