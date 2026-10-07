"""PPL-11c-FS-2 (a), the write limiter on a durable store (SEC-10; BQ-PPL11C-2 and -13; API_PPL_11c_FS_2.md section 1).

The in-memory limiter of PPL-11c S4 is the model: 60 POST attempts a minute per principal, every attempt that gets past
sign-in counts (a refused one and a 413 too, a read and a 429 itself do not), a sliding minute of the `deps.get_clock`
seam, `Retry-After` in whole seconds to the oldest counted attempt. FS-2 moves the counter onto the people stores' own
Firestore client so a restart or a second instance of the service neither forgets it nor has a count of its own.

Rows named `[memory]` run the same scenario on the in-memory limiter and pass today: they pin that the durable one
behaves like it. The `[firestore]` rows run on `FakeFirestore2` (serializable transactions, no emulator). Seam: the
limiter of a `PeopleStores` built by `firestore_people_stores(client)` / `open_people_stores(env, client_factory=)` is
`people_limits.limits_of(stores)`, backed by that same client (one client, no second composition root); the org of its
documents is `deps.ORG_ID`.
"""

from __future__ import annotations

import math
import threading
from collections import deque
from unittest import mock

import pytest
from _ppl11a_lib import PRIYA, SAM, run_threads
from _ppl11c_fs2_fake import FakeFirestore2
from _ppl11c_fs2_lib import alternate_instances, backend_rig, firestore_rig, new_instance
from _ppl11c_lib import MAX_BODY_BYTES, WORK_ITEM_BODY, WRITES_PER_MINUTE, at
from fastapi import HTTPException
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

BACKENDS = ["memory", "firestore"]


def _post(rig):
    return rig.post("/v1/work-items", WORK_ITEM_BODY)


def _fill(rig, count=WRITES_PER_MINUTE):
    for n in range(count):
        assert _post(rig).status_code == 201, n


@pytest.mark.parametrize("store", BACKENDS)
def test_PPL_11c_FS_2_limit_01_the_sixty_first_attempt_in_a_minute_is_a_429_with_retry_after(people_rig, store):
    rig = backend_rig(people_rig, store)
    _fill(rig)
    over = _post(rig)
    assert over.status_code == 429 and over.json() == {"detail": "rate_limited", "code": "rate_limited"}, over.text[
        :200
    ]
    assert 1 <= int(over.headers["retry-after"]) <= 60
    assert rig.plate().status_code == 200, "a read is never counted"
    rig.as_user(SAM)
    assert _post(rig).status_code == 201, "another principal has a count of its own"
    rig.as_user(PRIYA)
    rig.set_now(at(seconds=61))
    assert _post(rig).status_code == 201, "a minute later she may write again"


def test_PPL_11c_FS_2_limit_02_two_instances_of_the_service_share_one_count(people_rig):
    """Sixty attempts spread over two instances (every other request on the other one) use the whole minute: the 61st,
    and the 62nd on the other instance, are refused. A count kept per instance would let 120 through."""
    rig = firestore_rig(people_rig)
    alternate_instances(rig, 2)
    _fill(rig)
    assert [_post(rig).status_code for _ in range(2)] == [429, 429]


def test_PPL_11c_FS_2_limit_03_a_restart_forgets_nothing(people_rig):
    rig = firestore_rig(people_rig)
    _fill(rig)
    new_instance(rig)  # the process restarted: new adapter objects, the same Firestore
    assert _post(rig).status_code == 429
    new_instance(rig)
    assert _post(rig).status_code == 429


@pytest.mark.parametrize("store", BACKENDS)
def test_PPL_11c_FS_2_limit_04_the_window_slides_a_minute_of_the_injected_clock(people_rig, store):
    """Thirty attempts at t=0 and thirty at t=59 use the minute; at t=61 the first thirty have left it and exactly
    thirty more are allowed (a fixed window that reset at t=60 would allow sixty)."""
    rig = backend_rig(people_rig, store)
    _fill(rig, 30)
    rig.set_now(at(seconds=59))
    _fill(rig, 30)
    assert _post(rig).status_code == 429, "59 seconds after the first attempt is inside the minute"
    rig.set_now(at(seconds=61))
    assert [_post(rig).status_code for _ in range(31)] == [201] * 30 + [429]


