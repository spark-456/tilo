"""SEC-16 beta-allowance feedback: `POST /v1/feedback` (user request, 8 Oct 2026; not in the PRD; services/api/tests/
API_SPEND_FEEDBACK.md). A person who has used their lifetime allowance can leave honest feedback. What is pinned:

* the record: `{uid, text, created_at, context}`, `uid` only from the verified principal, `context` only
  `"lifetime_cap"`, extra fields refused (422), `created_at` from `deps.get_clock`;
* the text: plain text, at most 2,000 characters after cleaning, never empty after cleaning, control and invisible
  format characters removed (newline and tab kept), stored exactly as cleaned (markup is not interpreted or escaped),
  a raw bound of 8,000 characters applied before any cleaning (no quadratic NFKC work on a huge field);
* who: signed in only (401), and in a deployed service a declared judge only (the access gate's 403s), counted by the
  SEC-16 per-uid rate limiter like every gated route; a capped uid can still send feedback (it is not a model call);
* limits per uid: 5 per rolling hour (429 `rate_limited` with `Retry-After`), 20 in a lifetime (429
  `feedback_limit_reached`), atomic under concurrency; invalid requests use no quota;
* no model is called and no ledger is written; the text is never logged; nothing returns it (no read route for users);
* the production seam `deps.get_feedback_store` refuses 503 `not_configured` until wired; dev mode wires an in-memory
  store; the Firestore store writes only under `orgs/{org}/feedback`.

Written from the user request before any builder touches it: tests/SPEND-CAPS-FEEDBACK. Interface choices
(`tilo_api.feedback`, `deps.get_feedback_store`, `FeedbackStore.add`) are in API_SPEND_FEEDBACK.md.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import pytest
from _feedback_lib import (
    CONTEXT,
    GOOD_BODY,
    GOOD_TEXT,
    HOUR_S,
    LIFETIME_MAX,
    MAX_RAW_CHARS,
    MAX_TEXT_CHARS,
    PER_HOUR,
    FakeNow,
    install,
    make_store,
    post,
    with_text,
)
from _sec15_lib import NEWCOMER, VISITOR, concrete, non_public
from _sec16_lib import JUDGE_A, JUDGE_B, spend

BIG_LIMIT = {"rate_limit_requests": 100_000}


def declared():
    return {JUDGE_A: "judge", JUDGE_B: "judge", VISITOR: "visitor"}


@pytest.fixture()
def rig(sec16_factory):
    """A deployed-style harness (access gate on, judges declared), a spy over the production in-memory feedback store
    and a fake clock. The per-uid request limiter is set high so the feedback limits are what a test meets."""
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    store, now = install(h)
    h.feedback, h.now = store, now
    return h


# --- the record ---------------------------------------------------------------------------------------------


def test_SEC_16_FEEDBACK_a_post_stores_uid_text_created_at_and_context_and_answers_201(rig):
    response = post(rig)

    assert response.status_code == 201, response.text
    assert response.json() == {"received": True}, "the answer confirms receipt and never echoes the text"
    assert rig.feedback.records() == [
        {"uid": JUDGE_A, "text": GOOD_TEXT, "created_at": "2026-10-08T09:00:00.000Z", "context": CONTEXT}
    ]


def test_SEC_16_FEEDBACK_the_uid_is_the_verified_principal_never_the_request(rig):
    rig.as_user(JUDGE_B)
    response = post(
        rig,
        headers={"X-Tilo-Uid": JUDGE_A, "X-User-Id": JUDGE_A, "X-Uid": JUDGE_A},
        params={"uid": JUDGE_A, "user_id": JUDGE_A},
    )

    assert response.status_code == 201, response.text
    assert [r["uid"] for r in rig.feedback.records()] == [JUDGE_B]


@pytest.mark.parametrize("extra", ["uid", "user_id", "created_at", "id", "role", "world_id", "anything"])
def test_SEC_16_FEEDBACK_an_extra_field_is_refused_422_and_nothing_is_stored(rig, extra):
    response = post(rig, {**GOOD_BODY, extra: JUDGE_B})

    assert response.status_code == 422, response.text
    assert rig.feedback.records() == []


@pytest.mark.parametrize("context", ["other", "LIFETIME_CAP", "lifetime_cap ", "", None, 1, ["lifetime_cap"]])
def test_SEC_16_FEEDBACK_context_is_only_lifetime_cap(rig, context):
    assert post(rig, {"text": GOOD_TEXT, "context": context}).status_code == 422
    assert rig.feedback.records() == []


def test_SEC_16_FEEDBACK_context_is_required(rig):
    assert post(rig, {"text": GOOD_TEXT}).status_code == 422
    assert rig.feedback.records() == []


@pytest.mark.parametrize("body", [[], "text", None, 7, [GOOD_BODY]])
def test_SEC_16_FEEDBACK_a_body_that_is_not_an_object_is_422(rig, body):
    assert (
        rig.client.post(
            "/v1/feedback", content=json.dumps(body), headers={"content-type": "application/json"}
        ).status_code
        == 422
    )
    assert rig.feedback.records() == []


def test_SEC_16_FEEDBACK_malformed_json_is_422_and_stores_nothing(rig):
    response = rig.client.post("/v1/feedback", content=b'{"text": ', headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert rig.feedback.records() == []


@pytest.mark.parametrize("content_type", ["application/x-www-form-urlencoded", "text/plain", "multipart/form-data"])
def test_SEC_16_FEEDBACK_only_application_json_is_read_415(rig, content_type):
    """Like every task route and the declaration: a cross-site form post needs no CORS preflight, so it is refused."""
    response = rig.client.post(
        "/v1/feedback", content=b"text=hello&context=lifetime_cap", headers={"content-type": content_type}
    )

    assert response.status_code == 415
    assert rig.feedback.records() == []


# --- the text -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [None, 7, 1.5, True, ["a"], {"a": 1}])
def test_SEC_16_FEEDBACK_text_must_be_a_string(rig, text):
    assert post(rig, with_text(text)).status_code == 422
    assert rig.feedback.records() == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        " \n\t     ",
        "​‌‍⁠﻿",  # zero-width characters and a BOM
        "‮‭‏",  # bidi controls
        "ㅤ",  # Hangul filler: looks blank
        "\x00\x07\x1b\x7f",  # control characters
        " ​ \x00 ",
    ],
    ids=["empty", "spaces", "unicode_spaces", "zero_width", "bidi", "hangul_filler", "controls", "mixed_noise"],
)
def test_SEC_16_FEEDBACK_empty_or_invisible_only_text_is_refused_422(rig, text):
    response = post(rig, with_text(text))

    assert response.status_code == 422, response.text
    assert rig.feedback.records() == []


def test_SEC_16_FEEDBACK_exactly_2000_characters_are_stored_and_2001_are_refused(rig):
    assert post(rig, with_text("x" * MAX_TEXT_CHARS)).status_code == 201
    over = post(rig, with_text("x" * (MAX_TEXT_CHARS + 1)))

    assert over.status_code == 422, over.text
    assert [len(r["text"]) for r in rig.feedback.records()] == [MAX_TEXT_CHARS], "the refused one stored nothing"


def test_SEC_16_FEEDBACK_the_length_cap_counts_the_cleaned_text(rig):
    noisy = "x" * MAX_TEXT_CHARS + "​" * 100  # 2,100 raw characters, 2,000 once cleaned

    assert post(rig, with_text(noisy)).status_code == 201
    assert rig.feedback.records()[0]["text"] == "x" * MAX_TEXT_CHARS


def test_SEC_16_FEEDBACK_a_raw_field_over_8000_characters_is_refused_before_any_cleaning(rig):
    response = post(rig, with_text("​" * (MAX_RAW_CHARS + 1) + "ok"))

    assert response.status_code == 422, response.text
    assert rig.feedback.records() == []


def test_SEC_16_FEEDBACK_a_megabyte_of_FDFA_is_refused_quickly_not_normalised(rig):
    """U+FDFA expands 18-fold under NFKC and a run of them is quadratic in some code paths (tilo-untrusted-text
    defects). The raw bound has to come before any normalising or regex over the field."""
    started = time.process_time()
    response = post(rig, with_text("ﷺ" * 1_000_000))
    elapsed = time.process_time() - started

    assert response.status_code in (413, 422), response.status_code
    assert elapsed < 2.0, f"{elapsed:.1f} s of CPU for a 1 MB field"
    assert rig.feedback.records() == []


def test_SEC_16_FEEDBACK_control_and_invisible_characters_are_removed_and_newline_and_tab_are_kept(rig):
    text = "  first\x00 line​‮\n\tsecond\x07 line﻿  "

    assert post(rig, with_text(text)).status_code == 201
    assert rig.feedback.records()[0]["text"] == "first line\n\tsecond line"


def test_SEC_16_FEEDBACK_markup_is_stored_as_plain_text_unchanged(rig):
    """Plain text end to end: the server neither interprets nor escapes it (the page shows it as text nodes only)."""
    markup = '<script>alert(1)</script> <img src=x onerror=alert(2)> & "quotes" {{7*7}} ${jndi:x}'

    response = post(rig, with_text(markup))

    assert response.status_code == 201
    assert rig.feedback.records()[0]["text"] == markup
    assert markup not in response.text and "alert" not in response.text


def test_SEC_16_FEEDBACK_stored_text_is_not_normalised_so_it_cannot_grow(rig):
    text = "ﷺ praise ㌀ ﬃ"

    assert post(rig, with_text(text)).status_code == 201
    assert rig.feedback.records()[0]["text"] == text


# --- who may post -------------------------------------------------------------------------------------------


def test_SEC_16_FEEDBACK_signed_out_is_401_and_nothing_is_stored(rig):
    rig.sign_out()

    response = post(rig)

    assert response.status_code == 401
    assert rig.feedback.records() == []
    assert [c for c in rig.feedback.calls if c != "records"] == [], "the store is not written for nobody"


def test_SEC_16_FEEDBACK_signed_out_is_401_also_when_not_deployed(sec16_factory):
    h = sec16_factory(deployed=False, judge_live=False)
    store, _ = install(h)
    h.sign_out()

    assert post(h).status_code == 401
    assert store.records() == []


def test_SEC_16_FEEDBACK_a_visitor_and_an_undeclared_person_get_the_gates_403s(sec16_factory):
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    store, _ = install(h)

    h.as_user(VISITOR)
    visitor = post(h)
    h.as_user(NEWCOMER)
    newcomer = post(h)

    assert (visitor.status_code, visitor.json()["code"]) == (403, "under_construction")
    assert (newcomer.status_code, newcomer.json()["code"]) == (403, "declaration_required")
    assert store.records() == []
    assert [c for c in store.calls if c != "records"] == []


def test_SEC_16_FEEDBACK_the_route_is_not_public(sec16_factory):
    from _sec15_lib import PINNED_PUBLIC_ROUTES  # noqa: PLC0415

    h = sec16_factory(declarations=declared())

    assert ("POST", "/v1/feedback") not in PINNED_PUBLIC_ROUTES
    assert ("POST", "/v1/feedback") in non_public(h.sec.client.app)


def test_SEC_16_FEEDBACK_every_post_counts_toward_the_per_uid_request_limit(sec16_factory):
    """SEC-16's gate-level limiter (config rate_limit_*): the 4th request in the window is 429 `rate_limited`."""
    h = sec16_factory(declarations=declared(), rate_limit_requests=3)
    store, _ = install(h)

    codes = [post(h).status_code for _ in range(4)]

    assert codes == [201, 201, 201, 429]
    assert h.limiter.checked == [JUDGE_A] * 4
    assert len(store.records()) == 3


