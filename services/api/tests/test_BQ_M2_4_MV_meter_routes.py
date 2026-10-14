"""BQ-M2-4, BQ-M2-5, ADR-0042 (rules MV-01 to MV-16): the bot's two meter routes on tilo-api. They are INERT until the
user answers BQ-M2-5 (`TILO_VOICE_METER=1`); then each checks its own Google ID token, finds the attend claim the
owner's own attend request made (uid and org are never in a body), and reserves and settles one unit per spoken reply
on the SEC-16 ledger. Fake verifier, the in-memory ledger behind a spy, no network, no paid call."""

from __future__ import annotations

import logging
import math

import pytest
from _mv_lib import (
    AUDIENCE,
    BOT_SA,
    CEILING,
    CLOSE,
    MEETING,
    OTHER_MEETING,
    OWNER,
    OWNER_2,
    RESERVE,
    TASKS_SA,
    TICK_SA,
    UNIT,
    Rig,
    cost_usd,
    new_key,
)
from _sec16_lib import DeadFlags, DeadLedger, spend


def _priced(tokens_in: int, tokens_out: int) -> int:
    """The expected minor units, from the one rate the API prices with (never a literal)."""
    from tilo_api.spend_units import INR_MINOR_PER_USD

    return max(1, math.ceil(cost_usd(tokens_in, tokens_out) * INR_MINOR_PER_USD))


@pytest.fixture
def rig(monkeypatch):
    return Rig(monkeypatch)


# --- inert, pins (MV-13) -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [RESERVE, CLOSE])
def test_BQ_M2_5_MV_13_inert_until_the_user_enables_it_a_plain_404_and_nothing_read(rig, monkeypatch, path):
    monkeypatch.delenv("TILO_VOICE_METER")
    response = rig.post(path, {"anything": 1})
    assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})
    assert rig.verifier.calls == [] and rig.ledger.calls == []  # no token verification, no ledger touched
    monkeypatch.setenv("TILO_VOICE_METER", "true")  # presence is not enough: exactly "1"
    assert rig.post(path, {"anything": 1}).status_code == 404


@pytest.mark.parametrize("path", [RESERVE, CLOSE])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("authorization", [None, "", "Basic invalid", "Bearer", "Bearer two tokens"])
def test_SEC_05_MV_missing_or_malformed_bearer_is_401_before_flag_pins_or_body(
    rig, monkeypatch, path, enabled, authorization
):
    from tilo_api import meeting_voice_meter  # noqa: PLC0415

    monkeypatch.setenv("TILO_VOICE_METER", "1" if enabled else "0")
    monkeypatch.delenv("TILO_VOICE_METER_AUDIENCE")

    async def unread_body(request):
        pytest.fail("unauthenticated request read its body")

    monkeypatch.setattr(meeting_voice_meter, "_read_body", unread_body)
    headers = {} if authorization is None else {"Authorization": authorization}
    response = rig.client.post(path, content=b"not json", headers=headers)
    assert (response.status_code, response.json()) == (401, {"error": "unauthenticated"})
    assert rig.verifier.calls == [] and rig.ledger.calls == []


@pytest.mark.parametrize("path", [RESERVE, CLOSE])
def test_SEC_05_MV_valid_bearer_with_flag_off_reads_no_pins_or_body(rig, monkeypatch, path):
    from tilo_api import meeting_voice_meter  # noqa: PLC0415

    monkeypatch.delenv("TILO_VOICE_METER")

    def unread_pins():
        pytest.fail("disabled meter read caller configuration")

    async def unread_body(request):
        pytest.fail("disabled meter read its body")

    monkeypatch.setattr(meeting_voice_meter, "_pins", unread_pins)
    monkeypatch.setattr(meeting_voice_meter, "_read_body", unread_body)
    response = rig.post(path, None, raw=b"not json")
    assert (response.status_code, response.json()) == (404, {"detail": "Not Found"})
    assert rig.verifier.calls == [] and rig.ledger.calls == []


