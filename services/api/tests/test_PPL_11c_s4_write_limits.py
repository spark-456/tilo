"""PPL-11c slice 4: limits on the people writes (PPL-11a follow-ups #462, #464; SEC-10; BQ-PPL11C-1 to -4, -8, -12;
API_PPL_11c.md section 7).

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
import re

import pytest
from _ppl11a_lib import OWNER, PRIYA, SAM, fixture_case, run_threads
from _ppl11c_lib import (
    MAX_BODY_BYTES,
    MEETING_BODY,
    PERSON_BODY,
    R_MT_DELETE,
    R_MT_EDIT,
    R_MT_GET,
    R_MT_MINUTES,
    R_MT_WORLD,
    R_PERSON_FIRST,
    R_ROLE,
    R_TEAM_ADD,
    R_TEAM_REMOVE,
    R_WI_DONE,
    R_WI_EDIT,
    R_WI_GET,
    R_WI_LIST,
    R_WI_NOT_MINE,
    R_WI_PUT_BACK,
    R_WI_REOPEN,
    R_WI_SNOOZE,
    WORK_ITEM_BODY,
    WRITES_PER_MINUTE,
    at,
    meeting_rig,
    padded,
    path_of,
    stream_post,
    valid_request,
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
def test_PPL_11c_s4_BQ_PPL11C_1_an_oversize_body_is_a_413_and_the_rest_of_it_is_never_read(people_rig, path):
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


def test_PPL_11c_s4_BQ_PPL11C_1_every_people_post_route_is_in_the_body_cap_list(people_rig):
    """A guard (passes once S1 to S3 and S6 have landed, and must keep passing): a people POST route added later
    without a line in `BODY_ROUTES` would silently have no cap. `/v1/assistant/ask` is PPL-11b's, not a people write."""
    rig = people_rig()
    not_people_writes = {"/v1/assistant/ask"}
    templates = [
        t
        for t, methods in rig.app.openapi()["paths"].items()
        if "post" in methods and t.startswith("/v1/") and t not in not_people_writes
    ]
    patterns = {t: re.compile("^" + re.sub(r"\{[^/}]+\}", "[^/]+", t) + "$") for t in templates}
    uncovered = [t for t, p in patterns.items() if not any(p.match(path) for path in BODY_ROUTES.values())]
    assert not uncovered, f"people POST routes with no body-cap case: {uncovered}"
    stale = [path for path in BODY_ROUTES.values() if not any(p.match(path) for p in patterns.values())]
    assert not stale, f"body-cap cases for routes the app does not serve: {stale}"


def test_PPL_11c_s4_BQ_PPL11C_1_a_body_of_exactly_the_cap_is_read_and_one_byte_more_is_not(people_rig):
    rig = work_rig(people_rig)
    assert len(padded(MEETING_BODY, MAX_BODY_BYTES)) == MAX_BODY_BYTES  # the attest fields are inside the count
    assert len(padded(MEETING_BODY, MAX_BODY_BYTES + 1)) == MAX_BODY_BYTES + 1
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
    for bad in ("", " ", "a b", "x" * 65, "k\n1", "k;1"):
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


CHANGED_FIELD = {"meeting": "title", "work item": "title", "person": "display_name", "first person": "display_name"}


def _create_rig(people_rig, what):
    """(rig, path, body) for one of the four creates, signed in as someone who may make it."""
    if what == "first person":
        rig = people_rig()
        rig.as_user("u_founder")
        return rig, "/v1/people/first", PERSON_BODY
    path, body, actor = CREATES[what]
    rig = work_rig(people_rig)
    rig.as_user(actor)
    return rig, path, body