def test_SEC_16_FEEDBACK_a_uid_at_its_lifetime_spend_cap_can_still_send_feedback(rig):
    spend(rig.ledger, JUDGE_A, rig.caps.uid_lifetime_minor)
    rig.ledger.calls.clear()
    assert rig.intake().status_code == 403, "setup: new work is refused at the cap"

    response = post(rig)

    assert response.status_code == 201, response.text
    assert [r["uid"] for r in rig.feedback.records()] == [JUDGE_A]


def test_SEC_16_FEEDBACK_feedback_is_accepted_while_the_replay_only_switch_is_set(rig):
    rig.ledger.trip_replay_only("the daily hard cap would be exceeded")
    rig.ledger.calls.clear()

    assert post(rig).status_code == 201


def test_SEC_16_FEEDBACK_no_model_and_no_ledger_is_touched(rig):
    before = rig.snapshot()

    assert post(rig).status_code == 201

    assert rig.router_modes == [], "no router is built for feedback"
    assert rig.safety.calls == [], "the text is stored as text; it is not sent to a model"
    assert rig.ledger.writes == []
    assert rig.snapshot() == before


# --- limits per uid -----------------------------------------------------------------------------------------


def test_SEC_16_FEEDBACK_five_an_hour_then_429_rate_limited_with_retry_after(rig):
    for _ in range(PER_HOUR):
        assert post(rig).status_code == 201
        rig.now.advance(10)

    sixth = post(rig)

    assert sixth.status_code == 429, sixth.text
    assert sixth.json()["code"] == "rate_limited"
    assert sixth.headers["Retry-After"] == str(HOUR_S - 50), "until the oldest of the five leaves the hour"
    assert len(rig.feedback.records()) == PER_HOUR


