"""SEC-15, the declaration half: it is captured once at sign-up, kept server-side, and cannot be changed or
forged afterwards by anything a client sends. (The PRD says outright that the declaration can be bypassed, which
is why SEC-16's caps are "the real protection"; this ticket makes it a server-side fact, not a browser one.)

Routes pinned in API_SEC_15.md: `POST /access/declaration` (JSON `{"declaration": "visitor" | "judge"}`, set
once) and `GET /access` (what the signed-in person is, and may do). Tilo never handles passwords: neither route
takes one. Written from the PRD text before any builder touches it: tests/SEC-15-deployed-access.
"""

from __future__ import annotations

import threading

import pytest
from _sec15_lib import (
    CODE_DECLARATION_LOCKED,
    CODE_UNDER_CONSTRUCTION,
    JUDGE,
    NEWCOMER,
    OTHER,
    VISITOR,
    concrete,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_api import app

PROTECTED = "/worlds/{world_id}/events"  # any non-public route will do


def gated(sec) -> int:
    return sec.client.get(concrete(PROTECTED)).status_code


def test_SEC_15_sign_up_as_a_judge_stores_the_declaration_and_opens_the_routes(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)
    assert gated(sec) == 403  # before the question is answered

    response = sec.declare("judge")

    assert response.status_code == 200, response.text
    assert response.json() == {"declaration": "judge", "allowed": True, "models": response.json()["models"]}
    assert response.json()["models"] in {"live", "replay"}
    assert sec.access.data == {NEWCOMER: "judge"}, "stored server-side, keyed by the signed-in person"
    assert gated(sec) != 403
    assert sec.me().json()["declaration"] == "judge"


def test_SEC_15_sign_up_as_a_visitor_is_stored_and_gets_no_access(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    response = sec.declare("visitor")

    assert response.status_code == 200, response.text
    assert response.json() == {"declaration": "visitor", "allowed": False, "models": None}
    assert sec.access.data == {NEWCOMER: "visitor"}
    refused = sec.client.get(concrete(PROTECTED))
    assert (refused.status_code, refused.json()["code"]) == (403, CODE_UNDER_CONSTRUCTION)


def test_SEC_15_before_sign_up_answers_access_says_nothing_is_declared(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    me = sec.me()

    assert me.status_code == 200, me.text
    assert me.json() == {"declaration": None, "allowed": False, "models": None}


def test_SEC_15_a_visitor_cannot_upgrade_to_judge_after_sign_up(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(VISITOR)
    assert sec.declare("visitor").status_code == 200

    upgrade = sec.declare("judge")

    assert upgrade.status_code == 409, upgrade.text
    assert upgrade.json()["code"] == CODE_DECLARATION_LOCKED
    assert sec.access.data[VISITOR] == "visitor"
    assert sec.me().json()["declaration"] == "visitor"
    assert gated(sec) == 403


def test_SEC_15_a_judge_cannot_be_downgraded_by_a_request_either(sec15_factory):
    """Set once in both directions: only the stored value counts, and nothing a client sends rewrites it."""
    sec = sec15_factory(declarations={})
    sec.as_user(JUDGE)
    assert sec.declare("judge").status_code == 200

    response = sec.declare("visitor")

    assert response.status_code == 409 and response.json()["code"] == CODE_DECLARATION_LOCKED
    assert sec.access.data[JUDGE] == "judge"


def test_SEC_15_repeating_the_same_declaration_is_harmless(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(JUDGE)

    first, second = sec.declare("judge"), sec.declare("judge")

    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json() == second.json()
    assert sec.access.data == {JUDGE: "judge"}


@pytest.mark.parametrize(
    "value", ["admin", "Judge", "JUDGE", " judge", "judge ", "", None, 1, True, ["judge"], {"a": 1}]
)
def test_SEC_15_anything_but_visitor_or_judge_is_refused_and_stores_nothing(sec15_factory, value):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    response = sec.declare(value)

    assert response.status_code == 422, response.text
    assert sec.access.data == {}
    assert gated(sec) == 403  # still no declaration: still no access


def test_SEC_15_a_missing_declaration_field_is_refused(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    for body in ({}, {"role": "judge"}, {"allowed": True}):
        assert sec.client.post("/access/declaration", json=body).status_code == 422
    assert sec.access.data == {}


def test_SEC_15_the_declaration_is_always_for_the_signed_in_person_never_for_a_named_one(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    response = sec.client.post(
        "/access/declaration", json={"declaration": "judge", "user_id": OTHER, "uid": OTHER, "owner": OTHER}
    )

    assert response.status_code in {200, 422}, response.text  # extra fields are refused or ignored, never obeyed
    assert OTHER not in sec.access.data
    assert set(sec.access.data) <= {NEWCOMER}


def test_SEC_15_a_client_cannot_declare_through_headers_or_the_query(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    sec.client.post(
        "/access/declaration?declaration=judge",
        json={"declaration": "visitor"},
        headers={"X-Tilo-Declaration": "judge"},
    )

    assert sec.access.data == {NEWCOMER: "visitor"}, "only the JSON body names the declaration"
    sec.me(params={"declaration": "judge"}, headers={"X-Tilo-Declaration": "judge"})
    sec.client.get(concrete(PROTECTED), params={"declaration": "judge"}, headers={"X-Tilo-Declaration": "judge"})
    assert sec.access.data == {NEWCOMER: "visitor"}
    assert sec.access.writes == [(NEWCOMER, "visitor")], "nothing but the one sign-up call wrote"


@pytest.mark.parametrize(
    "shape",
    [
        {"data": {"declaration": "judge"}},
        {"content": "declaration=judge", "headers": {"content-type": "application/x-www-form-urlencoded"}},
        {"content": '{"declaration": "judge"}', "headers": {"content-type": "text/plain"}},
        {"files": {"declaration": (None, "judge")}},
    ],
    ids=["form", "urlencoded", "text-plain-json", "multipart"],
)
def test_SEC_15_a_cross_site_form_post_cannot_declare(sec15_factory, shape):
    """Browsers send these without a CORS preflight, so a hostile page could post one as the signed-in person.
    Like the task routes, `/access/declaration` reads only `application/json`."""
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)

    response = sec.client.post("/access/declaration", **shape)

    assert response.status_code in {415, 422}, response.text
    assert sec.access.data == {} and sec.access.writes == []


def test_SEC_15_signed_out_cannot_declare(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.sign_out()

    assert sec.declare("judge").status_code == 401
    assert sec.access.data == {} and sec.access.writes == []


def test_SEC_15_no_other_route_reads_or_writes_a_declaration_field():
    """The declaration is not editable through a profile or settings update (or any other) route: the only
    request schema in the whole API that has a `declaration` property is `POST /access/declaration`'s."""
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    carriers = {
        name
        for name, schema in schemas.items()
        if "declaration" in schema.get("properties", {}) and "Response" not in name and "Out" not in name
    }
    assert carriers, "POST /access/declaration has no request model carrying `declaration`"

    def refs(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref":
                    yield value.rsplit("/", 1)[-1]
                else:
                    yield from refs(value)
        elif isinstance(node, list):
            for item in node:
                yield from refs(item)

    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            body = op.get("requestBody")
            if body is None or (method.upper(), path) == ("POST", "/access/declaration"):
                continue
            assert not (set(refs(body)) & carriers), f"{method.upper()} {path} accepts the declaration field"
            assert "declaration" not in str(body), f"{method.upper()} {path} accepts a declaration field"


def test_SEC_15_an_update_style_route_cannot_change_a_stored_declaration(sec15_factory):
    """If a profile, account, settings or user update route ever exists, posting a declaration to it changes
    nothing. Vacuous while there is none (the openapi test above guards the field itself)."""
    from _sec15_lib import route_table

    sec = sec15_factory(declarations={VISITOR: "visitor"})
    sec.as_user(VISITOR)
    risky = [
        (m, p)
        for m, p in route_table(app)
        if m in {"POST", "PUT", "PATCH"}
        and any(word in p for word in ("profile", "account", "settings", "/me", "/users", "/user"))
        and p != "/access/declaration"
    ]
    for method, path in risky:
        sec.call(method, path, json={"declaration": "judge", "role": "judge"})
    assert sec.access.data == {VISITOR: "visitor"}
    assert sec.access.writes == []


def test_SEC_15_concurrent_first_declarations_leave_exactly_one_winner(sec15_factory):
    sec = sec15_factory(declarations={})
    sec.as_user(NEWCOMER)
    results: list[tuple[str, int, dict]] = []
    lock = threading.Lock()
    gate = threading.Barrier(8)

    def post(value: str) -> None:
        gate.wait()
        r = sec.declare(value)
        with lock:
            results.append((value, r.status_code, r.json()))

    threads = [threading.Thread(target=post, args=("judge" if i % 2 else "visitor",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    stored = sec.access.data[NEWCOMER]
    assert stored in {"visitor", "judge"}
    for value, status, body in results:
        assert status == (200 if value == stored else 409), (value, status, body, stored)
    assert sec.me().json()["declaration"] == stored


# --- the real in-memory store (the one tilo-api ships until Firestore is wired) --------------------------


@pytest.fixture()
def real_store():
    from tilo_api.access import InMemoryAccessStore

    return InMemoryAccessStore()


def test_SEC_15_store_get_of_an_unknown_person_is_none(real_store):
    assert real_store.get(NEWCOMER) is None


def test_SEC_15_store_is_per_person_and_first_write_wins(real_store):
    assert real_store.declare(VISITOR, "visitor") == "visitor"
    assert real_store.declare(VISITOR, "judge") == "visitor", "declare returns what is stored, not what was asked"
    assert real_store.declare(JUDGE, "judge") == "judge"
    assert (real_store.get(VISITOR), real_store.get(JUDGE), real_store.get(OTHER)) == ("visitor", "judge", None)


@settings(max_examples=80, deadline=None)
@given(
    calls=st.lists(
        st.tuples(st.sampled_from([VISITOR, JUDGE, OTHER]), st.sampled_from(["visitor", "judge"])), max_size=30
    )
)
def test_SEC_15_property_store_never_changes_a_stored_declaration(calls):
    from tilo_api.access import InMemoryAccessStore

    store = InMemoryAccessStore()
    first: dict[str, str] = {}
    for user, value in calls:
        first.setdefault(user, value)
        assert store.declare(user, value) == first[user]
        assert {u: store.get(u) for u in first} == first