@pytest.mark.parametrize("what", list(CHANGED_FIELD))
def test_PPL_11c_s4_PE_19_the_same_key_with_another_body_is_refused_on_every_create(people_rig, what):
    rig, path, body = _create_rig(people_rig, what)
    assert rig.client.post(path, json=body, headers=KEY).status_code == 201
    snapshot = rig.snapshot()
    other = {**body, CHANGED_FIELD[what]: "Something else entirely"}
    reused = rig.client.post(path, json=other, headers=KEY)
    assert reused.status_code == 422, (reused.status_code, reused.text[:200])
    assert reused.json() == {"detail": "idempotency_key_reused", "code": "idempotency_key_reused"}
    assert rig.snapshot() == snapshot


@pytest.mark.parametrize("what", list(CHANGED_FIELD))
def test_PPL_11c_s4_PE_19_a_malformed_key_is_a_422_on_every_create_and_creates_nothing(people_rig, what):
    rig, path, body = _create_rig(people_rig, what)
    before = rig.snapshot()
    for bad in ("", "a b", "x" * 65, "k;1", "k/1"):
        response = rig.client.post(path, json=body, headers={"Idempotency-Key": bad})
        assert response.status_code == 422, (what, repr(bad), response.status_code)
    assert rig.snapshot() == before


@pytest.mark.parametrize("key", ["a" * 64, "A_b-9", "0"], ids=["64 characters", "mixed", "one character"])
def test_PPL_11c_s4_PE_19_a_key_of_one_to_sixty_four_letters_digits_underscores_and_hyphens_is_a_key(people_rig, key):
    rig = work_rig(people_rig)
    first = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key})
    assert first.status_code == 201, first.text[:200]
    again = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key})
    assert again.status_code == 201 and again.content == first.content
    assert len(rig.real.work_items.list(rig.org, "owner", PRIYA)) == 3, "the two seeded items and one new one"


# --- the rate cap ---------------------------------------------------------------------------------------------------


def test_PPL_11c_s4_SEC_10_the_sixty_first_write_in_a_minute_is_a_429_and_reads_still_work(people_rig):
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


def test_PPL_11c_s4_SEC_10_a_refused_write_counts_too(people_rig):
    rig = work_rig(people_rig)
    for _ in range(WRITES_PER_MINUTE):
        assert rig.post("/v1/people", PERSON_BODY).status_code == 403  # a member may not create people
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 429


@settings(max_examples=6, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(count=st.integers(WRITES_PER_MINUTE - 3, WRITES_PER_MINUTE + 4))
def test_PPL_11c_s4_SEC_10_a_principal_never_gets_more_than_the_cap_accepted_in_a_minute(people_rig, count):
    rig = work_rig(people_rig)
    accepted = sum(rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201 for _ in range(count))
    assert accepted == min(count, WRITES_PER_MINUTE)


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [
        ("/v1/work-items/wi_never_made/done", {}, 404),
        ("/v1/work-items", {"nonsense": 1}, 422),
    ],
    ids=["a 404", "a 422"],
)
def test_PPL_11c_s4_SEC_10_every_attempt_past_sign_in_counts_a_404_and_a_422_too(people_rig, path, body, status):
    rig = work_rig(people_rig)
    for n in range(WRITES_PER_MINUTE):
        assert rig.post(path, body).status_code == status, n
    over = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert over.status_code == 429 and over.json()["code"] == "rate_limited", over.text[:200]


def test_PPL_11c_s4_SEC_10_reads_are_never_counted(people_rig):
    rig = work_rig(people_rig)
    for n in range(WRITES_PER_MINUTE + 10):
        assert (rig.plate() if n % 2 else rig.get("/v1/work-items")).status_code == 200, n
    for n in range(WRITES_PER_MINUTE):
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201, n
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 429


def test_PPL_11c_s4_SEC_10_a_retry_with_the_same_key_is_an_attempt_and_the_cap_is_decided_before_the_key(people_rig):
    rig = work_rig(people_rig)
    first = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert first.status_code == 201
    for n in range(WRITES_PER_MINUTE - 1):
        again = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
        assert again.status_code == 201 and again.content == first.content, n
    over = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert over.status_code == 429 and over.json()["code"] == "rate_limited", "the 61st attempt, a replay included"


