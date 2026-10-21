"""Owner 21 Oct ~19:30 (relayed): Tilo finds suitable times for a follow-up meeting, read-only.

`find_times` on the meeting actions route (OIDC + this attend's claim). Busy time comes from the OWNER's own Google
Calendar, read through their own connection (`read_events`, ADR-0048) with the WT-05 `data.transfer` in their Desk;
their Tilo calendar entries and upcoming Tilo meetings; and, with `with_team`, teammates' busy time from their Tilo
calendar entries only (PE-04 `read_busy`: start and end, accepted entries). A teammate's Google account is never read:
WT-01 lets a read touch only the person's own account, for their own feature. The answer is up to three starts, the
first free one on each of the next days, the zone, the owner's Google state and the teammates whose Tilo calendars
counted. Nothing is written to Google or sent; at most five reads per attend."""

from __future__ import annotations

from _morning_brief_lib import Rpc
from _ppl11a_lib import OWNER, PRIYA
from test_MTG_ACTIONS_1_meeting_actions_route import _run, deployed, rig  # noqa: F401

BUSY = {"id": "ev_busy", "title": "Board review", "start": "2026-10-06T10:00:00.000Z",
        "end": "2026-10-06T11:30:00.000Z", "all_day": False, "attendee_count": 3}  # fmt: skip
HOLIDAY = {"id": "ev_holiday", "title": "Holiday", "start": "2026-10-08", "end": "2026-10-09", "all_day": True,
           "attendee_count": 0}  # fmt: skip
PRIYA_DENTIST = {
    "id": "ce_dentist", "org_id": None, "owner": PRIYA, "title": "Dentist", "start": "2026-10-07T03:30:00.000Z",
    "end": "2026-10-07T05:00:00.000Z", "all_day": False, "attendee_count": 0, "source": {"kind": "manual"},
    "state": "accepted", "share": None, "created_by": {"by": "person", "ref": PRIYA, "at": "2026-10-05T10:30:00.000Z"},
    "confirmed_by": None, "flagged": False, "updated_at": "2026-10-05T10:30:00.000Z",
}  # fmt: skip


def _host(r, outcome="ok"):
    import _morning_brief_lib  # noqa: PLC0415
    from tilo_api import deps  # noqa: PLC0415

    rpc = Rpc()
    rpc.outcome["read_events"] = outcome
    r.monkeypatch.setattr(_morning_brief_lib, "EVENTS", [BUSY, HOLIDAY])
    r.app.dependency_overrides[deps.get_meeting_host_client] = lambda: rpc
    r.add("calendar", {**PRIYA_DENTIST, "org_id": r.org})
    return rpc


def _times(r, **args):
    answer = _run(r, "find_times", {"minutes": 30, **args})
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_MTG_TIMES_1_first_free_slot_each_day_from_the_owners_google_and_the_teams_tilo_calendars(deployed):  # noqa: F811
    rpc = _host(deployed)
    got = _times(deployed, with_team=True)
    # Tue 15:30-17:00 IST busy (Google): 17:00 IST; Wed 09:00-10:30 IST Priya's dentist (Tilo): 10:30; Thu: 09:00
    # (an all-day event never blocks a day).
    assert got["slots"] == ["2026-10-06T11:30:00.000Z", "2026-10-07T05:00:00.000Z", "2026-10-08T03:30:00.000Z"]
    assert got["zone"] == "Asia/Kolkata" and got["google"] == "ok" and "Priya Nair" in got["teammates"]
    assert [c[0] for c in rpc.calls] == [OWNER]  # only the owner's own account is ever read (WT-01)
    desk = [c.part for c in deployed.events.calls if c.part.get("type") == "data.transfer"]
    assert len(desk) == 1 and desk[0]["data"]["action_type"] == "read_events"  # WT-05 in the owner's Desk
    assert "Board review" not in str(got) and "Dentist" not in str(got)  # times only, never a title


def test_MTG_TIMES_1_without_the_team_teammates_do_not_count(deployed):  # noqa: F811
    _host(deployed)
    got = _times(deployed)
    assert got["slots"][1] == "2026-10-07T03:30:00.000Z" and got["teammates"] == []


def test_MTG_TIMES_1_no_google_connection_still_answers_from_tilo_and_records_nothing(deployed):  # noqa: F811
    _host(deployed, outcome="not_connected")
    got = _times(deployed, with_team=True)
    assert got["google"] == "not_connected" and got["slots"][0] == "2026-10-06T10:00:00.000Z"
    assert not [c.part for c in deployed.events.calls if c.part.get("type") == "data.transfer"]


def test_MTG_TIMES_1_at_most_five_reads_per_attend_and_closed_args(deployed):  # noqa: F811
    _host(deployed)
    for _ in range(5):
        _times(deployed)
    capped = _run(deployed, "find_times", {"minutes": 30})
    assert capped.status_code == 409 and capped.json()["outcome"] == "cap_reached"
    assert _run(deployed, "find_times", {"minutes": 2}).status_code == 422
    assert _run(deployed, "find_times", {"minutes": 30, "people": ["u_priya"]}).status_code == 422
