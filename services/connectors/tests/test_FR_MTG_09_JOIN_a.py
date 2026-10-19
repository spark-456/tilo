"""MJ-03/04: the Calendar read returns only a capability, never stores it. Offline fake transport."""

import pytest
from _meeting_host_lib import (
    CALENDAR_EVENTS_OWNED,
    EVENTS_URL,
    OWNER,
    make_host_env,
    no_network_and_no_live,  # noqa: F401
)
from tilo_connectors.errors import MeetingHostRefused, ProviderUnavailable

EVENT = "0123456789abcdef0123456789abcdef"


def host():
    h = make_host_env()
    h.cal.seed_event(EVENT)
    return h


def test_FR_MTG_09_JOIN_a_one_narrow_get_no_emission_or_receipt(caplog):
    h = host()
    emitted = list(h.emitted)
    link = h.adapter.join_link(OWNER, EVENT)
    assert link == h.cal.plant.link
    request = h.cal.gets()[0]
    assert request.url == f"{EVENTS_URL}/{EVENT}"
    assert request.params == {"fields": "status,hangoutLink"}
    assert h.spy.asked == [(OWNER, "meeting_host", (CALENDAR_EVENTS_OWNED,), False)]
    assert not h.cal.posts() and len(h.cal.requests) == 1
    assert h.emitted == emitted and not h.receipts.receipts
    assert link not in caplog.text


@pytest.mark.parametrize("value", ["x", "../event", EVENT + "\n"])
def test_FR_MTG_09_JOIN_a_invalid_event_never_fetches_token_or_calendar(value):
    h = host()
    with pytest.raises(MeetingHostRefused) as raised:
        h.adapter.join_link(OWNER, value)
    assert raised.value.rule == "MH-20"
    assert h.cal.requests == []
    assert h.spy.asked == []


@pytest.mark.parametrize("status", [404, 410])
def test_FR_MTG_09_JOIN_a_missing_calendar_event_is_fixed_refusal(status):
    h = host()
    h.cal.fail_next(status)
    with pytest.raises(MeetingHostRefused) as raised:
        h.adapter.join_link(OWNER, EVENT)
    assert raised.value.rule == "MH-20"
    assert len(h.cal.requests) == 1


def test_FR_MTG_09_JOIN_a_cancelled_event_is_not_joinable():
    h = host()
    h.cal.seed_event(EVENT, status="cancelled")
    with pytest.raises(MeetingHostRefused) as raised:
        h.adapter.join_link(OWNER, EVENT)
    assert raised.value.rule == "MH-20"


@pytest.mark.parametrize(
    "value",
    [
        None,
        12,
        "http://meet.google.com/abc-defg-hij",
        "https://meet.google.com/abc-defg-hij?authuser=1",
        "https://meet.google.com/abc-defg-hij\n",
        "https://meet.google.com.example.org/abc-defg-hij",
    ],
)
def test_FR_MTG_09_JOIN_a_hostile_link_never_echoed(value, monkeypatch, caplog):
    h = host()
    original = h.cal._body
    monkeypatch.setattr(h.cal, "_body", lambda ev: {**original(ev), "hangoutLink": value})
    with pytest.raises(MeetingHostRefused) as raised:
        h.adapter.join_link(OWNER, EVENT)
    assert raised.value.rule == "MH-21"
    assert "meet.google.com" not in str(raised.value) + repr(raised.value) + caplog.text


@pytest.mark.parametrize("status", [429, 500])
def test_FR_MTG_09_JOIN_a_unavailable_never_waits_or_retries(status):
    h = host()
    h.cal.fail_next(status)
    with pytest.raises(ProviderUnavailable):
        h.adapter.join_link(OWNER, EVENT)
    assert len(h.cal.requests) == 1 and h.sleeps == []