def test_PPL_11c_s4_SEC_10_the_window_is_a_minute_of_the_injected_clock(people_rig):
    rig = work_rig(people_rig)
    for _ in range(WRITES_PER_MINUTE):
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201
    rig.set_now(at(seconds=59))
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 429, (
        "59 s after the first write is inside a minute"
    )
    rig.set_now(at(seconds=61))
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201


def test_PPL_11c_s4_SEC_10_a_limited_caller_is_refused_before_any_of_the_body_is_read(people_rig):
    rig = work_rig(people_rig)
    for _ in range(WRITES_PER_MINUTE):
        rig.post("/v1/work-items", WORK_ITEM_BODY)
    before = rig.snapshot()
    status, consumed, headers, text = stream_post(rig.app, "/v1/work-items", total_bytes=30_000)  # under the 32 KiB cap
    assert status == 429 and json.loads(text)["code"] == "rate_limited", (status, text[:120])
    assert 1 <= int(headers["retry-after"]) <= 60
    assert consumed <= 4096, f"the app read {consumed} bytes of the body of a request it was going to refuse"
    assert rig.snapshot() == before


def test_PPL_11c_s4_SEC_10_the_counter_belongs_to_the_install_not_to_the_module(people_rig):
    """A second install (a fresh `PeopleStores`) starts at zero for the same person at the same time of day; if the
    counter were module state, one test's writes would limit the next test's."""
    rig = work_rig(people_rig)
    for _ in range(WRITES_PER_MINUTE):
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201
    assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 429
    fresh = work_rig(people_rig)
    assert fresh.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201


# --- no whole-org directory per write -------------------------------------------------------------------------------


def _listed(rig) -> bool:
    return ("person", "list", rig.org) in rig.store_calls


def test_PPL_11c_s4_BQ_PPL11C_12_the_existing_writes_read_the_actor_by_id_and_list_no_directory(people_rig):
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


def test_PPL_11c_s4_BQ_PPL11C_12_meeting_world_and_delete_read_the_actor_by_id_and_list_no_directory(people_rig):
    """S6 and S2a writes: no whole-org directory, no more than two person records (S1 and S2b have their own)."""
    rig = meeting_rig(people_rig)
    for path in ("/v1/meetings/mt_q4_plan/world", "/v1/meetings/mt_q4_plan/delete"):
        del rig.store_calls[:]
        response = rig.post(path)
        assert response.status_code == 200, (path, response.status_code, response.text[:200])
        assert not _listed(rig), f"{path} listed the whole org directory"
        assert len([c for c in rig.store_calls if c[:2] == ("person", "get")]) <= 2, path


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


def test_PPL_11c_s4_PE_22_every_people_route_of_this_ticket_answers_no_store_whatever_the_status(people_rig):
    """Each route of API_PPL_11c.md section 1, asked by someone it may succeed for and by an id it never will, plus
    the directory routes: the Cache-Control header is on the answer, not on the happy path only."""
    rig = work_rig(people_rig)
    mine, theirs, meeting = {"work_item_id": "wi_own1"}, {"work_item_id": "wi_never_made"}, {"meeting_id": "mt_q4_plan"}
    nobody = {"person_id": "u_never_made"}
    calls = [
        (PRIYA, R_WI_LIST, {}),
        (PRIYA, R_WI_GET, mine),
        (PRIYA, R_WI_GET, theirs),
        (PRIYA, R_WI_EDIT, mine),
        (PRIYA, R_WI_SNOOZE, mine),
        (PRIYA, R_WI_PUT_BACK, mine),
        (PRIYA, R_WI_DONE, mine),
        (PRIYA, R_WI_REOPEN, mine),
        (PRIYA, R_WI_NOT_MINE, {"work_item_id": "wi_rate_sheet"}),
        (PRIYA, R_WI_DONE, theirs),
        (PRIYA, R_PERSON_FIRST, {}),
        (OWNER, R_MT_GET, meeting),
        (OWNER, R_MT_GET, {"meeting_id": "mt_never_made"}),
        (OWNER, R_MT_EDIT, meeting),
        (OWNER, R_MT_MINUTES, meeting),
        (OWNER, R_MT_WORLD, meeting),
        (OWNER, R_TEAM_ADD, {"person_id": PRIYA}),
        (OWNER, R_TEAM_REMOVE, {"person_id": PRIYA}),
        (OWNER, R_ROLE, {"person_id": PRIYA}),
        (OWNER, R_TEAM_ADD, nobody),
        (OWNER, R_MT_DELETE, meeting),  # last: the meeting is gone after it
    ]
    for actor, route, ids in calls:
        rig.require_route(route)
        rig.as_user(actor)
        response = rig.client.request(route[0], path_of(route, **ids), **valid_request(route))
        assert response.headers.get("cache-control") == "no-store", (route, ids, response.status_code)