def test_BQ_M2_5_MV_13_the_two_routes_are_exact_public_and_app_check_exempt_entries_and_nothing_wider():
    from tilo_api import access, appcheck

    routes = {("POST", RESERVE), ("POST", CLOSE)}
    assert routes <= access.PUBLIC_ROUTES and routes <= appcheck.EXEMPT_ROUTES
    assert {r for r in access.PUBLIC_ROUTES if "meeting-voice" in r[1]} == routes
    assert {r for r in appcheck.EXEMPT_ROUTES if "meeting-voice" in r[1]} == routes
    assert not access.public_link("POST", RESERVE)  # it is no `/l/<token>` path


def test_BQ_M2_5_MV_13_deployed_the_gate_and_app_check_let_it_through_to_its_own_token_check(rig, monkeypatch):
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setenv("TILO_APPCHECK_ENFORCE", "1")
    nonce = rig.attend()
    anonymous = rig.reserve(nonce, new_key(), token=None)
    assert (anonymous.status_code, anonymous.json()) == (401, {"error": "unauthenticated"})  # its own, not the gate's
    ok = rig.reserve(nonce, new_key())
    assert (ok.status_code, ok.json()) == (200, {"decision": "live"})


# --- the caller (MV-01) ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", [RESERVE, CLOSE])
def test_BQ_M2_4_MV_01_no_token_or_a_token_google_would_not_accept_is_401(rig, route):
    nonce = rig.attend()
    body = {"meeting_id": MEETING, "claim": nonce, "key": new_key()}
    other_audience = rig.verifier.register(BOT_SA, aud="https://someone-else.example.com")
    for token in (None, "not-a-token", other_audience):
        response = rig.post(route, body, token=token)
        assert (response.status_code, response.json()) == (401, {"error": "unauthenticated"})
    assert rig.ledger.calls == []


@pytest.mark.parametrize("route", [RESERVE, CLOSE])
def test_BQ_M2_4_MV_01_any_other_account_is_403_the_ticks_and_tasks_included(rig, route):
    nonce = rig.attend()
    body = {"meeting_id": MEETING, "claim": nonce, "key": new_key()}
    for email, verified in (
        (TICK_SA, True),
        (TASKS_SA, True),
        ("tilo-api@x.iam.gserviceaccount.com", True),
        (BOT_SA, False),
    ):
        token = rig.verifier.register(email, email_verified=verified)
        response = rig.post(route, body, token=token)
        assert (response.status_code, response.json()) == (403, {"error": "forbidden"})
    assert rig.ledger.calls == []


def test_BQ_M2_4_MV_01_the_bots_account_gets_403_on_the_schedule_tick(rig, monkeypatch):
    monkeypatch.setenv("TILO_SCHEDULE_TICK_AUDIENCE", AUDIENCE)
    response = rig.post("/internal/schedules/tick", None, raw=b"", token=None)
    assert response.status_code == 401
    forbidden = rig.post("/internal/schedules/tick", None, raw=b"", token=rig.token)  # the bot's own token
    assert forbidden.status_code == 403


@pytest.mark.parametrize(
    "name,value",
    [
        ("TILO_VOICE_METER_AUDIENCE", None),
        ("TILO_VOICE_METER_CALLER", None),
        ("TILO_VOICE_METER_CALLER", TICK_SA),  # equal to the tick's caller: one setting would open two doors
        ("TILO_VOICE_METER_CALLER", TASKS_SA),
        ("TILO_VOICE_METER_AUDIENCE", AUDIENCE + "/internal"),
        ("TILO_VOICE_METER_AUDIENCE", AUDIENCE + "?a=1"),
        ("TILO_VOICE_METER_AUDIENCE", AUDIENCE + "#x"),
        ("TILO_VOICE_METER_AUDIENCE", AUDIENCE.replace("https", "http")),
        ("TILO_VOICE_METER_AUDIENCE", AUDIENCE + "\n"),
    ],
)
@pytest.mark.parametrize("route", [RESERVE, CLOSE])
def test_BQ_M2_4_MV_01_unset_or_malformed_pins_are_503_before_any_token_is_read(rig, monkeypatch, route, name, value):
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    response = rig.post(route, {"meeting_id": MEETING}, token=rig.token)
    assert (response.status_code, response.json()) == (503, {"error": "not_configured"})
    assert rig.verifier.calls == []