@pytest.mark.parametrize("store", BACKENDS)
def test_PPL_11c_FS_2_limit_05_an_oversize_body_counts_and_a_429_does_not(people_rig, store):
    rig = backend_rig(people_rig, store)
    _fill(rig, WRITES_PER_MINUTE - 1)
    big = rig.client.post(
        "/v1/work-items", content=b" " * (MAX_BODY_BYTES + 1), headers={"content-type": "application/json"}
    )
    assert big.status_code == 413, "BQ-PPL11C-13: the 413 is the 60th attempt"
    assert _post(rig).status_code == 429


@pytest.mark.parametrize("store", BACKENDS)
def test_PPL_11c_FS_2_limit_06_a_refused_attempt_is_not_counted_so_it_never_extends_the_wait(people_rig, store):
    rig = backend_rig(people_rig, store)
    _fill(rig)
    rig.set_now(at(seconds=30))
    for n in range(WRITES_PER_MINUTE):  # sixty refusals: counted, they would keep her out until t=90
        assert _post(rig).status_code == 429, n
    rig.set_now(at(seconds=61))
    assert _post(rig).status_code == 201


@pytest.mark.parametrize("store", BACKENDS)
def test_PPL_11c_FS_2_limit_07_retry_after_is_whole_seconds_to_the_oldest_counted_attempt(people_rig, store):
    rig = backend_rig(people_rig, store)
    _fill(rig)
    rig.set_now(at(seconds=20))
    refused = _post(rig)
    assert refused.status_code == 429 and refused.headers["retry-after"] == "40"
    rig.set_now(at(seconds=59, minutes=0))
    assert _post(rig).headers["retry-after"] == "1"


@pytest.mark.parametrize("store", BACKENDS)
def test_PPL_11c_FS_2_limit_08_every_people_post_route_shares_the_principals_one_count(people_rig, store):
    """`write_limit` is a dependency of every people POST route, the creates and the actions alike: sixty mixed
    attempts, refused ones included, use the minute."""
    rig = backend_rig(people_rig, store)
    for n in range(WRITES_PER_MINUTE):
        path = ("/v1/work-items", "/v1/work-items/wi_own1/done", "/v1/work-items/wi_never_made/edit")[n % 3]
        assert rig.post(path, WORK_ITEM_BODY if n % 3 == 0 else {}).status_code in (201, 200, 404, 409, 422), n
    assert _post(rig).status_code == 429


# --- the same limiter called directly, against a model of the sliding minute ------------------------------------------


def _limits(store: str, db: FakeFirestore2):
    from tilo_api.people_firestore import firestore_people_stores
    from tilo_api.people_limits import Limits, limits_of

    return Limits() if store == "memory" else limits_of(firestore_people_stores(db))


def _hit(limits, user: str, now: float) -> tuple[int, str | None]:
    try:
        limits.attempt(user, now)
    except HTTPException as exc:
        return exc.status_code, (exc.headers or {}).get("Retry-After")
    return 201, None


GAPS = st.sampled_from([0.0, 0.0, 0.5, 0.5, 1.0, 3.0, 25.0, 61.0])  # seconds, exactly representable


@pytest.mark.parametrize("store", BACKENDS)
@settings(max_examples=25, deadline=None)
@given(steps=st.lists(st.tuples(st.integers(0, 2), GAPS), min_size=1, max_size=220))
def test_PPL_11c_FS_2_limit_09_never_more_than_the_cap_in_any_minute_and_exactly_the_sliding_model(store, steps):
    """SEC-10 as an invariant: at most 60 attempts are accepted for a principal in any window of a minute; an attempt
    is accepted exactly when fewer than 60 accepted ones are younger than a minute; the refusal says how long, in
    whole seconds, to the oldest of them. Principals do not touch each other."""
    from tilo_api import deps

    with mock.patch.object(deps, "ORG_ID", "org_prop"):
        limits, now = _limits(store, FakeFirestore2()), 1_000_000.0
        accepted: dict[str, deque[float]] = {}
        for who, gap in steps:
            now, user = now + gap, f"u_p{who}"
            hits = accepted.setdefault(user, deque())
            while hits and hits[0] <= now - 60:
                hits.popleft()
            status, retry_after = _hit(limits, user, now)
            if len(hits) < WRITES_PER_MINUTE:
                assert status == 201, (user, now, len(hits))
                hits.append(now)
            else:
                assert status == 429, (user, now)
                assert retry_after == str(min(60, max(1, math.ceil(hits[0] + 60 - now))))
            assert len(hits) <= WRITES_PER_MINUTE