def test_PPL_11c_s4_PE_22_a_409_and_a_503_are_no_store_too(people_rig):
    rig = work_rig(people_rig)
    rig.conflicting_stores("work_items")
    conflict = rig.post("/v1/work-items/wi_own1/done")
    assert conflict.status_code == 409, (conflict.status_code, conflict.text[:200])
    assert conflict.headers.get("cache-control") == "no-store", "409"
    rig.unwire("redactor")
    unavailable = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert unavailable.status_code == 503, (unavailable.status_code, unavailable.text[:200])
    assert unavailable.headers.get("cache-control") == "no-store", "503"


def test_PPL_11c_s4_PE_22_a_rate_limited_answer_is_no_store_too(people_rig):
    rig = work_rig(people_rig)
    for _ in range(WRITES_PER_MINUTE):
        rig.post("/v1/work-items", WORK_ITEM_BODY)
    over = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert over.status_code == 429 and over.headers.get("cache-control") == "no-store"


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


def test_PPL_11c_s4_BQ_PPL11C_4_the_dev_browser_may_send_an_idempotency_key_and_read_retry_after(monkeypatch):
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


# --- supervisor decisions of 7 Oct (BQ-PPL11C-13, BQ-PPL11C-14) -------------------------------------------------------


def test_PPL_11c_s4_BQ_PPL11C_13_an_oversize_body_counts_against_the_rate_cap(people_rig):
    """Every authenticated write attempt counts, a 413 included: oversized-payload spam cannot bypass the limiter."""
    rig = work_rig(people_rig)
    for n in range(WRITES_PER_MINUTE):
        oversize = rig.client.post(
            "/v1/work-items", content=b" " * (MAX_BODY_BYTES + 1), headers={"content-type": "application/json"}
        )
        assert oversize.status_code == 413, n
    over = rig.post("/v1/work-items", WORK_ITEM_BODY)
    assert over.status_code == 429 and over.json()["code"] == "rate_limited", over.text[:200]


def test_PPL_11c_s4_BQ_PPL11C_14_an_idempotency_key_is_scoped_to_the_route_as_well_as_the_principal(people_rig):
    """The same key on another create route is another request, never a replay (or a reuse) of the first route's."""
    rig = work_rig(people_rig)
    item = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert item.status_code == 201
    meetings = len(rig.real.meetings.list(rig.org))
    meeting = rig.client.post("/v1/meetings", json=MEETING_BODY, headers=KEY)
    assert meeting.status_code == 201 and meeting.json()["id"].startswith("mt_"), meeting.text[:200]
    assert len(rig.real.meetings.list(rig.org)) == meetings + 1
    assert rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY).content == item.content
    assert rig.client.post("/v1/meetings", json=MEETING_BODY, headers=KEY).content == meeting.content


# --- #549 items 2 and 5: key eviction and the 429 pin ---------------------------------------------------------------