def test_BQ_M2_4_MV_01_the_pins_are_read_per_request_from_tilo_apis_own_environment(rig, monkeypatch):
    nonce = rig.attend()
    other = "someone@" + BOT_SA.split("@")[1]
    monkeypatch.setenv("TILO_VOICE_METER_CALLER", other)
    assert rig.reserve(nonce, new_key()).status_code == 403  # the old bot account is not the pin any more
    assert rig.reserve(nonce, new_key(), token=rig.verifier.register(other)).status_code == 200


# --- the body (MV-03, MV-06) -------------------------------------------------------------------------------------


@pytest.mark.parametrize("extra", ["user_id", "org_id", "run_id", "amount_minor", "hold", "uid", "cap", "price"])
def test_BQ_M2_4_MV_03_a_body_names_no_person_org_run_hold_or_amount(rig, extra):
    nonce = rig.attend()
    body = {"meeting_id": MEETING, "claim": nonce, "key": new_key(), extra: OWNER_2}
    response = rig.post(RESERVE, body)
    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert rig.ledger.writes == []
    closing = {**body, "outcome": "released"}
    assert rig.post(CLOSE, closing).status_code == 422


def test_BQ_M2_4_MV_06_a_body_over_two_kib_not_json_or_off_contract_is_422_and_touches_nothing(rig):
    nonce = rig.attend()
    key = new_key()
    for raw in (
        b'{"meeting_id": "' + MEETING.encode() + b'", "pad": "' + b"x" * 2100 + b'"}',
        b"not json",
        b'{"meeting_id": "' + MEETING.encode() + b'"}',
        b'{"meeting_id": "m_1", "claim": "' + nonce.encode() + b'", "key": "' + key.encode() + b'"}',
    ):
        response = rig.post(RESERVE, None, raw=raw)
        assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})
    assert rig.ledger.calls == []


@pytest.mark.parametrize(
    "claim,key",
    [
        ("c" * 31, "k" * 16),
        ("c" * 65, "k" * 16),
        ("c" * 32, "k" * 15),
        ("c" * 32, "k" * 65),
        ("c c" + "c" * 30, "k" * 16),
    ],
)
def test_BQ_M2_4_MV_16_a_claim_or_key_of_the_wrong_shape_is_422(rig, claim, key):
    assert rig.reserve(claim, key).status_code == 422


def test_BQ_M2_4_MV_05_a_close_needs_usage_exactly_when_it_settles(rig):
    nonce = rig.attend()
    key = new_key()
    assert rig.reserve(nonce, key).status_code == 200
    no_usage = rig.post(CLOSE, {"meeting_id": MEETING, "claim": nonce, "key": key, "outcome": "settled"})
    with_usage = rig.post(
        CLOSE,
        {"meeting_id": MEETING, "claim": nonce, "key": key, "outcome": "released", "usage": {"total_token_count": 1}},
    )
    assert (no_usage.status_code, with_usage.status_code) == (422, 422)
    assert rig.spent() == UNIT  # still one open hold: neither request closed anything


# --- the claim, the nonce and the uid (MV-02, MV-14, MV-16) -------------------------------------------------------


def test_BQ_M2_4_MV_14_without_a_claim_the_answer_is_409_and_there_is_no_fallback(rig):
    for call in (rig.reserve("n" * 32, new_key()), rig.close("n" * 32, new_key())):
        assert (call.status_code, call.json()) == (409, {"error": "not_attending"})
    assert rig.ledger.calls == []