def test_SEC_16_FEEDBACK_the_hour_is_rolling_and_exactly_one_hour_frees_a_slot(rig):
    for _ in range(PER_HOUR):  # at t0, t0+1 ... t0+4
        assert post(rig).status_code == 201
        rig.now.advance(1)
    rig.now.advance(HOUR_S - PER_HOUR - 1)  # now t0 + 3,599
    assert post(rig).status_code == 429, "3,599 s after the first: still inside the hour"

    rig.now.advance(1)  # now t0 + 3,600

    assert post(rig).status_code == 201, "3,600 s after the first: its slot is free"
    assert post(rig).status_code == 429, "only one slot was freed (the second is still inside the hour)"


def test_SEC_16_FEEDBACK_one_uids_limit_never_refuses_another(rig):
    for _ in range(PER_HOUR):
        assert post(rig).status_code == 201
    assert post(rig).status_code == 429

    rig.as_user(JUDGE_B)

    assert post(rig).status_code == 201


def test_SEC_16_FEEDBACK_a_refused_request_uses_no_quota(rig):
    for _ in range(PER_HOUR + 3):
        assert post(rig, with_text("   ")).status_code == 422
        assert post(rig, {**GOOD_BODY, "uid": "x"}).status_code == 422

    assert [post(rig).status_code for _ in range(PER_HOUR)] == [201] * PER_HOUR