def _shrink_key_bound(monkeypatch, n: int) -> None:
    from tilo_api import people_limits

    # both names, so the test means the same against the code before and after the per-principal bound
    for name in ("_MAX_KEYS_PER_PRINCIPAL", "_MAX_KEYS"):
        monkeypatch.setattr(people_limits, name, n, raising=False)


def _create_person(rig, key: str) -> int:
    return rig.client.post("/v1/people", json=PERSON_BODY, headers={"Idempotency-Key": key}).status_code


def _create_item(rig, key: str) -> int:
    return rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key}).status_code


def test_PPL_11c_s4_BQ_PPL11C_14_one_principals_creates_cannot_evict_another_principals_key(people_rig, monkeypatch):
    """With the bound at 5: Sam's refused and accepted creates (distinct keys) push out none of Priya's keys, and a
    refused attempt of Priya's own takes no slot either; her retry replays and creates nothing."""
    _shrink_key_bound(monkeypatch, 5)
    rig = work_rig(people_rig)
    first = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert first.status_code == 201
    for n in range(5):  # her own refused attempts (a member may not create people)
        assert _create_person(rig, f"own-{n}") == 403
    rig.as_user(SAM)
    for n in range(5):
        assert _create_person(rig, f"sam-no-{n}") == 403
        assert _create_item(rig, f"sam-{n}") == 201
    rig.as_user(PRIYA)
    snapshot = rig.snapshot()
    again = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert again.status_code == 201 and again.content == first.content, "the first answer, not a second record"
    assert rig.snapshot() == snapshot


def test_PPL_11c_s4_BQ_PPL11C_14_a_principal_over_its_bound_forgets_its_own_oldest_key_only(people_rig, monkeypatch):
    _shrink_key_bound(monkeypatch, 3)
    rig = work_rig(people_rig)
    ids = [
        rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": f"k-{n}"}).json()["id"]
        for n in range(4)
    ]
    assert len(set(ids)) == 4
    newest = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": "k-3"})
    assert newest.json()["id"] == ids[3], "the newest key is still remembered"


def test_PPL_11c_s4_BQ_PPL11C_14_an_entry_whose_holder_is_inside_make_is_never_evicted(monkeypatch):
    """A racing retry waits for the first caller even when that caller's key was the oldest of a full principal."""
    import threading
    import time

    from pydantic import BaseModel
    from tilo_api.people_limits import Limits

    class Body(BaseModel):
        n: int = 1

    _shrink_key_bound(monkeypatch, 2)
    limits, started, release = Limits(), threading.Event(), threading.Event()
    calls: list[str] = []
    results: list[dict] = []

    def slow() -> dict:
        calls.append("first")
        started.set()
        release.wait(5)
        return {"id": "one"}

    def duplicate() -> dict:
        calls.append("duplicate")
        return {"id": "two"}

    first = threading.Thread(target=lambda: results.append(limits.once("u", "/r", "k", Body(), slow)))
    first.start()
    assert started.wait(5)
    for n in range(5):  # the same principal fills its bound while the first create is still running
        limits.once("u", "/r", f"other-{n}", Body(), lambda: {"id": "x"})
    retry = threading.Thread(target=lambda: results.append(limits.once("u", "/r", "k", Body(), duplicate)))
    retry.start()
    time.sleep(0.2)
    release.set()
    first.join(5)
    retry.join(5)
    assert calls == ["first"] and results == [{"id": "one"}, {"id": "one"}], (calls, results)


def _sixty_writes_then_429s_then_a_late_write(rig) -> int:
    for _ in range(WRITES_PER_MINUTE):
        assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 201
    for second in range(1, 60):  # two refused attempts a second through the minute
        rig.set_now(at(seconds=second))
        for _ in range(2):
            assert rig.post("/v1/work-items", WORK_ITEM_BODY).status_code == 429
    rig.set_now(at(seconds=61))
    return rig.post("/v1/work-items", WORK_ITEM_BODY).status_code


def test_PPL_11c_s4_SEC_10_a_429_is_not_counted_so_the_write_at_61_seconds_succeeds(people_rig):
    assert _sixty_writes_then_429s_then_a_late_write(work_rig(people_rig)) == 201