def test_PPL_11c_FS_2_limit_10_the_limiter_uses_the_one_client_the_stores_were_built_with():
    """FS-1b's `open_people_stores(env, client_factory=)` is the one door: the factory is called once, for the stores,
    and the limiter writes through that same client (no `firestore.Client(...)` of its own, no second factory)."""
    from google.cloud import firestore
    from tilo_api import deps
    from tilo_api.people_firestore import open_people_stores
    from tilo_api.people_limits import limits_of

    made, fake = [], FakeFirestore2()

    def factory(project: str):
        made.append(project)
        return fake

    def no_other_client(*_a, **_k):
        raise AssertionError("the limiter built a Firestore client of its own")

    env = {"TILO_PEOPLE_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "demo-tilo"}
    with (
        mock.patch.object(firestore, "Client", no_other_client),
        mock.patch.object(deps, "ORG_ID", "org_one"),
    ):
        stores = open_people_stores(env, client_factory=factory)
        limits_of(stores).attempt(PRIYA, 1_000_000.0)
    assert made == ["demo-tilo"]
    assert fake.limiter_docs(), "the counter is in the client the stores were built with"


def test_PPL_11c_FS_2_limit_11_a_limiter_of_other_stores_does_not_see_this_ones_count():
    """Two separate installs over two separate databases (the tests of one process): no module state."""
    from tilo_api import deps
    from tilo_api.people_firestore import firestore_people_stores
    from tilo_api.people_limits import limits_of

    with mock.patch.object(deps, "ORG_ID", "org_one"):
        first, second = firestore_people_stores(FakeFirestore2()), firestore_people_stores(FakeFirestore2())
        for _ in range(WRITES_PER_MINUTE):
            assert _hit(limits_of(first), PRIYA, 1_000_000.0)[0] == 201
        assert _hit(limits_of(first), PRIYA, 1_000_000.0)[0] == 429
        assert _hit(limits_of(second), PRIYA, 1_000_000.0)[0] == 201


def test_PPL_11c_FS_2_limit_12_racing_attempts_never_get_more_than_the_cap_through():
    """Four threads, twenty attempts each, one principal, one instant, directly on the limiter: at most sixty are
    accepted (a read-then-write counter without a transaction lets some past), the rest are 429 or a clean refusal;
    when the store never failed, exactly sixty are accepted."""
    from tilo_api import deps
    from tilo_api.people_firestore import firestore_people_stores
    from tilo_api.people_limits import limits_of

    with mock.patch.object(deps, "ORG_ID", "org_race"):
        limits = limits_of(firestore_people_stores(FakeFirestore2()))

        def work(_: int) -> list[int]:
            return [_hit(limits, PRIYA, 1_000_000.0)[0] for _ in range(20)]

        codes = [code for chunk in run_threads(4, work) for code in chunk]
    assert codes.count(201) <= WRITES_PER_MINUTE, codes.count(201)
    assert set(codes) <= {201, 429, 503}, set(codes)
    if 503 not in codes:
        assert codes.count(201) == WRITES_PER_MINUTE


def test_PPL_11c_FS_2_limit_13_racing_requests_on_two_instances_never_get_more_than_the_cap_through(people_rig):
    rig = firestore_rig(people_rig)
    alternate_instances(rig, 2)
    barrier, results, guard = threading.Barrier(4), [], threading.Lock()

    def work(client: TestClient) -> None:
        barrier.wait()
        for _ in range(20):
            response = client.post("/v1/work-items", json=WORK_ITEM_BODY)
            with guard:
                results.append(response)

    clients = [TestClient(rig.app, raise_server_exceptions=False) for _ in range(4)]
    threads = [threading.Thread(target=work, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    codes = [r.status_code for r in results]
    assert len(codes) == 80 and set(codes) <= {201, 429, 503}, sorted(set(codes))
    assert codes.count(201) <= WRITES_PER_MINUTE
    assert all(r.json() == {"detail": "unavailable"} for r in results if r.status_code == 503)
    if 503 not in codes:
        assert codes.count(201) == WRITES_PER_MINUTE