def test_SEC_16_FEEDBACK_twenty_in_a_lifetime_then_429_feedback_limit_reached(rig):
    for _ in range(LIFETIME_MAX):
        rig.now.advance(HOUR_S + 1)  # never more than one an hour, so only the lifetime max can refuse
        assert post(rig).status_code == 201
    rig.now.advance(30 * 24 * HOUR_S)  # a month later

    response = post(rig)

    assert response.status_code == 429, response.text
    assert response.json()["code"] == "feedback_limit_reached"
    assert "Retry-After" not in response.headers, "waiting does not help: it is a lifetime limit"
    assert len(rig.feedback.records()) == LIFETIME_MAX


def test_SEC_16_FEEDBACK_the_hourly_limit_holds_under_concurrency():
    """The store decides atomically (a Firestore store must use one transaction): 40 threads, one uid, one instant."""
    store, now = make_store(), FakeNow()
    results: list[str] = []
    barrier = threading.Barrier(40)

    def worker(n: int) -> None:
        barrier.wait()
        outcome = store.add(
            uid="u_race",
            text=f"t{n}",
            context=CONTEXT,
            created_at=now(),
            hourly_limit=PER_HOUR,
            lifetime_limit=LIFETIME_MAX,
        )
        results.append(outcome.status)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["hourly_limit"] * 35 + ["stored"] * 5
    assert len(store.records()) == PER_HOUR