def test_PPL_11c_s4_SEC_10_the_429_pin_catches_a_limiter_that_counts_its_refusals(people_rig, monkeypatch):
    """A mutant that records a hit before refusing keeps the caller limited past the minute; the pin above fails it."""
    from tilo_api import people_limits

    real = people_limits.Limits.attempt

    def counting_mutant(self, user_id, now):
        try:
            real(self, user_id, now)
        except people_limits.Refusal:
            self._hits[user_id].append(now)
            raise

    monkeypatch.setattr(people_limits.Limits, "attempt", counting_mutant)
    assert _sixty_writes_then_429s_then_a_late_write(work_rig(people_rig)) == 429


# --- #553 fix pass: principal slots, LRU order, in-flight principals --------------------------------------------------


def _shrink_principal_bound(monkeypatch, n: int) -> None:
    from tilo_api import people_limits

    # both names (the bound on principals with keys was `_MAX_PRINCIPALS` before it got its own constant)
    for name in ("_MAX_KEY_PRINCIPALS", "_MAX_PRINCIPALS"):
        monkeypatch.setattr(people_limits, name, n, raising=False)


def test_PPL_11c_s4_BQ_PPL11C_14_strangers_refused_keyed_creates_take_no_principal_slot(people_rig, monkeypatch):
    """With room for 3 principals' keys: six non-members each send one keyed create (403). None of them keeps a key or
    a principal slot, so the victim's retry is a byte-identical replay and nothing is created."""
    _shrink_principal_bound(monkeypatch, 3)
    rig = work_rig(people_rig)
    first = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert first.status_code == 201
    for n in range(6):
        rig.as_user(f"u_stranger_{n}")
        assert _create_item(rig, f"stranger-{n}") == 403, n
    rig.as_user(PRIYA)
    snapshot = rig.snapshot()
    again = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert again.status_code == 201 and again.content == first.content, "the first answer, not a second record"
    assert rig.snapshot() == snapshot


def test_PPL_11c_s4_BQ_PPL11C_14_a_key_past_the_bound_is_forgotten_oldest_first_and_a_replay_refreshes_the_order(
    people_rig, monkeypatch
):
    _shrink_key_bound(monkeypatch, 3)
    rig = work_rig(people_rig)

    def create(key: str) -> str:
        response = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key})
        assert response.status_code == 201
        return response.json()["id"]

    ids = [create(f"k-{n}") for n in range(3)]
    assert create("k-0") == ids[0], "a replay, and it makes k-0 the most recently used"
    assert create("k-3") not in ids  # a fourth key: k-1 is now the oldest and goes
    assert create("k-0") == ids[0], "kept: the replay refreshed it"
    assert create("k-2") == ids[2]
    assert create("k-1") != ids[1], "forgotten: its replay is a new record"


def test_PPL_11c_s4_BQ_PPL11C_14_the_oldest_key_past_the_bound_is_forgotten(people_rig, monkeypatch):
    _shrink_key_bound(monkeypatch, 3)
    rig = work_rig(people_rig)
    ids = [
        rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": f"k-{n}"}).json()["id"]
        for n in range(4)
    ]
    first_again = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": "k-0"})
    assert first_again.json()["id"] not in ids, "k-0 was the oldest of four: its bound is three"


