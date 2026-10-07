"""PPL-11c-FS-2 (a), `Idempotency-Key` records on a durable store (PE-19; BQ-PPL11C-4 and -14;
API_PPL_11c_FS_2.md section 2).

The in-memory keys of PPL-11c S4 are the model: an optional key on the four creates, scoped to (principal, route, key);
the same body again is the first answer and writes nothing; another body is a 422 `idempotency_key_reused`; a refused
or failed create leaves the key free. FS-2 keeps these records in Firestore on the stores' own client, so a restart or
another instance of the service replays them, a record forgets itself after its TTL, and a failure of the store at any
step never creates twice. Rows named `[memory]` pass today and pin the model.
"""

from __future__ import annotations

import threading

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM
from _ppl11c_fs2_lib import (
    alternate_instances,
    backend_rig,
    firestore_rig,
    fresh_token,
    new_instance,
    stamped_events_of,
    work_items_titled,
)
from _ppl11c_lib import MEETING_BODY, PERSON_BODY, WORK_ITEM_BODY, at
from fastapi.testclient import TestClient

BACKENDS = ["memory", "firestore"]
CREATES = {
    "meeting": ("/v1/meetings", MEETING_BODY, PRIYA),
    "work item": ("/v1/work-items", WORK_ITEM_BODY, PRIYA),
    "person": ("/v1/people", PERSON_BODY, OWNER),
}


def _keyed(rig, path, body, key):
    return rig.client.post(path, json=body, headers={"Idempotency-Key": key})


@pytest.mark.parametrize("what", list(CREATES))
@pytest.mark.parametrize("store", BACKENDS)
def test_PPL_11c_FS_2_key_01_a_replay_is_the_first_answer_byte_for_byte_and_writes_nothing(people_rig, store, what):
    path, body, actor = CREATES[what]
    rig = backend_rig(people_rig, store)
    rig.as_user(actor)
    key = fresh_token()
    first = _keyed(rig, path, body, key)
    assert first.status_code == 201, first.text[:200]
    snapshot, events = rig.snapshot(), len(rig.events.calls)
    record_writes = None if rig.fake is None else list(rig.fake.record_writes())
    again = _keyed(rig, path, body, key)
    assert again.status_code == 201 and again.content == first.content, "the first answer, byte for byte"
    assert rig.snapshot() == snapshot, "nothing created twice"
    assert len(rig.events.calls) == events, "and nothing said twice"
    if rig.fake is not None:
        assert rig.fake.record_writes() == record_writes, "a replay writes to no people record collection"


@pytest.mark.parametrize("what", list(CREATES))
def test_PPL_11c_FS_2_key_02_a_replay_on_another_instance_is_the_first_answer_and_writes_nothing(people_rig, what):
    """A restart, or the next request landing on another instance: only Firestore is shared."""
    path, body, actor = CREATES[what]
    rig = firestore_rig(people_rig)
    rig.as_user(actor)
    key = fresh_token()
    first = _keyed(rig, path, body, key)
    assert first.status_code == 201, first.text[:200]
    new_instance(rig)
    snapshot, events, writes = rig.snapshot(), len(rig.events.calls), list(rig.fake.record_writes())
    again = _keyed(rig, path, body, key)
    assert again.status_code == 201 and again.content == first.content
    assert rig.snapshot() == snapshot and len(rig.events.calls) == events and rig.fake.record_writes() == writes


def test_PPL_11c_FS_2_key_03_the_same_key_with_another_body_is_a_422_on_every_instance(people_rig):
    rig = firestore_rig(people_rig)
    key = fresh_token()
    assert _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key).status_code == 201
    new_instance(rig)
    snapshot = rig.snapshot()
    reused = _keyed(rig, "/v1/work-items", {**WORK_ITEM_BODY, "title": "Something else"}, key)
    assert reused.status_code == 422
    assert reused.json() == {"detail": "idempotency_key_reused", "code": "idempotency_key_reused"}
    assert rig.snapshot() == snapshot


