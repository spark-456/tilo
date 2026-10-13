"""SEC-16 feedback hardening (security review r1 of SPEND-CAPS-FEEDBACK): the body is read like the people writes
(415, a 413 before the read, a 422 that never carries the input), invisible-only text is refused, the Firestore slots
bound both limits under an optimistic database, a busy store is a 503, and anonymous demo sessions are refused."""

from __future__ import annotations

import io
import json
import logging

import pytest
from _feedback_lib import CONTEXT, FakeNow, install, post
from _sec15_lib import VISITOR
from _sec16_lib import JUDGE_A, JUDGE_B

CANARY = "FEEDBACK-HARDEN-CANARY-91c4d7"


@pytest.fixture()
def rig(sec16_factory):
    h = sec16_factory(
        declarations={JUDGE_A: "judge", JUDGE_B: "judge", VISITOR: "visitor"}, rate_limit_requests=100_000
    )
    h.feedback, h.now = install(h)
    return h


def _json_stream():
    from tilo_logging import configure_logging  # noqa: PLC0415

    stream = io.StringIO()
    configure_logging(stream)
    return stream


def _raw(rig, content: bytes):
    return rig.client.post("/v1/feedback", content=content, headers={"content-type": "application/json"})


@pytest.mark.parametrize(
    "body",
    [
        ('{"text": "' + CANARY + ' \\ud800", "context": "lifetime_cap"}').encode(),
        ('{"text": "' + CANARY + " " + "y" * 8001 + '", "context": "lifetime_cap", "n": NaN}').encode(),
        ('{"text": "' + CANARY + '", "context": "lifetime_cap", "extra_' + CANARY + '": NaN}').encode(),
    ],
    ids=["lone_surrogate", "nan_with_oversized_text", "nan_unknown_key"],
)
def test_SEC_16_FEEDBACK_a_surrogate_or_NaN_body_is_422_and_the_text_is_logged_nowhere(rig, caplog, capsys, body):
    caplog.set_level(logging.DEBUG)
    stream = _json_stream()

    response = _raw(rig, body)

    assert response.status_code == 422, response.text
    assert CANARY not in response.text, "the 422 never echoes the input"
    assert rig.feedback.records() == []
    out = capsys.readouterr()
    for place in (caplog.text, out.out, out.err, stream.getvalue()):
        assert CANARY not in place


def test_SEC_16_FEEDBACK_a_422_carries_only_field_locations(rig):
    response = post(rig, {"text": "x", "context": CONTEXT, "uid": "u_other"})

    assert response.status_code == 422
    assert response.json() == {"detail": [{"loc": ["body", "?"]}]} or all(
        set(item) == {"loc"} for item in response.json()["detail"]
    )
    assert "u_other" not in response.text


def test_SEC_16_FEEDBACK_a_20_MB_body_is_413_without_being_parsed(rig):
    body = b'{"text": "' + b"a" * (20 * 1024 * 1024) + b'", "context": "lifetime_cap"}'

    response = _raw(rig, body)

    assert response.status_code == 413, response.status_code
    assert len(response.content) < 1000, "nothing of the body is sent back"
    assert rig.feedback.records() == []


def test_SEC_16_FEEDBACK_a_chunked_body_over_the_cap_is_413(rig):
    def chunks():
        for _ in range(200):
            yield b"a" * 4096

    response = rig.client.post("/v1/feedback", content=chunks(), headers={"content-type": "application/json"})

    assert response.status_code == 413


@pytest.mark.parametrize(
    "text",
    ["͏", "⠀", "️", "̀́", "͏⠀️ ", "ㅤ͏"],
    ids=["cgj", "braille_blank", "variation_selector", "combining_only", "mixed", "filler_cgj"],
)
def test_SEC_16_FEEDBACK_invisible_only_text_is_422(rig, text):
    response = post(rig, {"text": text, "context": CONTEXT})

    assert response.status_code == 422, response.text
    assert rig.feedback.records() == []


def test_SEC_16_FEEDBACK_text_with_a_combining_mark_on_a_letter_is_kept(rig):
    assert post(rig, {"text": "café ok", "context": CONTEXT}).status_code == 201