def test_BQ_M2_4_MV_16_a_wrong_nonce_another_meetings_nonce_and_an_old_one_are_the_same_409(rig):
    old = rig.attend()  # the nonce of an earlier attend of the same meeting
    rig.claims.end(MEETING, old)
    mine, other = rig.attend(), rig.attend(OTHER_MEETING, uid=OWNER_2)
    shapes = set()
    for nonce in (old, other, "w" * 32, mine[:-1] + ("A" if mine[-1] != "A" else "B")):
        for call in (rig.reserve(nonce, new_key()), rig.close(nonce, new_key())):
            assert call.status_code == 409
            shapes.add(call.text)
    assert shapes == {'{"error":"not_attending"}'}  # one body, whatever the reason
    assert rig.ledger.calls == []


def test_BQ_M2_4_MV_16_the_nonce_is_compared_in_constant_time(rig, monkeypatch):
    import hmac

    from tilo_api import meeting_voice_claims

    seen: list[str] = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.extend(x.decode() if isinstance(x, bytes) else x for x in (a, b))
        return real(a, b)

    monkeypatch.setattr(meeting_voice_claims.hmac, "compare_digest", spy)
    rig.attend()
    rig.reserve("w" * 32, new_key())  # a wrong nonce is compared ...
    rig.reserve("x" * 32, new_key(), meeting_id=OTHER_MEETING)  # ... and so is a nonce with no claim at all
    assert "w" * 32 in seen and "x" * 32 in seen


def test_BQ_M2_4_MV_02_an_expired_claim_is_refused_before_it_is_swept(rig):
    nonce = rig.attend()
    rig.clock.advance(3_501)  # the attend request's own read timeout is 3500 s
    assert rig.reserve(nonce, new_key()).status_code == 409


def test_BQ_M2_4_MV_02_spend_lands_on_the_uid_the_claim_names_never_on_one_the_body_names(rig):
    nonce_a, nonce_b = rig.attend(uid=OWNER), rig.attend(OTHER_MEETING, uid=OWNER_2)
    key_a, key_b = new_key(), new_key()
    assert rig.reserve(nonce_a, key_a).status_code == 200
    assert rig.reserve(nonce_b, key_b, meeting_id=OTHER_MEETING).status_code == 200
    assert (rig.spent(OWNER), rig.spent(OWNER_2)) == (UNIT, UNIT)
    assert rig.close(nonce_a, key_a).status_code == 200
    assert (rig.settled(OWNER), rig.settled(OWNER_2), rig.spent(OWNER_2)) == (2, 0, UNIT)  # a's close moved b's nothing
    assert rig.close(nonce_a, key_b, meeting_id=OTHER_MEETING).status_code == 409  # a's nonce on b's meeting


# --- reserve (MV-04, MV-05, MV-06) -------------------------------------------------------------------------------


def test_BQ_M2_4_MV_04_a_reserve_holds_exactly_one_unit_whatever_the_request_says(rig):
    nonce, key = rig.attend(), new_key()
    assert rig.reserve(nonce, key).json() == {"decision": "live"}
    assert rig.spent() == UNIT and rig.settled() == 0
    held = [kw for name, _, kw in rig.ledger.calls if name == "reserve"]
    assert [kw["amount_minor"] for kw in held] == [UNIT]
    assert held[0]["uid"] == OWNER and held[0]["org_id"] == "org_tilo" and held[0]["run_id"] == MEETING


def test_BQ_M2_4_MV_05_a_repeated_reserve_of_an_open_key_counts_once_and_a_closed_key_is_never_reopened(rig):
    nonce, key = rig.attend(), new_key()
    assert [rig.reserve(nonce, key).json() for _ in range(3)] == [{"decision": "live"}] * 3
    assert rig.spent() == UNIT and len([c for c in rig.ledger.names if c == "reserve"]) == 1
    assert rig.close(nonce, key, "released").json() == {"outcome": "released"}
    again = rig.reserve(nonce, key)
    assert (again.status_code, again.json()) == (409, {"error": "key_used"})
    assert rig.spent() == 0