def test_PPL_11c_FS_2_key_04_a_key_never_crosses_a_principal_or_a_route_even_across_instances(people_rig):
    """The same key by another principal, on another route, with another body: three independent requests. No 422
    oracle for a key somebody else used, no replay of another route's answer."""
    rig = firestore_rig(people_rig)
    key = fresh_token()
    mine = _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key)
    assert mine.status_code == 201
    new_instance(rig)
    other_route = _keyed(rig, "/v1/meetings", MEETING_BODY, key)
    assert other_route.status_code == 201 and other_route.json()["id"].startswith("mt_"), other_route.text[:200]
    rig.as_user(SAM)
    theirs = _keyed(rig, "/v1/work-items", {**WORK_ITEM_BODY, "title": "Sam's own item"}, key)
    assert theirs.status_code == 201, "a key somebody else used is a free key, whatever the body"
    assert theirs.json()["id"] != mine.json()["id"] and theirs.json()["owner"] == SAM
    new_instance(rig)
    rig.as_user(PRIYA)
    assert _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key).content == mine.content, "each still has its own"
    assert _keyed(rig, "/v1/meetings", MEETING_BODY, key).content == other_route.content


def test_PPL_11c_FS_2_key_05_a_record_is_a_replay_for_twenty_four_hours_and_then_the_key_is_free(people_rig):
    """TTL: BQ default, 24 hours from the request's clock (`deps.get_clock`). Firestore's TTL sweeper may run late (up
    to a day), so an expired document that is still there is ignored: the key is free, whatever the body."""
    rig = firestore_rig(people_rig)
    key = fresh_token()
    first = _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key)
    assert first.status_code == 201
    rig.set_now(at(days=1, seconds=-60))
    assert _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key).content == first.content, "23 h 59 min: still the key's"
    rig.set_now(at(days=1, seconds=1))
    other = _keyed(rig, "/v1/work-items", {**WORK_ITEM_BODY, "title": "Another day, another body"}, key)
    assert other.status_code == 201, "past 24 h the key is free: not a 422 for the old body"
    assert other.json()["id"] != first.json()["id"]


def test_PPL_11c_FS_2_key_05b_after_the_ttl_the_same_key_and_body_is_a_new_request(people_rig):
    rig = firestore_rig(people_rig)
    key = fresh_token()
    first = _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key)
    assert first.status_code == 201
    rig.set_now(at(days=1, seconds=1))
    second = _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key)
    assert second.status_code == 201 and second.json()["id"] != first.json()["id"]
    assert len(work_items_titled(rig, WORK_ITEM_BODY["title"])) == 2
    assert _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key).content == second.content, "and now it is that one's"


def test_PPL_11c_FS_2_key_06_every_stored_record_expires_within_a_day_of_the_clock(people_rig):
    """A TTL policy needs a Timestamp field: the limiter's documents carry `expires_at` as a timezone-aware datetime,
    none later than 24 hours after the clock of the request that wrote it (plus a minute), and one is the key's."""
    from datetime import datetime, timedelta

    rig = firestore_rig(people_rig)
    assert _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, fresh_token()).status_code == 201
    now = datetime.fromisoformat(rig.clock.replace("Z", "+00:00"))
    docs = rig.fake.limiter_docs()
    assert docs, "a keyed create leaves its records in Firestore"
    expiries = []
    for path, doc in docs.items():
        stamp = doc.get("expires_at")
        assert isinstance(stamp, datetime) and stamp.tzinfo is not None, (path, type(stamp))
        assert now < stamp <= now + timedelta(days=1, minutes=1), (path, stamp)
        expiries.append(stamp)
    assert any(abs(stamp - (now + timedelta(days=1))) <= timedelta(minutes=1) for stamp in expiries), "the key's own"


@pytest.mark.parametrize("store", BACKENDS)
def test_PPL_11c_FS_2_key_07_a_refused_first_attempt_does_not_use_up_the_key(people_rig, store):
    rig = backend_rig(people_rig, store)
    body = {"title": "Reply to the vendor", "source": {"kind": "mail", "ref": "msg_vendor_1"}}
    key = fresh_token()
    assert _keyed(rig, "/v1/work-items", body, key).status_code == 422, "someone else's (here: nobody's) mail"
    rig.owners.owners[("mail", "msg_vendor_1")] = PRIYA
    ok = _keyed(rig, "/v1/work-items", body, key)
    assert ok.status_code == 201, ok.text[:200]
    assert _keyed(rig, "/v1/work-items", body, key).content == ok.content


