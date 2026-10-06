"""PPL-11c slice 1, review fixes: the history cap on the write side, authorisation before text and schema on edit, an
impossible snooze date is a malformed timestamp, and invisible characters never split a secret before the redactor."""

from __future__ import annotations

import pytest
from _ppl11a_lib import DEV, MEERA, OWNER, PRIYA, SAM, fake_token, history_of, own_item, u
from _ppl11c_lib import UNIQUE_ID, refusals, work_rig
from _ppl11c_lib import act as _act
from tilo_api.people_quotes import MAX_HISTORY


@pytest.mark.parametrize("action", ["edit", "done", "snooze"])
def test_PPL_11c_s1_PE_19_a_write_that_would_take_history_past_the_cap_is_refused_and_the_item_stays_readable(
    people_rig, action
):
    """199 entries: the write makes 200 and works. 200 entries: the next write is a 409 `history`, nothing changes, and
    the owner (and the assigner of a Tilo-made item) can still read the item and list it."""
    rig = work_rig(people_rig)
    rig.add("work_items", own_item("wi_h199", PRIYA, history=history_of(MAX_HISTORY - 1)))
    first = _act(rig, "edit", "wi_h199", {"title": "One more"})
    assert first.status_code == 200 and len(first.json()["history"]) == MAX_HISTORY
    before = rig.snapshot()
    refused = _act(rig, action, "wi_h199")
    assert refused.status_code == 409, refused.text[:200]
    assert refused.json()["code"] == "write_refused" and refused.json()["problems"] == ["history"]
    assert rig.snapshot() == before, "a refused write changes nothing"
    assert rig.client.get("/v1/work-items/wi_h199").status_code == 200
    assert "wi_h199" in [i["id"] for i in rig.client.get("/v1/work-items").json()["items"]]
    assert rig.plate().status_code == 200


def test_PPL_11c_s1_PE_19_the_history_cap_is_decided_after_authorisation(people_rig):
    """Someone who may not touch a full item still gets the one 404, never a 409 that says it is full."""
    rig = work_rig(people_rig)
    rig.add("work_items", own_item("wi_full", PRIYA, history=history_of(MAX_HISTORY)))
    seen = []
    for actor in (DEV, SAM, MEERA, OWNER, "u_ghost"):
        rig.as_user(actor)
        seen.append(_act(rig, "done", "wi_full"))
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1


def test_PPL_11c_s1_PE_03_an_edit_is_authorised_before_its_text_is_cleaned_redacted_or_schema_checked(people_rig):
    """A non-owner's edit with a title over 140 characters, a line break or a due phrase over 60 characters is the one
    404 (not a 422 that says what is wrong, not a redactor call), byte-identical to every other refusal."""
    rig = work_rig(people_rig)
    before = rig.snapshot()
    refused = [_act(rig, "edit", UNIQUE_ID, {"title": "ok"})]
    for actor in (SAM, MEERA, OWNER, "u_ghost"):
        rig.as_user(actor)
        for body in (
            {"title": "x" * 141},
            {"title": f"line{chr(10)}break"},
            {"due_text": "x" * 61},
            {"title": "Water", "due_text": "tomorrow"},
        ):
            refused += [_act(rig, "edit", "wi_own1", body), _act(rig, "edit", "wi_rate_sheet", body)]
    assert {r.status_code for r in refused} == {404} and len(refusals(refused)) == 1
    assert rig.redactor.calls == [], "the redactor never saw a refused caller's text"
    assert rig.snapshot() == before


@pytest.mark.parametrize(
    "until", ["2026-02-30T10:00:00.000Z", "2026-13-01T10:00:00.000Z", "2026-10-07T25:00:00.000Z"], ids=str
)
def test_PPL_11c_s1_PE_19_a_snooze_date_that_does_not_exist_is_a_malformed_timestamp_not_a_range_error(
    people_rig, until
):
    rig = work_rig(people_rig)
    before = rig.snapshot()
    response = _act(rig, "snooze", "wi_own1", {"until": until})
    assert response.status_code == 422, response.text[:200]
    assert until not in response.text
    assert rig.snapshot() == before


def _split(secret: str, mark: str) -> str:
    return mark.join(secret)


@pytest.mark.parametrize(
    "mark",
    [
        u(0x034F),
        u(0xFE0F),
        u(0x180B),
        u(0x115F),
        u(0x1160),
        u(0x3164),
        u(0xFFA0),
        u(0xE0100),
        u(0xE01EF),
        u(0x2065),
        u(0xFFF0),
        u(0xFFF8),
        u(0xE0000),
        u(0xE0FFF),
        u(0x2800),
    ],
    ids=lambda m: f"U+{ord(m):04X}",
)
def test_PPL_11c_s1_SEC_01_an_invisible_mark_cannot_split_a_secret_past_the_redactor(people_rig, mark):
    secret = fake_token()
    rig = work_rig(people_rig)
    response = _act(rig, "edit", "wi_own1", {"title": f"Water {_split(secret, mark)}"})
    assert response.status_code == 200, response.text[:300]
    assert response.json()["title"] == "Water [REDACTED]"
    assert secret not in response.text and secret not in rig.stored("work_items", "wi_own1")["title"]
    assert all(c not in call for call in rig.redactor.calls for c in (mark,)), "stripped before the redactor"


def test_PPL_11c_s1_PE_24_an_emoji_keeps_its_variation_selector_and_a_keycap_its_enclosing_mark(people_rig):
    rig = work_rig(people_rig)
    for title in ("Team ❤️ retro", "1️⃣ Budget", "Café͏ notes"):
        response = _act(rig, "edit", "wi_own1", {"title": title})
        assert response.status_code == 200 and response.json()["title"] == title, title


def test_PPL_11c_s1_PE_24_a_variation_selector_after_ascii_or_a_bare_keycap_base_is_removed(people_rig):
    rig = work_rig(people_rig)
    for given, stored in (("fr️ee", "free"), ("a1️2", "a12"), ("️start", "start"), ("͏", None)):
        response = _act(rig, "edit", "wi_own1", {"title": given})
        if stored is None:
            assert response.status_code == 422, "nothing is left of a title that was only invisible"
        else:
            assert response.status_code == 200 and response.json()["title"] == stored, given