def test_PPL_11c_s4_BQ_PPL11C_14_a_principal_with_a_create_in_flight_survives_principal_level_eviction(monkeypatch):
    import threading
    import time

    from pydantic import BaseModel
    from tilo_api.people_limits import Limits

    class Body(BaseModel):
        n: int = 1

    _shrink_principal_bound(monkeypatch, 2)
    limits, started, release = Limits(), threading.Event(), threading.Event()
    calls: list[str] = []
    results: list[dict] = []

    def slow() -> dict:
        calls.append("first")
        started.set()
        release.wait(5)
        return {"id": "one"}

    def duplicate() -> dict:
        calls.append("duplicate")
        return {"id": "two"}

    first = threading.Thread(target=lambda: results.append(limits.once("a", "/r", "k", Body(), slow)))
    first.start()
    assert started.wait(5)
    for other in ("b", "c", "d", "e"):  # more principals with stored answers than there is room for
        limits.once(other, "/r", "k", Body(), lambda: {"id": "x"})
    retry = threading.Thread(target=lambda: results.append(limits.once("a", "/r", "k", Body(), duplicate)))
    retry.start()
    time.sleep(0.2)
    release.set()
    first.join(5)
    retry.join(5)
    assert calls == ["first"] and results == [{"id": "one"}, {"id": "one"}], (calls, results)


# --- #549 / #553 re-check: the principal-level bound is pinned one mutant at a time ----------------------------------


def test_PPL_11c_s4_BQ_PPL11C_14_a_members_store_after_strangers_refusals_evicts_nobody(people_rig, monkeypatch):
    """With room for 3 principals' keys: six strangers' keyed creates are refused (403), then Sam (a member) stores one,
    then Priya retries and gets the first answer. This pins the combination of the unanswered-entry cleanup and the
    stored-only counting; neither mutant alone is guaranteed to fail it. The cleanup mutant is caught by
    `a_refused_create_leaves_no_principal_map_behind`, the old counting (pending work takes a slot) by
    `an_in_flight_create_by_a_stranger_takes_no_principal_slot`."""
    _shrink_principal_bound(monkeypatch, 3)
    rig = work_rig(people_rig)
    first = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert first.status_code == 201
    for n in range(6):
        rig.as_user(f"u_stranger_{n}")
        assert _create_item(rig, f"stranger-{n}") == 403, n
    rig.as_user(SAM)
    assert _create_item(rig, "sam-0") == 201
    rig.as_user(PRIYA)
    snapshot = rig.snapshot()
    again = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers=KEY)
    assert again.status_code == 201 and again.content == first.content, "the first answer, not a second record"
    assert rig.snapshot() == snapshot


def _limits_with_bound(monkeypatch, n: int):
    from pydantic import BaseModel
    from tilo_api.people_limits import Limits

    class Body(BaseModel):
        n: int = 1

    _shrink_principal_bound(monkeypatch, n)
    return Limits(), Body


def _store(limits, body, user: str, key: str = "k") -> None:
    limits.once(user, "/r", key, body(), lambda: {"id": f"{user}-{key}"})


def _never_called() -> dict:
    raise AssertionError("a replay must not call make")


def test_PPL_11c_s4_BQ_PPL11C_14_the_principal_bound_forgets_the_least_recently_used_idle_principal(monkeypatch):
    """Bound 2, three principals store: the first one's key is forgotten (its replay creates again)."""
    limits, body = _limits_with_bound(monkeypatch, 2)
    for user in ("a", "b", "c"):
        _store(limits, body, user)
    assert set(limits._keys) == {"b", "c"}
    created: list[str] = []
    limits.once("a", "/r", "k", body(), lambda: created.append("a") or {"id": "new"})
    assert created == ["a"], "a's key was forgotten, so its retry runs make again"


def test_PPL_11c_s4_BQ_PPL11C_14_a_replay_refreshes_the_principal_order(monkeypatch):
    """Bound 2: a, b store, a replays (now the most recently used), c stores: b goes, a stays."""
    limits, body = _limits_with_bound(monkeypatch, 2)
    _store(limits, body, "a")
    _store(limits, body, "b")
    limits.once("a", "/r", "k", body(), _never_called)
    _store(limits, body, "c")
    assert set(limits._keys) == {"a", "c"}
    limits.once("a", "/r", "k", body(), _never_called)