def test_BQ_M2_4_MV_06_one_reply_at_a_time_and_a_cap_on_reserves_per_claim(rig):
    nonce, first = rig.attend(), new_key()
    assert rig.reserve(nonce, first).json() == {"decision": "live"}
    second = rig.reserve(nonce, new_key())
    assert second.json() == {"decision": "replay", "reason": "hold_open"}
    assert rig.close(nonce, first, "released").status_code == 200
    from dataclasses import replace

    rig.config = replace(rig.config, max_reserves=2)  # the released `first` counted as 1
    key = new_key()
    assert rig.reserve(nonce, key).json() == {"decision": "live"}
    assert rig.close(nonce, key, "released").status_code == 200
    limited = rig.reserve(nonce, new_key())
    assert limited.json() == {"decision": "replay", "reason": "meeting_limit"}


# --- close (MV-05, MV-09) ----------------------------------------------------------------------------------------


def test_BQ_M2_4_MV_05_a_close_with_no_reserve_or_for_another_claims_key_is_409_no_hold(rig):
    nonce, other = rig.attend(), rig.attend(OTHER_MEETING, uid=OWNER_2)
    theirs = new_key()
    assert rig.reserve(other, theirs, meeting_id=OTHER_MEETING).status_code == 200
    for key in (new_key(), theirs):  # never reserved here; another meeting's key
        closed = rig.close(nonce, key)
        assert (closed.status_code, closed.json()) == (409, {"error": "no_hold"})
    assert (rig.settled(OWNER), rig.spent(OWNER_2)) == (0, UNIT)


def test_BQ_M2_4_MV_05_a_repeated_close_answers_as_the_first_did_and_counts_nothing_twice(rig):
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    first = rig.close(nonce, key)
    assert (first.status_code, first.json()) == (200, {"outcome": "settled"})
    assert rig.settled() == 2
    again = rig.close(nonce, key, usage={"prompt_token_count": 16, "response_token_count": 16})
    assert (again.status_code, again.json()) == (200, {"outcome": "settled"})
    assert rig.settled() == 2 and [c for c in rig.ledger.names if c == "settle"] == ["settle"]


def test_BQ_M2_4_MV_05_a_second_settle_after_a_release_and_a_release_after_a_settle_are_409(rig):
    nonce, one, two = rig.attend(), new_key(), new_key()
    rig.reserve(nonce, one)
    assert rig.close(nonce, one, "released").json() == {"outcome": "released"}
    assert rig.close(nonce, one).status_code == 409
    rig.reserve(nonce, two)
    assert rig.close(nonce, two).json() == {"outcome": "settled"}
    assert rig.close(nonce, two, "released").status_code == 409
    assert (rig.spent(), rig.settled()) == (2, 2)


def test_BQ_M2_4_MV_09_usage_is_priced_in_tilo_api_from_config_rounded_up_to_at_least_one_paisa(rig):
    for counts, expected in (
        ({"prompt_token_count": 1}, 1),  # 0.0000003 USD is under one paisa: at least 1
        ({"prompt_token_count": 100, "response_token_count": 100}, _priced(100, 100)),
        ({"prompt_token_count": 1000, "response_token_count": 900}, _priced(1000, 900)),
    ):
        nonce, key = rig.attend(), new_key()
        rig.reserve(nonce, key)
        before = rig.settled()
        assert rig.close(nonce, key, usage=counts).status_code == 200
        assert rig.settled() - before == expected, counts
        rig.claims.end(MEETING, nonce)


@pytest.mark.parametrize(
    "usage", [{}, {"total_token_count": 50}, {"prompt_token_count": 0, "response_token_count": CEILING + 1}]
)
def test_BQ_M2_4_MV_09_unpriced_or_empty_usage_books_the_whole_unit(rig, usage):
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    assert rig.close(nonce, key, usage=usage).status_code == 200
    assert rig.settled() == UNIT


def test_BQ_M2_4_MV_09_a_profile_with_no_price_row_books_the_whole_unit(rig):
    from dataclasses import replace

    rig.config = replace(rig.config, cost_usd=None)
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    rig.close(nonce, key)
    assert rig.settled() == UNIT