def test_SEC_16_FEEDBACK_an_anonymous_demo_session_is_refused_403_and_nothing_is_stored(rig):
    from tilo_api import app, deps  # noqa: PLC0415

    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=JUDGE_A, role="owner", demo_session=True
    )

    response = post(rig)

    assert response.status_code == 403
    assert response.json()["code"] == "full_session_required"
    assert rig.feedback.records() == []


def test_SEC_16_FEEDBACK_a_busy_store_is_503_busy_not_500(rig):
    from tilo_api import app, deps  # noqa: PLC0415
    from tilo_api.feedback import FeedbackBusy  # noqa: PLC0415

    class Busy:
        def add(self, **_):
            raise FeedbackBusy

    app.dependency_overrides[deps.get_feedback_store] = lambda: Busy()

    response = post(rig)

    assert response.status_code == 503
    assert response.json()["code"] == "busy"


# --- the Firestore store on the optimistic fake ----------------------------------------------------------------


def _fs():
    from _ppl11c_fs_fake import FakeFirestore  # noqa: PLC0415
    from tilo_api.feedback_firestore import FirestoreFeedbackStore  # noqa: PLC0415

    db = FakeFirestore()
    return db, FirestoreFeedbackStore(db)


ITEMS = "orgs/org_tilo/feedback/u_fs/items"


def _seed(db, count, created_at="2026-10-01T09:00:00.000Z"):
    for n in range(count):
        db.put(f"{ITEMS}/{n:02d}", {"uid": "u_fs", "text": "t", "created_at": created_at, "context": CONTEXT})


def _add(store, clock):
    return store.add(uid="u_fs", text="t", context=CONTEXT, created_at=clock(), hourly_limit=5, lifetime_limit=20)


def test_SEC_16_FEEDBACK_a_rival_insert_after_the_read_cannot_push_the_lifetime_count_past_20():
    db, store = _fs()
    _seed(db, 19)
    db.rival_after_read(
        f"{ITEMS}/00",
        docs={
            f"{ITEMS}/19": {
                "uid": "u_fs",
                "text": "rival",
                "created_at": "2026-10-01T09:00:00.000Z",
                "context": CONTEXT,
            }
        },
    )

    outcome = _add(store, FakeNow())

    assert outcome.status == "lifetime_limit"
    assert len([p for p in db.docs if p.startswith(ITEMS)]) == 20


def test_SEC_16_FEEDBACK_a_rival_insert_after_the_read_cannot_push_the_hourly_count_past_5():
    db, store = _fs()
    clock = FakeNow()
    now = clock()
    _seed(db, 4, created_at=now)
    db.rival_after_read(
        f"{ITEMS}/00", docs={f"{ITEMS}/04": {"uid": "u_fs", "text": "rival", "created_at": now, "context": CONTEXT}}
    )

    outcome = _add(store, clock)

    assert outcome.status == "hourly_limit"
    assert len([p for p in db.docs if p.startswith(ITEMS)]) == 5


def test_SEC_16_FEEDBACK_the_firestore_read_is_bounded_and_slots_are_fixed():
    db, store = _fs()
    assert _add(store, FakeNow()).status == "stored"
    assert sorted(db.docs) == [f"{ITEMS}/00"]


def test_SEC_16_FEEDBACK_a_store_that_keeps_aborting_raises_busy_not_a_valueerror():
    from google.api_core import exceptions as gexc  # noqa: PLC0415
    from tilo_api.feedback import FeedbackBusy  # noqa: PLC0415

    db, store = _fs()
    _seed(db, 3)

    def always(path, doc=None):
        raise gexc.Aborted("contention")

    db.commit = always  # type: ignore[method-assign]

    with pytest.raises(FeedbackBusy):
        _add(store, FakeNow())


def test_SEC_16_FEEDBACK_the_json_body_cap_is_a_constant_of_the_feedback_module():
    from tilo_api import feedback  # noqa: PLC0415

    assert feedback.MAX_BODY_BYTES >= 6 * feedback.MAX_RAW_CHARS, "8000 escaped characters must fit"
    assert json.dumps("\u0001" * feedback.MAX_RAW_CHARS).__len__() <= feedback.MAX_BODY_BYTES
