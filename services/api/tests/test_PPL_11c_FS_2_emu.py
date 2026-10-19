"""PPL-11c-FS-2 on the real Firestore emulator (ADR-0003): the limiter, the key records and the erase hook against the
server's own transactions and Timestamp type, not the stand-in. Spec: `API_PPL_11c_FS_2.md` section 5.

Every test here is `@pytest.mark.emulator` and SKIPS unless `FIRESTORE_EMULATOR_HOST` is already set by whoever owns an
emulator: this file never starts one (the heavy-run lock belongs to the cloud lane). An org is unique per test, so no
test clears the emulator. A racing test uses three callers: see `_ppl11c_fs_lib.racers`.
"""

from __future__ import annotations

import threading
from datetime import datetime
from unittest import mock

import pytest
from _ppl11a_lib import PRIYA, SAM
from _ppl11c_fs2_lib import alternate_instances, emulator_host, fresh_token, new_instance
from _ppl11c_fs_lib import DEMO_PROJECT, person, unique_org
from _ppl11c_lib import WORK_ITEM_BODY, WRITES_PER_MINUTE
from fastapi import HTTPException
from fastapi.testclient import TestClient

emulator = pytest.mark.emulator


@pytest.fixture
def emu_client():
    if not emulator_host():
        pytest.skip("FIRESTORE_EMULATOR_HOST is not set: FS-2 never starts an emulator itself")
    from google.cloud import firestore

    return firestore.Client(project=DEMO_PROJECT)


def _emu_rig(people_rig, client):
    from tilo_api.people_firestore import firestore_people_stores

    org = unique_org()
    rig = people_rig(org=org)
    stores = firestore_people_stores(client)
    rig.real = rig.stores = stores
    rig.fake = client
    stores.persons.create(person(PRIYA, org, email="priya@example.com"))
    stores.persons.create(person(SAM, org, email="sam@example.com"))
    rig.as_user(PRIYA)
    return rig


def _hit(limits, user: str, now: float) -> int:
    try:
        limits.attempt(user, now)
    except HTTPException as exc:
        return exc.status_code
    return 201