# --- the bound on one reply (MV-15, SEC-REVIEW-21 B1) --------------------------------------------------------------


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_token_count": CEILING + 1, "response_token_count": 1},
        {"prompt_token_count": 1, "response_token_count": CEILING + 1},
        {"prompt_token_count": 1, "response_token_count": 1, "total_token_count": 2 * CEILING + 1},
    ],
)
def test_BQ_M2_4_MV_15_a_count_over_the_config_ceiling_books_the_whole_unit_never_the_price(rig, usage):
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    assert rig.close(nonce, key, usage=usage).status_code == 200
    assert rig.settled() == UNIT


def test_BQ_M2_4_MV_15_a_count_at_the_ceiling_is_priced_and_the_total_may_be_twice_the_ceiling(rig):
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    usage = {"prompt_token_count": CEILING, "response_token_count": CEILING, "total_token_count": 2 * CEILING}
    assert rig.close(nonce, key, usage=usage).status_code == 200
    assert rig.settled() == _priced(CEILING, CEILING)  # (2048 x 0.30 + 2048 x 1.20) / 1e6 USD, priced up


def test_BQ_M2_4_MV_15_a_priced_charge_above_the_unit_books_the_unit_and_never_more(rig):
    from dataclasses import replace

    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    rig.config = replace(rig.config, cost_usd=lambda i, o: 0.5 if (i, o) != (CEILING, CEILING) else 0.0001)
    assert rig.close(nonce, key, usage={"prompt_token_count": 10, "response_token_count": 10}).status_code == 200
    assert rig.settled() == UNIT  # 0.5 USD would be 4000 paise
    assert rig.spent() == UNIT


def test_BQ_M2_4_MV_15_a_lying_close_cannot_pass_the_lifetime_run_or_day_cap(monkeypatch):
    lie = {"prompt_token_count": 16384, "response_token_count": 16384, "total_token_count": 16384}
    cases = (
        ({"uid_lifetime_minor": 500}, 400),  # a uid with exactly one unit left
        ({"run_minor": UNIT}, 0),  # a run with exactly one unit of room
        ({"global_day_hard_minor": UNIT}, 0),  # a day with exactly one unit under its hard cap
    )
    for caps, already in cases:
        rig = Rig(monkeypatch, **caps)
        if already:
            spend(rig.ledger, OWNER, already)
        nonce, key = rig.attend(), new_key()
        assert rig.reserve(nonce, key).json() == {"decision": "live"}
        assert rig.close(nonce, key, usage=lie).status_code == 200
        assert rig.settled() == already + UNIT and rig.spent() == already + UNIT  # the unit, not the lie
        assert rig.settled() <= rig.caps.uid_lifetime_minor


def test_BQ_M2_4_MV_15_a_count_of_16385_is_422_and_the_claims_end_books_the_unit(rig):
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    too_big = rig.close(nonce, key, usage={"response_token_count": 16385})
    assert too_big.status_code == 422
    assert (rig.spent(), rig.settled()) == (UNIT, 0)  # still held
    rig.claims.end(MEETING, nonce)
    assert (rig.spent(), rig.settled()) == (UNIT, UNIT)  # settled at the whole unit, not released


def test_BQ_M2_4_MV_15_the_ceiling_follows_the_config_and_a_ceiling_sized_reply_priced_over_the_unit_is_503(rig):
    from dataclasses import replace

    nonce, key = rig.attend(), new_key()
    rig.config = replace(rig.config, ceiling=300)
    rig.reserve(nonce, key)
    rig.close(nonce, key, usage={"prompt_token_count": 301})
    assert rig.settled() == UNIT  # above the (lowered) ceiling
    rig.claims.end(MEETING, nonce)
    nonce, key = rig.attend(), new_key()
    rig.config = replace(rig.config, cost_usd=lambda i, o: 1.0)  # a ceiling-sized reply costs far more than the unit
    for call in (rig.reserve(nonce, key), rig.close(nonce, key)):
        assert (call.status_code, call.json()) == (503, {"error": "not_configured"})


# --- the ledger says no (MV-07) ----------------------------------------------------------------------------------


