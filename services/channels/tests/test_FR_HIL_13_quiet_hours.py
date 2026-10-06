"""FR-HIL-13 (PRD 10.6): Quiet hours — during quiet hours only `gate` and `blocked` notify."""

from __future__ import annotations

import pytest
from tilo_channels.quiet_hours import NotificationGate, QuietHours, is_quiet_hours, parse_quiet_hours, should_notify

USER = "u_alice"


class FakePrefs:
    def __init__(self, data: dict[str, dict] | None = None) -> None:
        self._data = dict(data or {})

    def get(self, user_id: str) -> dict | None:
        return self._data.get(user_id)


def test_FR_HIL_13_daytime_window_inside_and_outside() -> None:
    prefs = {"quiet_hours": {"start": "13:00", "end": "15:00", "timezone": "UTC"}}
    assert is_quiet_hours(prefs, now="2026-10-06T13:00:00.000Z") is True
    assert is_quiet_hours(prefs, now="2026-10-06T14:29:00.000Z") is True
    for kind in ("needs_you", "meeting", "nudge"):
        assert should_notify(kind, prefs=prefs, now="2026-10-06T14:00:00.000Z") is False
    assert is_quiet_hours(prefs, now="2026-10-06T12:59:00.000Z") is False
    assert is_quiet_hours(prefs, now="2026-10-06T15:00:00.000Z") is False
    assert should_notify("needs_you", prefs=prefs, now="2026-10-06T12:59:00.000Z") is True
    assert should_notify("needs_you", prefs=prefs, now="2026-10-06T15:00:00.000Z") is True


def test_FR_HIL_13_window_crossing_midnight() -> None:
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "UTC"}}
    for ts in (
        "2026-10-06T22:00:00.000Z",
        "2026-10-06T23:45:00.000Z",
        "2026-10-07T00:15:00.000Z",
        "2026-10-07T06:59:00.000Z",
    ):
        assert is_quiet_hours(prefs, now=ts) is True
        assert should_notify("needs_you", prefs=prefs, now=ts) is False
    for ts in ("2026-10-07T07:00:00.000Z", "2026-10-07T12:00:00.000Z", "2026-10-07T21:59:00.000Z"):
        assert is_quiet_hours(prefs, now=ts) is False
        assert should_notify("needs_you", prefs=prefs, now=ts) is True


def test_FR_HIL_13_timezone_conversion_per_user() -> None:
    ist_prefs = {"quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "Asia/Kolkata"}}
    utc_prefs = {"quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "UTC"}}
    top_tz_prefs = {"time_zone": "Asia/Kolkata", "quiet_hours": {"start": "22:00", "end": "07:00"}}
    instant = "2026-10-06T17:00:00.000Z"  # 22:30 IST, 17:00 UTC
    assert is_quiet_hours(ist_prefs, now=instant) is True and is_quiet_hours(top_tz_prefs, now=instant) is True
    assert is_quiet_hours(utc_prefs, now=instant) is False
    assert should_notify("needs_you", prefs=ist_prefs, now=instant) is False
    assert should_notify("needs_you", prefs=utc_prefs, now=instant) is True


@pytest.mark.parametrize("urgent_type", ["gate", "blocked"])
@pytest.mark.parametrize("suppressed_type", ["needs_you", "meeting", "nudge", "fyi", "info", "consent"])
def test_FR_HIL_13_gate_and_blocked_always_notify_during_quiet_hours(urgent_type: str, suppressed_type: str) -> None:
    prefs = {"quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "Asia/Kolkata"}}
    instant = "2026-10-06T18:00:00.000Z"
    assert should_notify(urgent_type, prefs=prefs, now=instant) is True
    assert should_notify({"rung": urgent_type, "kind": "needs_you"}, prefs=prefs, now=instant) is True
    assert should_notify(suppressed_type, prefs=prefs, now=instant) is False
    assert should_notify({"rung": suppressed_type, "kind": suppressed_type}, prefs=prefs, now=instant) is False


def test_FR_HIL_13_notification_gate_records_in_app_even_when_notification_suppressed() -> None:
    store = FakePrefs({USER: {"quiet_hours": {"start": "22:00", "end": "07:00", "timezone": "UTC"}}})
    sent: list[dict] = []
    gate = NotificationGate(preferences=store, clock=lambda: "2026-10-06T23:15:00.000Z", sender=sent.append)
    d1 = gate.deliver(USER, {"id": "c_needs", "kind": "needs_you", "rung": "needs_you"})
    d2 = gate.deliver(USER, {"id": "c_blocked", "kind": "needs_you", "rung": "blocked"})
    d3 = gate.deliver(USER, {"id": "c_gate", "kind": "gate", "rung": "gate"})
    assert (d1.notified, d2.notified, d3.notified) == (False, True, True)
    assert (d1.in_app, d2.in_app, d3.in_app) == (True, True, True)
    assert [c["id"] for c in sent] == ["c_blocked", "c_gate"]
    assert [c["id"] for c in gate.in_app_items(USER)] == ["c_needs", "c_blocked", "c_gate"]


def test_FR_HIL_13_unconfigured_or_disabled_quiet_hours_do_not_suppress() -> None:
    assert parse_quiet_hours(None) is None and parse_quiet_hours({}) is None
    disabled = {"quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00", "timezone": "UTC"}}
    assert parse_quiet_hours(disabled) is None
    assert should_notify("needs_you", prefs=disabled, now="2026-10-06T23:30:00.000Z") is True
    with pytest.raises(ValueError):
        QuietHours(start="25:00", end="07:00", timezone="UTC")
    with pytest.raises(ValueError):
        QuietHours(start="22:00", end="07:00", timezone="Not/AZone")