@emulator
def test_PPL_11c_FS_2_emu_01_two_clients_share_one_count_on_the_emulator(people_rig, emu_client):
    """Two instances with a Firestore client each (nothing shared but the database): thirty attempts on each use the
    minute, the next one on either is a 429."""
    from google.cloud import firestore
    from tilo_api.people_firestore import firestore_people_stores
    from tilo_api.people_limits import limits_of

    rig = _emu_rig(people_rig, emu_client)
    first = limits_of(firestore_people_stores(emu_client))
    second = limits_of(firestore_people_stores(firestore.Client(project=DEMO_PROJECT)))
    now = 1_000_000.0
    for n in range(WRITES_PER_MINUTE // 2):
        assert _hit(first, PRIYA, now) == 201 and _hit(second, PRIYA, now) == 201, n
    assert _hit(first, PRIYA, now) == 429 and _hit(second, PRIYA, now) == 429
    assert _hit(second, SAM, now) == 201, "another principal"
    assert rig.org


@emulator
def test_PPL_11c_FS_2_emu_02_the_sixty_first_post_is_a_429_across_two_instances_over_http(people_rig, emu_client):
    rig = _emu_rig(people_rig, emu_client)
    alternate_instances(rig, 2)
    for n in range(WRITES_PER_MINUTE):
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201, n
    over = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert over.status_code == 429 and 1 <= int(over.headers["retry-after"]) <= 60


@emulator
def test_PPL_11c_FS_2_emu_03_a_replay_on_another_instance_is_the_first_answer_and_creates_nothing(
    people_rig, emu_client
):
    rig = _emu_rig(people_rig, emu_client)
    key, body = fresh_token(), {**WORK_ITEM_BODY, "title": "Replayed on the emulator"}
    first = rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text[:200]
    new_instance(rig)
    again = rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
    assert again.status_code == 201 and again.content == first.content
    assert len([s for s in rig.real.work_items.list(rig.org) if s.record["title"] == body["title"]]) == 1
    other = rig.client.post("/v1/work-items", json={**body, "title": "Another"}, headers={"Idempotency-Key": key})
    assert other.status_code == 422 and other.json()["code"] == "idempotency_key_reused"


@emulator
def test_PPL_11c_FS_2_emu_04_three_racing_retries_over_two_instances_create_one_record(people_rig, emu_client):
    rig = _emu_rig(people_rig, emu_client)
    alternate_instances(rig, 2)
    key, body = fresh_token(), {**WORK_ITEM_BODY, "title": "Raced on the emulator"}
    barrier, codes, guard = threading.Barrier(3), [], threading.Lock()

    def work(client: TestClient) -> None:
        barrier.wait()
        response = client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
        with guard:
            codes.append(response.status_code)

    clients = [TestClient(rig.app, raise_server_exceptions=False) for _ in range(3)]
    threads = [threading.Thread(target=work, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=240)
    assert set(codes) <= {201, 409, 503}, codes
    final = None
    for _ in range(3):  # the emulator's lock timeouts may have answered 503 to every racer: ask again, one by one
        final = rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
        if final.status_code == 201:
            break
    assert final is not None and final.status_code == 201
    assert len([s for s in rig.real.work_items.list(rig.org) if s.record["title"] == body["title"]]) == 1


@emulator
def test_PPL_11c_FS_2_emu_05_the_stored_documents_carry_a_real_timestamp_expiry_and_no_personal_data(
    people_rig, emu_client
):
    from _ppl11c_fs2_fake import is_record_path
    from _ppl11c_fs2_lib import docs_text

    rig = _emu_rig(people_rig, emu_client)
    key = fresh_token()
    assert rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key}).status_code == 201
    docs = {}
    for snap in emu_client.collection_group("people_limits").stream():  # the name is the builder's: fall back below
        docs[snap.reference.path] = snap.to_dict()
    if not docs:
        for collection in emu_client.document(f"orgs/{rig.org}").collections():
            if not is_record_path(f"orgs/{rig.org}/{collection.id}/x"):
                docs.update({s.reference.path: s.to_dict() for s in collection.stream()})
    assert docs, "the counter and the key are in Firestore under orgs/{org}/"
    for path, doc in docs.items():
        assert path.startswith(f"orgs/{rig.org}/"), path
        assert isinstance(doc.get("expires_at"), datetime) and doc["expires_at"].tzinfo is not None, path
    text = docs_text(docs)
    assert PRIYA not in text and key not in text


@emulator
def test_PPL_11c_FS_2_emu_06_erase_person_deletes_their_documents_and_only_theirs(people_rig, emu_client):
    from tilo_api.people_limits import limits_of

    rig = _emu_rig(people_rig, emu_client)
    key_p, key_s = fresh_token(), fresh_token()
    mine = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key_p})
    assert mine.status_code == 201
    rig.as_user(SAM)
    theirs = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key_s})
    assert theirs.status_code == 201
    limits = limits_of(rig.stores)
    assert limits.erase_person(rig.org, PRIYA) >= 1
    assert limits.erase_person(rig.org, PRIYA) == 0
    assert rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key_s}).content == (
        theirs.content
    )
    rig.as_user(PRIYA)
    again = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key_p})
    assert again.status_code == 201 and again.json()["id"] != mine.json()["id"]


@emulator
def test_PPL_11c_FS_2_emu_07_the_limiter_builds_no_client_of_its_own_on_the_emulator(people_rig, emu_client):
    from google.cloud import firestore

    rig = _emu_rig(people_rig, emu_client)

    def no_client(*_a, **_k):
        raise AssertionError("a second Firestore client was built")

    with mock.patch.object(firestore, "Client", no_client):
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201
        new_instance(rig)
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201