def test_PPL_11c_s4_BQ_PPL11C_14_the_principal_that_is_storing_is_never_the_one_evicted(monkeypatch):
    """Bound 2: a's create is slow while b and c store; when a's answer lands, a is the oldest principal in the order
    but it is the one storing, so b goes and a's answer is kept (its replay is the first answer)."""
    import threading

    limits, body = _limits_with_bound(monkeypatch, 2)
    started, release = threading.Event(), threading.Event()

    def slow() -> dict:
        started.set()
        release.wait(5)
        return {"id": "a-k"}

    first = threading.Thread(target=lambda: limits.once("a", "/r", "k", body(), slow))
    first.start()
    assert started.wait(5)
    _store(limits, body, "b")
    _store(limits, body, "c")
    release.set()
    first.join(5)
    assert set(limits._keys) == {"a", "c"}
    assert limits.once("a", "/r", "k", body(), _never_called) == {"id": "a-k"}


def test_PPL_11c_s4_BQ_PPL11C_14_a_refused_create_leaves_no_principal_map_behind(monkeypatch):
    """A refused keyed create keeps no key and no (empty) principal map, so refusals never grow the table."""
    limits, body = _limits_with_bound(monkeypatch, 2)

    def refuse() -> dict:
        raise ValueError("refused")

    for n in range(20):
        with pytest.raises(ValueError):
            limits.once(f"stranger-{n}", "/r", "k", body(), refuse)
    assert len(limits._keys) == 0


def test_PPL_11c_s4_BQ_PPL11C_14_an_in_flight_create_by_a_stranger_takes_no_principal_slot(monkeypatch):
    """Bound 2, a and b hold stored answers. A stranger's create is in flight (make blocked); a member stores a second
    key. The in-flight work is no stored answer, so it takes no slot and that store evicts nobody."""
    import threading

    limits, body = _limits_with_bound(monkeypatch, 2)
    _store(limits, body, "a")
    _store(limits, body, "b")
    started, release = threading.Event(), threading.Event()
    outcome: list[str] = []

    def blocked() -> dict:
        started.set()
        release.wait(5)
        raise ValueError("refused")

    def stranger() -> None:
        try:
            limits.once("s", "/r", "k", body(), blocked)
        except ValueError:
            outcome.append("refused")

    thread = threading.Thread(target=stranger)
    thread.start()
    assert started.wait(5)
    _store(limits, body, "a", "k2")
    try:
        assert set(limits._keys) == {"a", "b", "s"}, "nobody was evicted"
        limits.once("b", "/r", "k", body(), _never_called)
    finally:
        release.set()
        thread.join(5)
    assert outcome == ["refused"] and set(limits._keys) == {"a", "b"}


def test_PPL_11c_s4_BQ_PPL11C_14_a_stored_principal_with_a_create_in_flight_is_skipped_by_the_principal_pass(
    monkeypatch,
):
    """Bound 2: `a` has a stored answer and a second create in flight, and is the least recently used principal when
    `b` and `c` store. The principal pass skips it (it has a holder) and forgets `b` instead; a racing retry of the
    in-flight key waits for the first caller and makes nothing."""
    import threading
    import time

    limits, body = _limits_with_bound(monkeypatch, 2)
    _store(limits, body, "a", "stored")
    started, release = threading.Event(), threading.Event()
    calls: list[str] = []
    results: list[dict] = []

    def slow() -> dict:
        calls.append("first")
        started.set()
        release.wait(5)
        return {"id": "one"}

    def duplicate() -> dict:
        calls.append("duplicate")
        return {"id": "two"}

    first = threading.Thread(target=lambda: results.append(limits.once("a", "/r", "k", body(), slow)))
    first.start()
    assert started.wait(5)
    _store(limits, body, "b")
    _store(limits, body, "c")
    retry = threading.Thread(target=lambda: results.append(limits.once("a", "/r", "k", body(), duplicate)))
    retry.start()
    time.sleep(0.2)
    release.set()
    first.join(5)
    retry.join(5)
    assert calls == ["first"] and results == [{"id": "one"}, {"id": "one"}], (calls, results)
    assert set(limits._keys) == {"a", "c"}