def test_SEC_16_FEEDBACK_the_lifetime_limit_holds_under_concurrency():
    """The hourly limit is set out of the way here (store-level `hourly_limit` is a parameter), so only the lifetime
    limit can refuse: 60 threads at one instant, exactly 20 are stored."""
    store, now = make_store(), FakeNow()
    results: list[str] = []
    barrier = threading.Barrier(60)

    def worker(n: int) -> None:
        barrier.wait()
        outcome = store.add(
            uid="u_race",
            text=f"t{n}",
            context=CONTEXT,
            created_at=now(),
            hourly_limit=1_000,
            lifetime_limit=LIFETIME_MAX,
        )
        results.append(outcome.status)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(60)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("stored") == LIFETIME_MAX
    assert results.count("lifetime_limit") == 60 - LIFETIME_MAX
    assert len(store.records()) == LIFETIME_MAX


def test_SEC_16_FEEDBACK_the_store_reports_how_long_to_wait():
    store, clock = make_store(), FakeNow()
    for _ in range(PER_HOUR):
        assert (
            store.add(
                uid="u_a",
                text="t",
                context=CONTEXT,
                created_at=clock(),
                hourly_limit=PER_HOUR,
                lifetime_limit=LIFETIME_MAX,
            ).status
            == "stored"
        )
        clock.advance(1)

    refused = store.add(
        uid="u_a", text="t", context=CONTEXT, created_at=clock(), hourly_limit=PER_HOUR, lifetime_limit=LIFETIME_MAX
    )

    assert refused.status == "hourly_limit"
    assert refused.retry_after_s == HOUR_S - PER_HOUR
    assert type(refused.retry_after_s) is int


# --- the text is never read back, never logged ----------------------------------------------------------------


def test_SEC_16_FEEDBACK_the_only_route_about_feedback_is_the_post(sec16_factory):
    h = sec16_factory(declarations=declared())
    spec = h.sec.client.app.openapi()["paths"]

    about = sorted((m.upper(), p) for p, ops in spec.items() for m in ops if "feedback" in p.lower())

    assert about == [("POST", "/v1/feedback")], "no list, get, export or delete route for feedback"


def test_SEC_16_FEEDBACK_no_user_route_ever_returns_the_text(rig):
    token = "FEEDBACK-CANARY-7f3a9c1e"
    assert post(rig, with_text(f"{token} please read me")).status_code == 201
    seen = []
    for user in (JUDGE_A, JUDGE_B):
        rig.as_user(user)
        for method, path in non_public(rig.sec.client.app):
            if method != "GET":
                continue
            response = rig.call(method, concrete(path))
            seen.append((user, path))
            assert token not in response.text, f"{user} {method} {path} returned the feedback text"
    assert seen, "the probe ran"


def test_SEC_16_FEEDBACK_only_the_feedback_modules_know_the_store():
    """Static: a route that read feedback would have to name the store or its records. Only the feedback modules and
    the wiring (deps, dev) may."""
    import pathlib  # noqa: PLC0415

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_api"
    allowed = {"feedback.py", "feedback_firestore.py", "deps.py", "dev.py", "__init__.py"}
    named = {p.name for p in src.rglob("*.py") if "feedback" in p.read_text(encoding="utf-8").lower()}

    assert "feedback.py" in named, "tilo_api/feedback.py must exist"
    assert named <= allowed, f"unexpected modules that mention feedback: {sorted(named - allowed)}"


def test_SEC_16_FEEDBACK_the_text_is_never_logged(rig, caplog, capsys):
    token = "FEEDBACK-LOGCANARY-2b8d4e60"
    caplog.set_level(logging.DEBUG)

    assert post(rig, with_text(f"{token} secret opinion")).status_code == 201
    assert post(rig, with_text(f"{token} " + "y" * MAX_TEXT_CHARS)).status_code == 422  # over the cap: still not logged

    out = capsys.readouterr()
    assert token not in caplog.text
    assert token not in out.out and token not in out.err