def test_BQ_M2_4_MV_07_a_capped_uid_and_less_than_one_unit_left_are_replay_capped(monkeypatch):
    rig = Rig(monkeypatch, uid_lifetime_minor=500)
    spend(rig.ledger, OWNER, 500)
    nonce = rig.attend()
    spend(rig.ledger, OWNER_2, 450)  # 50 of 500 left: under one unit of 100
    assert rig.reserve(nonce, new_key()).json() == {"decision": "replay", "reason": "capped"}
    other = rig.attend(OTHER_MEETING, uid=OWNER_2)
    assert rig.reserve(other, new_key(), meeting_id=OTHER_MEETING).json() == {"decision": "replay", "reason": "capped"}
    assert (rig.spent(OWNER), rig.spent(OWNER_2)) == (500, 450)  # nothing was held


def test_BQ_M2_4_MV_07_the_switch_in_either_store_is_replay_replay_only(rig):
    nonce = rig.attend()
    rig.flags.set("replay_only", True, reason="test")
    assert rig.reserve(nonce, new_key()).json() == {"decision": "replay", "reason": "replay_only"}
    rig.flags.set("replay_only", False, reason="test")
    assert rig.reserve(nonce, new_key()).json() == {"decision": "live"}
    rig.ledger.trip_replay_only("test")  # the ledger's own durable record
    other = rig.attend(OTHER_MEETING, uid=OWNER_2)
    assert rig.reserve(other, new_key(), meeting_id=OTHER_MEETING).json() == {
        "decision": "replay",
        "reason": "replay_only",
    }


def test_BQ_M2_4_MV_07_an_unreadable_ledger_or_switch_store_is_replay_never_live(monkeypatch):
    rig = Rig(monkeypatch)
    rig.app.dependency_overrides[rig.deps.get_spend_cap_ledger] = lambda: DeadLedger()
    nonce = rig.attend()
    answer = rig.reserve(nonce, new_key())
    assert (answer.status_code, answer.json()["decision"]) == (200, "replay")
    rig = Rig(monkeypatch)
    rig.app.dependency_overrides[rig.deps.get_flag_store] = lambda: DeadFlags()
    answer = rig.reserve(rig.attend(), new_key())
    assert (answer.status_code, answer.json()["decision"]) == (200, "replay")


def test_BQ_M2_4_MV_07_a_trip_of_the_days_hard_cap_mid_meeting_makes_the_next_reply_replay(monkeypatch):
    rig = Rig(monkeypatch, global_day_hard_minor=2 * UNIT)
    nonce, one, two = rig.attend(), new_key(), new_key()
    assert rig.reserve(nonce, one).json() == {"decision": "live"}
    rig.close(nonce, one, usage={})  # the whole unit: 100 of 200
    other = rig.attend(OTHER_MEETING, uid=OWNER_2)
    k = new_key()
    assert rig.reserve(other, k, meeting_id=OTHER_MEETING).json() == {"decision": "live"}
    rig.close(other, k, usage={}, meeting_id=OTHER_MEETING)  # 200 of 200: the ledger trips replay-only
    assert rig.reserve(nonce, two).json()["decision"] == "replay"


def test_BQ_M2_4_MV_07_no_ledger_wired_is_503_not_configured(rig):
    from fastapi import HTTPException

    def unwired():
        raise HTTPException(status_code=503, detail="not_configured")

    rig.app.dependency_overrides[rig.deps.get_spend_cap_ledger] = unwired
    answer = rig.reserve(rig.attend(), new_key())
    assert (answer.status_code, answer.json()) == (503, {"error": "not_configured"})


def test_BQ_M2_4_MV_07_a_replay_reserve_leaves_no_hold_so_the_same_close_is_no_hold(monkeypatch):
    rig = Rig(monkeypatch, uid_lifetime_minor=500)
    spend(rig.ledger, OWNER, 500)
    nonce, key = rig.attend(), new_key()
    assert rig.reserve(nonce, key).json()["decision"] == "replay"
    assert rig.close(nonce, key).status_code == 409


# --- the claim ends (MV-08) --------------------------------------------------------------------------------------


