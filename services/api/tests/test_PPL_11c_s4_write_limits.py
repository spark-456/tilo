"""PPL-11c slice 4: limits on the people writes (PPL-11a follow-ups #464, #462; SEC-09; API_PPL_11c.md section 7).

* A body over 32,768 bytes is a 413 `body_too_large`, decided before the whole body is read (by `Content-Length` when
  it is declared, by counting while streaming when it is not), on every people POST route.
* `Idempotency-Key` on the four creates (meeting, person, work item, first person): the same principal and key with
  the same body again is the first answer, byte for byte, with nothing created twice; with a different body it is a 422
  `idempotency_key_reused`; another principal's key is another key; a refused first attempt does not poison the key.
* At most 60 writes a minute per principal on the people POST routes (every attempt that gets past sign-in counts,
  refused ones too; reads do not): the 61st is a 429 `rate_limited` with `Retry-After` seconds. The clock is
  `deps.get_clock`, and the counter belongs to the install's people stores, not to module state.
* Writes list no whole-org directory: the actor's own record is read by id.
* Every answer carries `Cache-Control: no-store`, the gate's 403 and a validation 422 included.
* Dev mode's CORS lets the browser send `Idempotency-Key` and read `Retry-After`.
"""

from __future__ import annotations

import json

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM, fixture_case, run_threads
from _ppl11c_lib import (
    MAX_BODY_BYTES,
    MEETING_BODY,
    PERSON_BODY,
    WORK_ITEM_BODY,
    WRITES_PER_MINUTE,
    at,
    meeting_rig,
    padded,
    stream_post,
    work_rig,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

KEY = {"Idempotency-Key": "retry-key-0001"}
BODY_ROUTES = {
    "create meeting": "/v1/meetings",
    "create person": "/v1/people",
    "create work item": "/v1/work-items",
    "first person": "/v1/people/first",
    "confirm meeting": "/v1/meetings/mt_q4_plan/confirm",
    "confirm item": "/v1/work-items/wi_launch_note/confirm",
    "edit item": "/v1/work-items/wi_rate_sheet/edit",
    "done": "/v1/work-items/wi_rate_sheet/done",
    "snooze": "/v1/work-items/wi_rate_sheet/snooze",
    "reopen": "/v1/work-items/wi_rate_sheet/reopen",
    "not mine": "/v1/work-items/wi_rate_sheet/not-mine",
    "put back": "/v1/work-items/wi_rate_sheet/put-back",
    "edit meeting": "/v1/meetings/mt_q4_plan/edit",
    "delete meeting": "/v1/meetings/mt_q4_plan/delete",
    "meeting world": "/v1/meetings/mt_q4_plan/world",
    "add membership": "/v1/people/u_priya/memberships",
    "remove membership": "/v1/people/u_priya/memberships/remove",
    "role": "/v1/people/u_priya/role",
}


# --- the body cap ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", list(BODY_ROUTES.values()), ids=list(BODY_ROUTES))
def test_PPL_11c_s4_SEC_09_an_oversize_body_is_a_413_and_the_rest_of_it_is_never_read(people_rig, path):
    """A client that keeps sending is stopped after the cap: the app asked for at most the cap plus one read-ahead
    chunk of a 5 MB stream, and a declared `Content-Length` over the cap is refused before any body is read."""
    rig = meeting_rig(people_rig)
    before = rig.snapshot()
    status, consumed, headers, text = stream_post(rig.app, path, total_bytes=5_000_000)
    assert status == 413 and json.loads(text) == {"detail": "body_too_large"}, (status, text[:120])
    assert consumed <= MAX_BODY_BYTES + 64 * 1024, f"the app read {consumed} bytes of a body it was going to refuse"
    status, consumed, headers, text = stream_post(rig.app, path, total_bytes=10, declared_length=50_000_000)
    assert status == 413 and consumed <= 4096, "a declared length over the cap is refused before reading"
    assert rig.snapshot() == before


def test_PPL_11c_s4_SEC_09_a_body_of_exactly_the_cap_is_read_and_one_byte_more_is_not(people_rig):
    rig = work_rig(people_rig)
    at_cap = rig.client.post(
        "/v1/meetings", content=padded(MEETING_BODY, MAX_BODY_BYTES), headers={"content-type": "application/json"}
    )
    assert at_cap.status_code == 201, (at_cap.status_code, at_cap.text[:200])
    over = rig.client.post(
        "/v1/meetings", content=padded(MEETING_BODY, MAX_BODY_BYTES + 1), headers={"content-type": "application/json"}
    )
    assert over.status_code == 413 and over.json() == {"detail": "body_too_large"}


# --- Idempotency-Key on creates -------------------------------------------------------------------------------------

CREATES = {
    "meeting": ("/v1/meetings", MEETING_BODY, PRIYA),
    "work item": ("/v1/work-items", WORK_ITEM_BODY, PRIYA),
    "person": ("/v1/people", PERSON_BODY, OWNER),
}


@pytest.mark.parametrize("what", list(CREATES))
def test_PPL_11c_s4_PE_19_a_retry_with_the_same_key_and_body_is_the_first_answer_and_creates_nothing(people_rig, what):
    path, body, actor = CREATES[what]
    rig = work_rig(people_rig)
    rig.as_user(actor)
    first = rig.client.post(path, json=body, headers=KEY)
    assert first.status_code == 201, first.text[:200]
    snapshot = rig.snapshot()
    again = rig.client.post(path, json=body, headers=KEY)
    assert again.status_code == 201 and again.content == first.content, "the first answer, byte for byte"
    assert rig.snapshot() == snapshot, "nothing created twice"


@pytest.mark.parametrize("what", list(CREATES))
def test_PPL_11c_s4_PE_19_eight_racing_retries_with_one_key_create_one_record(people_rig, what):
    path, body, actor = CREATES[what]
    rig = work_rig(people_rig)
    rig.as_user(actor)
    store = {"meeting": "meetings", "work item": "work_items", "person": "persons"}[what]
    count = len(getattr(rig.real, store).list(rig.org))

    def post(_: int):
        with TestClient(rig.app, raise_server_exceptions=False) as client:
            return client.post(path, json=body, headers=KEY)

    responses = run_threads(8, post)
    assert {r.status_code for r in responses} == {201}, [r.status_code for r in responses]
    assert len({r.content for r in responses}) == 1
    assert len(getattr(rig.real, store).list(rig.org)) == count + 1


def test_PPL_11c_s4_PE_19_the_same_key_with_another_body_is_refused_and_another_principal_has_its_own_keys(people_rig):
    rig = work_rig(people_rig)
    first = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert first.status_code == 201
    snapshot = rig.snapshot()
    reused = rig.client.post("/v1/work-items", json={**WORK_ITEM_BODY, "title": "Something else"}, headers=KEY)
    assert reused.status_code == 422 and reused.json()["code"] == "idempotency_key_reused", reused.text[:200]
    assert rig.snapshot() == snapshot
    rig.as_user(SAM)
    theirs = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert theirs.status_code == 201 and theirs.json()["id"] != first.json()["id"], "no oracle across principals"
    assert theirs.json()["owner"] == SAM


def test_PPL_11c_s4_PE_19_without_a_key_nothing_is_deduplicated_and_a_bad_key_is_a_422(people_rig):
    rig = work_rig(people_rig)
    ids = {rig.post("/v1/work-items", WORK_ITEM_BODY).json()["id"] for _ in range(2)}
    assert len(ids) == 2
    before = rig.snapshot()
    for bad in ("", " ", "a b", "x" * 65, "kéy", "k\n1", "k;1"):
        response = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": bad})
        assert response.status_code == 422, repr(bad)
    assert rig.snapshot() == before


def test_PPL_11c_s4_PE_19_a_refused_first_attempt_does_not_use_up_the_key(people_rig):
    rig = work_rig(people_rig)
    body = {"title": "Reply to the vendor", "source": {"kind": "mail", "ref": "msg_vendor_1"}}
    refused = rig.client.post("/v1/work-items", json=body, headers=KEY)
    assert refused.status_code == 422, "someone else's (here: nobody's) mail"
    rig.owners.owners[("mail", "msg_vendor_1")] = PRIYA
    ok = rig.client.post("/v1/work-items", json=body, headers=KEY)
    assert ok.status_code == 201, ok.text[:200]
    assert rig.client.post("/v1/work-items", json=body, headers=KEY).content == ok.content


def test_PPL_11c_s4_PE_17_a_retry_of_the_first_person_claim_is_the_first_answer(people_rig):
    rig = people_rig()
    rig.as_user("u_founder")
    first = rig.client.post("/v1/people/first", json=PERSON_BODY, headers=KEY)
    assert first.status_code == 201, first.text[:200]
    assert rig.client.post("/v1/people/first", json=PERSON_BODY, headers=KEY).content == first.content
    assert len(rig.real.persons.list(rig.org)) == 1


# --- the rate cap ---------------------------------------------------------------------------------------------------


def test_PPL_11c_s4_SEC_09_the_sixty_first_write_in_a_minute_is_a_429_and_reads_still_work(people_rig):
    rig = work_rig(people_rig)
    for n in range(WRITES_PER_MINUTE):
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201, n
    snapshot = rig.snapshot()
    over = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert over.status_code == 429 and over.json()["code"] == "rate_limited", over.text[:200]
    assert 1 <= int(over.headers["retry-after"]) <= 60
    assert rig.post("/v1/meetings", MEETING_BODY).status_code == 429, "the cap is per principal, not per route"
    assert rig.client.post("/v1/work-items", json={"nonsense": 1}).status_code == 429, "decided before the body"
    assert rig.snapshot() == snapshot
    assert rig.plate().status_code == 200, "a read is never counted"
    rig.as_user(SAM)
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201, "another person is not limited"
    rig.as_user(PRIYA)
    rig.set_now(at(seconds=61))
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201, "a minute later she may write again"


def test_PPL_11c_s4_SEC_09_a_refused_write_counts_too(people_rig):
    rig = work_rig(people_rig)
    for _ in range(WRITES_PER_MINUTE):
        assert rig.post("/v1/people", PERSON_BODY).status_code == 403  # a member may not create people
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 429


@settings(max_examples=6, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(count=st.integers(WRITES_PER_MINUTE - 3, WRITES_PER_MINUTE + 4))
def test_PPL_11c_s4_SEC_09_a_principal_never_gets_more_than_the_cap_accepted_in_a_minute(people_rig, count):
    rig = work_rig(people_rig)
    accepted = sum(rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201 for _ in range(count))
    assert accepted == min(count, WRITES_PER_MINUTE)


# --- no whole-org directory per write -------------------------------------------------------------------------------


def _listed(rig) -> bool:
    return ("person", "list", rig.org) in rig.store_calls


def test_PPL_11c_s4_SEC_09_the_existing_writes_read_the_actor_by_id_and_list_no_directory(people_rig):
    """Create meeting, create work item and both confirms (PPL-11a) read the actor's record, never every person of the
    org (#464: 'every write lists the whole org directory'); no more than two person records are read."""
    rig = meeting_rig(people_rig)
    cases = [
        (OWNER, "/v1/work-items/wi_launch_note/confirm", {}),
        (PRIYA, "/v1/meetings", MEETING_BODY),
        (PRIYA, "/v1/work-items", WORK_ITEM_BODY),
    ]
    for actor, path, body in cases:
        rig.as_user(actor)
        del rig.store_calls[:]
        assert rig.post(path, body).status_code in (200, 201), path
        assert not _listed(rig), f"{path} listed the whole org directory"
        assert len([c for c in rig.store_calls if c[:2] == ("person", "get")]) <= 2, path
    unconfirmed = fixture_case("transcript", "invalid", "pe23_unconfirmed_minutes")
    other = people_rig()
    other.seed_quote_case(unconfirmed)
    other.as_user(OWNER)
    del other.store_calls[:]
    assert other.post("/v1/meetings/mt_q4_plan/confirm").status_code == 200
    assert not _listed(other), "confirming minutes listed the whole org directory"


# --- no-store on every answer ---------------------------------------------------------------------------------------


def test_PPL_11c_s4_PE_22_every_answer_is_no_store_the_gates_403_and_a_validation_422_included(people_rig):
    from _sec15_lib import FakeAccessStore  # noqa: PLC0415

    rig = people_rig(deployed=True, access=FakeAccessStore({SAM: "visitor", PRIYA: "judge"}))
    rig.add_people()
    rig.as_user(SAM)
    answers = {"gate 403 (visitor)": rig.get("/v1/plate")}
    rig.as_user(OWNER)
    answers["gate 403 (undeclared)"] = rig.post("/v1/work-items", WORK_ITEM_BODY)
    rig.sign_out()
    answers["401"] = rig.get("/v1/plate")
    rig.as_user(PRIYA)
    answers["422 (bad query)"] = rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": "not-ids"})
    answers["422 (body)"] = rig.client.post("/v1/work-items", json={"nonsense": 1})
    answers["415"] = rig.client.post("/v1/work-items", content="x", headers={"content-type": "text/plain"})
    answers["413"] = rig.client.post(
        "/v1/work-items", content=b" " * (MAX_BODY_BYTES + 1), headers={"content-type": "application/json"}
    )
    answers["404"] = rig.get("/v1/work-items/wi_never_made/quote")
    answers["403 (create)"] = rig.post("/v1/people", PERSON_BODY)
    answers["200"] = rig.get("/v1/plate")
    answers["201"] = rig.post("/v1/work-items", WORK_ITEM_BODY)
    for label, response in answers.items():
        assert response.headers.get("cache-control") == "no-store", (label, response.status_code)
    assert [answers[k].status_code for k in ("gate 403 (visitor)", "413", "422 (bad query)")] == [403, 413, 422]


def test_PPL_11c_s4_PE_22_a_rate_limited_answer_is_no_store_too(people_rig):
    rig = work_rig(people_rig)
    for _ in range(WRITES_PER_MINUTE):
        rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).headers.get("cache-control") == "no-store"


# --- dev mode's CORS ------------------------------------------------------------------------------------------------


def _dev_client(monkeypatch):
    from tilo_api import dev  # noqa: PLC0415
    from tilo_api.people import router  # noqa: PLC0415

    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    app = FastAPI()
    app.include_router(router)
    dev.install(app, {})
    return TestClient(app, base_url=f"http://localhost:{dev.PORT}", raise_server_exceptions=False)


def test_PPL_11c_s4_SEC_09_the_dev_browser_may_send_an_idempotency_key_and_read_retry_after(monkeypatch):
    """The web app on the Vite origin sends `Idempotency-Key` on a create: its preflight must be allowed, and a 429's
    `Retry-After` must be readable by the page. Without that, dev mode answers the preflight 400."""
    from tilo_api import dev  # noqa: PLC0415

    client = _dev_client(monkeypatch)
    preflight = client.options(
        "/v1/work-items",
        headers={
            "Origin": dev.DEFAULT_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, idempotency-key",
        },
    )
    assert preflight.status_code == 200, preflight.text
    assert "idempotency-key" in preflight.headers["access-control-allow-headers"].lower()
    real = client.get("/v1/plate", headers={"Origin": dev.DEFAULT_ORIGIN})
    assert real.status_code == 200
    assert "retry-after" in real.headers.get("access-control-expose-headers", "").lower()