# --- wiring -----------------------------------------------------------------------------------------------


def test_SEC_16_FEEDBACK_an_unwired_production_store_refuses_503_not_configured(sec16_factory, monkeypatch):
    for name in ("TILO_API_STORE", "TILO_FIRESTORE_PROJECT", "FIRESTORE_EMULATOR_HOST"):
        monkeypatch.delenv(name, raising=False)
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    from tilo_api import app, deps  # noqa: PLC0415

    app.dependency_overrides.pop(getattr(deps, "get_feedback_store", None), None)

    response = post(h)

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "not_configured"


def test_SEC_16_FEEDBACK_dev_mode_wires_an_in_memory_store():
    from fastapi import FastAPI  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from tilo_api import deps, dev, feedback  # noqa: PLC0415

    app = FastAPI()
    app.include_router(feedback.router)
    dev.install(app, {})
    client = TestClient(app, base_url=f"http://localhost:{dev.PORT}")

    response = client.post("/v1/feedback", json=GOOD_BODY)

    assert response.status_code == 201, response.text
    store = app.dependency_overrides[deps.get_feedback_store]()
    assert [(r["uid"], r["text"]) for r in store.records()] == [(dev.DEV_OWNER, GOOD_TEXT)]


# --- the Firestore store ------------------------------------------------------------------------------------


def _firestore_store():
    from _ppl11c_fs_fake import FakeFirestore  # noqa: PLC0415
    from tilo_api.feedback_firestore import FirestoreFeedbackStore  # noqa: PLC0415

    db = FakeFirestore()
    return db, FirestoreFeedbackStore(db)


def _stored_docs(db):
    return {path: doc for path, doc in db.docs.items() if "text" in doc}


def test_SEC_16_FEEDBACK_the_firestore_store_writes_exactly_the_four_fields_under_the_orgs_feedback_collection():
    db, store = _firestore_store()

    outcome = store.add(
        uid="u_fs",
        text="Honest words.",
        context=CONTEXT,
        created_at="2026-10-08T09:00:00.000Z",
        hourly_limit=PER_HOUR,
        lifetime_limit=LIFETIME_MAX,
    )

    assert outcome.status == "stored"
    assert all(path.startswith("orgs/org_tilo/feedback") for path in db.docs), sorted(db.docs)
    assert list(_stored_docs(db).values()) == [
        {"uid": "u_fs", "text": "Honest words.", "created_at": "2026-10-08T09:00:00.000Z", "context": CONTEXT}
    ]


def test_SEC_16_FEEDBACK_the_firestore_store_enforces_both_limits_and_a_refusal_writes_nothing():
    db, store = _firestore_store()
    clock = FakeNow()
    outcomes = []
    for n in range(PER_HOUR + 1):
        outcomes.append(
            store.add(
                uid="u_fs",
                text=f"t{n}",
                context=CONTEXT,
                created_at=clock(),
                hourly_limit=PER_HOUR,
                lifetime_limit=LIFETIME_MAX,
            )
        )
        clock.advance(1)

    assert [o.status for o in outcomes] == ["stored"] * PER_HOUR + ["hourly_limit"]
    assert type(outcomes[-1].retry_after_s) is int and 1 <= outcomes[-1].retry_after_s <= HOUR_S
    assert len(_stored_docs(db)) == PER_HOUR

    for _ in range(LIFETIME_MAX - PER_HOUR):
        clock.advance(HOUR_S + 1)
        assert (
            store.add(
                uid="u_fs",
                text="t",
                context=CONTEXT,
                created_at=clock(),
                hourly_limit=PER_HOUR,
                lifetime_limit=LIFETIME_MAX,
            ).status
            == "stored"
        )
    clock.advance(HOUR_S + 1)
    last = store.add(
        uid="u_fs", text="t", context=CONTEXT, created_at=clock(), hourly_limit=PER_HOUR, lifetime_limit=LIFETIME_MAX
    )

    assert last.status == "lifetime_limit"
    assert len(_stored_docs(db)) == LIFETIME_MAX