def test_PPL_11c_FS_2_key_08_four_racing_retries_over_two_instances_create_one_record(people_rig):
    rig = firestore_rig(people_rig)
    alternate_instances(rig, 2)
    key, body = fresh_token(), {**WORK_ITEM_BODY, "title": "Raced once"}
    barrier, answers, guard = threading.Barrier(4), [], threading.Lock()

    def work(client: TestClient) -> None:
        barrier.wait()
        response = client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
        with guard:
            answers.append(response)

    clients = [TestClient(rig.app, raise_server_exceptions=False) for _ in range(4)]
    threads = [threading.Thread(target=work, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    codes = sorted(r.status_code for r in answers)
    assert len(codes) == 4 and set(codes) <= {201, 409, 503}, codes
    created = [r for r in answers if r.status_code == 201]
    assert created and len({r.content for r in created}) == 1, "whoever is answered is answered with the one record"
    assert len(work_items_titled(rig, "Raced once")) == 1
    later = _keyed(rig, "/v1/work-items", body, key)
    assert later.status_code == 201 and later.content == created[0].content


@pytest.mark.parametrize("applied", [False, True], ids=["fails-before-it-lands", "lands-then-fails"])
def test_PPL_11c_FS_2_key_09_a_failure_at_any_step_of_the_limiter_never_creates_twice(people_rig, applied):
    """Fault injection: for each n, the nth Firestore operation on a limiter document (a read, a query or a commit)
    fails once (or lands and then fails: the answer was lost). Whatever the first attempt answers (a created record or
    the fixed 503), the same key again ends with exactly one record and exactly one event for it, and the answers a
    caller got for it agree."""
    reached = 0
    for n in range(1, 41):
        rig = firestore_rig(people_rig)
        title, key = f"Sweep {n} {applied}", fresh_token()
        body = {**WORK_ITEM_BODY, "title": title}
        rig.fake.arm_fault(n, applied=applied)
        first = _keyed(rig, "/v1/work-items", body, key)
        fired = rig.fake.fault_fired
        rig.fake.disarm()
        reached += fired
        assert first.status_code in (201, 503), (n, first.status_code, first.text[:150])
        if first.status_code == 503:
            assert first.json() == {"detail": "unavailable"}, "a failure of the store is one fixed body"
        final = _keyed(rig, "/v1/work-items", body, key)
        assert final.status_code == 201, (n, final.status_code, final.text[:150])
        made = work_items_titled(rig, title)
        assert len(made) == 1, f"operation {n}: {len(made)} records for one key"
        assert final.json()["id"] == made[0]["id"]
        assert len(stamped_events_of(rig, made[0]["id"])) == 1, f"operation {n}: one event for the record"
        if first.status_code == 201:
            assert final.content == first.content
        if not fired:
            break
    assert reached >= 3, f"the limiter made {reached} Firestore operations on the first attempt: it is not durable"


@pytest.mark.parametrize("applied", [False, True], ids=["fails-before-it-lands", "lands-then-fails"])
def test_PPL_11c_FS_2_key_10_a_failure_while_replaying_never_creates_a_second_record(people_rig, applied):
    reached = 0
    for n in range(1, 41):
        rig = firestore_rig(people_rig)
        title, key = f"Replay sweep {n} {applied}", fresh_token()
        body = {**WORK_ITEM_BODY, "title": title}
        first = _keyed(rig, "/v1/work-items", body, key)
        assert first.status_code == 201
        rig.fake.arm_fault(n, applied=applied)
        replay = _keyed(rig, "/v1/work-items", body, key)
        fired = rig.fake.fault_fired
        rig.fake.disarm()
        reached += fired
        assert replay.status_code in (201, 503), (n, replay.status_code, replay.text[:150])
        if replay.status_code == 201:
            assert replay.content == first.content
        else:
            assert replay.json() == {"detail": "unavailable"}
        final = _keyed(rig, "/v1/work-items", body, key)
        assert final.status_code == 201 and final.content == first.content, n
        assert len(work_items_titled(rig, title)) == 1, f"operation {n}"
        if not fired:
            break
    assert reached >= 2, f"a replay made {reached} Firestore operations on limiter documents: it is not durable"


def test_PPL_11c_FS_2_key_11_a_replay_never_touches_a_people_record_collection_even_to_read_the_old_answer_twice(
    people_rig,
):
    """Replays are cheap and safe to hammer: sixty replays leave the record collections exactly as the one create left
    them (versions included), on any instance."""
    rig = firestore_rig(people_rig)
    key = fresh_token()
    first = _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key)
    assert first.status_code == 201
    snapshot, writes = rig.snapshot(), list(rig.fake.record_writes())
    for n in range(40):
        if n % 10 == 0:
            new_instance(rig)
        assert _keyed(rig, "/v1/work-items", WORK_ITEM_BODY, key).content == first.content, n
    assert rig.snapshot() == snapshot and rig.fake.record_writes() == writes