def test_BQ_M2_4_MV_08_when_the_claim_closes_every_open_hold_settles_at_the_whole_unit_not_released(rig):
    nonce, key = rig.attend(), new_key()
    rig.reserve(nonce, key)
    rig.claims.end(MEETING, nonce)
    assert (rig.spent(), rig.settled()) == (UNIT, UNIT)
    assert "release" not in rig.ledger.names
    after = rig.reserve(nonce, new_key())  # the claim is gone: 409, no fallback
    assert (after.status_code, after.json()) == (409, {"error": "not_attending"})


# --- privacy and side effects (MV-10, MV-11) ---------------------------------------------------------------------


def test_BQ_M2_4_MV_10_no_log_line_or_body_carries_a_token_a_nonce_a_key_or_usage(rig, caplog):
    caplog.set_level(logging.DEBUG)
    nonce, key = rig.attend(), new_key()
    answers = [
        rig.reserve(nonce, key),
        rig.close(nonce, key, usage={"prompt_token_count": 1777, "response_token_count": 1555}),
        rig.reserve("w" * 32, key),
        rig.post(RESERVE, {"meeting_id": MEETING, "claim": nonce, "key": key, "user_id": "x"}),
        rig.reserve(nonce, key, token=rig.verifier.register(TICK_SA)),
        rig.reserve(nonce, key, token="forged-token-value"),
    ]
    for answer in answers:
        assert set(answer.json()) in ({"decision"}, {"decision", "reason"}, {"outcome"}, {"error"})
    logged = " ".join(r.getMessage() for r in caplog.records) + " " + caplog.text
    for secret in (rig.token, nonce, key, "forged-token-value", "1777", "1555"):
        assert secret not in logged and all(secret not in a.text for a in answers)


def test_BQ_M2_4_MV_04_the_persons_team_limit_lowers_the_cap_and_an_unreadable_one_is_replay(rig, monkeypatch):
    from tilo_api import team_access

    monkeypatch.setattr(team_access, "user_cap_minor", lambda *_a: 150)  # a personal limit under the ledger's 1000
    spend(rig.ledger, OWNER, 100)  # 50 left under the person's own limit: under one unit of 100
    nonce = rig.attend()
    assert rig.reserve(nonce, new_key()).json() == {"decision": "replay", "reason": "capped"}
    assert rig.spent() == 100  # nothing was held
    monkeypatch.setattr(team_access, "user_cap_minor", lambda *_a: 250)  # a unit fits again
    assert rig.reserve(nonce, new_key()).json() == {"decision": "live"}

    def unreadable(*_a):
        raise ConnectionError("team store")

    monkeypatch.setattr(team_access, "user_cap_minor", unreadable)
    other = rig.attend(OTHER_MEETING, uid=OWNER_2)
    answer = rig.reserve(other, new_key(), meeting_id=OTHER_MEETING).json()
    assert answer == {"decision": "replay", "reason": "unavailable"} and rig.spent(OWNER_2) == 0


@pytest.mark.parametrize("cap", [0, -50])
def test_BQ_M2_4_MV_04_a_team_cap_of_nothing_is_capped_not_unavailable(rig, monkeypatch, cap):
    from tilo_api import team_access

    monkeypatch.setattr(team_access, "user_cap_minor", lambda *_a: cap)
    nonce = rig.attend()
    assert rig.reserve(nonce, new_key()).json() == {"decision": "replay", "reason": "capped"}
    assert rig.spent() == 0  # nothing was held


def test_BQ_M2_4_MV_11_no_event_outbox_entry_world_write_or_model_call(rig):
    def forbidden(*_a, **_k):
        raise AssertionError("the meter route reached a seam it must not")

    for name in ("get_event_writer", "get_outbox_store", "get_router", "get_store", "get_artifact_store"):
        rig.app.dependency_overrides[getattr(rig.deps, name)] = forbidden
    nonce, key = rig.attend(), new_key()
    assert rig.reserve(nonce, key).status_code == 200
    assert rig.close(nonce, key).status_code == 200
    assert rig.reserve(nonce, new_key()).status_code == 200
