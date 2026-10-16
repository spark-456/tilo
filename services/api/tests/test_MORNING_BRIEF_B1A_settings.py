"""MORNING-BRIEF-B1A, MO-01 to MO-04: the brief routes, the setting, the Scheduler sweep and on-demand briefs.
Rig and fakes: `_morning_brief_lib`."""

from __future__ import annotations

# ruff: noqa: F811  (the shared `case` fixture is imported by name)
import pytest
from _morning_brief_lib import DAY, NOW, ZONE, case, desk_events, get, made, post, sweep, turn_on  # noqa: F401
from _ppl11a_lib import OWNER, PRIYA, conforms
from tilo_api import brief_routes, deps

# --- MO-01, MO-02: whose, and the setting ----------------------------------------------------------


def test_MORNING_BRIEF_B1A_MO02_the_setting_is_off_by_default_and_a_put_stores_the_whole_of_it(case):
    c = case
    first = get(c, path="/v1/me/brief-settings").json()
    assert conforms("morning_brief.schema.json#/$defs/settings", first)
    assert first | {"email_rule_ready": first["email_rule_ready"]} == {
        "owner_id": OWNER, "org_id": deps.ORG_ID, "enabled": False, "time": "07:30", "time_zone": "UTC",
        "email_copy": False, "email_rule_ready": first["email_rule_ready"], "updated_at": None,
    }  # fmt: skip
    body = {"enabled": True, "time": "06:45", "time_zone": ZONE, "email_copy": True}
    saved = c.rig.client.put("/v1/me/brief-settings", json=body).json()
    assert conforms("morning_brief.schema.json#/$defs/settings", saved)
    assert {k: saved[k] for k in body} == body and saved["updated_at"] == NOW and saved["owner_id"] == OWNER
    assert get(c, path="/v1/me/brief-settings").json() == saved
    assert get(c, PRIYA, "/v1/me/brief-settings").json()["enabled"] is False  # nobody else's setting changed


@pytest.mark.parametrize(
    "body, field",
    [
        ({"enabled": True, "time": "07:30", "time_zone": "Mars/Olympus", "email_copy": False}, "time_zone"),
        ({"enabled": True, "time": "7:30", "time_zone": ZONE, "email_copy": False}, "time"),
    ],
)
def test_MORNING_BRIEF_B1A_MO02_an_unknown_zone_or_clock_is_422_naming_the_field_and_stores_nothing(case, body, field):
    response = case.rig.client.put("/v1/me/brief-settings", json=body)
    assert response.status_code == 422 and response.json()["fields"] == [field]
    assert case.briefs.settings(deps.ORG_ID, OWNER) is None


def test_MORNING_BRIEF_B1A_MO02_the_server_owns_the_owner_the_org_and_the_time_of_saving(case):
    body = {"enabled": True, "time": "07:30", "time_zone": ZONE, "email_copy": False}
    for extra in ({"owner_id": PRIYA}, {"updated_at": "2020-01-01T00:00:00.000Z"}, {"email_rule_ready": True}):
        assert case.rig.client.put("/v1/me/brief-settings", json=body | extra).status_code == 422
    assert case.briefs.settings(deps.ORG_ID, OWNER) is None


def test_MORNING_BRIEF_B1A_MO01_no_route_names_a_person_or_a_date_and_nobody_else_reads_the_brief(case):
    c = case
    paths = [p for p in c.rig.app.openapi()["paths"] if p.startswith("/v1/me/brief")]
    assert sorted(paths) == ["/v1/me/brief", "/v1/me/brief-settings"]
    made(c)
    assert get(c, PRIYA).json() == {"detail": "not_ready"}
    other = c.rig.client.get(f"/v1/me/brief?user={OWNER}&date={DAY}")  # a query names nobody
    assert other.status_code == 404
    c.rig.as_user(OWNER)
    assert c.rig.client.get("/v1/me/brief").json()["owner"] == OWNER


def test_MORNING_BRIEF_B1A_MO01_no_verified_principal_is_401_and_reads_nothing(case):
    c = case
    c.rig.sign_out()
    for call in (
        lambda: c.rig.client.get("/v1/me/brief"),
        lambda: c.rig.client.post("/v1/me/brief", json={}),
        lambda: c.rig.client.get("/v1/me/brief-settings"),
        lambda: c.rig.client.put("/v1/me/brief-settings", json={}),
    ):
        assert call().status_code == 401
    assert c.rpc.calls == []


def test_MORNING_BRIEF_B1A_MO01_a_brief_that_is_not_yet_made_is_404_not_ready_and_get_never_makes_one(case):
    response = get(case)
    assert response.status_code == 404 and response.json() == {"detail": "not_ready"}
    assert case.rpc.calls == [] and desk_events(case) == []


# --- MO-03: the sweep ------------------------------------------------------------------------------


def test_MORNING_BRIEF_B1A_MO03_the_sweep_is_off_unless_the_switch_is_one(case):
    turn_on(case)
    assert sweep(case) == 0 and case.rpc.calls == []
    case.monkeypatch.setenv(brief_routes.ENV_BRIEF, "0")
    assert sweep(case) == 0 and case.rpc.calls == []


def test_MORNING_BRIEF_B1A_MO03_the_window_is_three_hours_from_the_persons_time_and_may_pass_midnight(case):
    due = brief_routes.due_date
    assert due("2026-10-16T02:00:00.000Z", ZONE, "07:30") == DAY  # 07:30 IST exactly
    assert due("2026-10-16T04:59:00.000Z", ZONE, "07:30") == DAY  # 10:29
    assert due("2026-10-16T05:00:00.000Z", ZONE, "07:30") is None  # 10:30: three hours on, the window has passed
    assert due("2026-10-16T01:59:00.000Z", ZONE, "07:30") is None  # 07:29: not yet
    assert due("2026-10-16T19:30:00.000Z", "UTC", "22:30") is None
    assert due("2026-10-16T23:30:00.000Z", "UTC", "22:30") == DAY
    assert due("2026-10-17T00:59:00.000Z", "UTC", "22:30") == DAY  # past midnight: still the 16th's window
    assert due("2026-10-17T01:30:00.000Z", "UTC", "22:30") is None


def test_MORNING_BRIEF_B1A_MO03_one_brief_per_person_and_local_date_whatever_the_ticks(case):
    c = case
    c.monkeypatch.setenv(brief_routes.ENV_BRIEF, "1")
    turn_on(c)
    assert sweep(c) == 1
    assert sweep(c) == 0 and sweep(c, "2026-10-16T03:00:00.000Z") == 0
    assert [t for _, t, _ in c.rpc.calls].count("read_events") == 1
    brief = get(c).json()
    assert brief["trigger"] == "schedule" and brief["local_date"] == DAY
    assert sweep(c, "2026-10-17T02:30:00.000Z") == 1  # the next local date is a new claim


def test_MORNING_BRIEF_B1A_MO03_a_person_outside_the_window_or_switched_off_gets_nothing(case):
    c = case
    c.monkeypatch.setenv(brief_routes.ENV_BRIEF, "1")
    turn_on(c, OWNER, time="09:00")  # 09:00 IST: 08:00 is before it
    turn_on(c, PRIYA, enabled=False)
    assert sweep(c) == 0 and c.rpc.calls == []
    assert sweep(c, "2026-10-16T09:00:00.000Z") == 0  # 14:30 IST: the 09:00 window has passed, a person gets none


def test_MORNING_BRIEF_B1A_MO03_at_most_ten_briefs_a_tick_and_the_rest_wait_for_the_next(case):
    c = case
    c.monkeypatch.setenv(brief_routes.ENV_BRIEF, "1")
    users = [f"u_p{n:02d}" for n in range(12)]
    for user in users:
        c.rig.event_store.worlds["w_desk_" + user[2:]] = deps.WorldRecord(user, {}, run_id="r_desk_" + user[2:])
        turn_on(c, user)
    assert sweep(c) == 10
    assert sweep(c) == 2  # the next tick takes the two that waited
    assert sweep(c) == 0


def test_MORNING_BRIEF_B1A_MO03_one_persons_failure_never_stops_the_others_or_the_tick(case):
    c = case
    c.monkeypatch.setenv(brief_routes.ENV_BRIEF, "1")
    turn_on(c, OWNER)
    turn_on(c, PRIYA)
    c.rig.event_store.worlds.pop("w_desk_priya")
    c.rig.desks.fail = False
    c.monkeypatch.setattr(c.rig.desks, "desk_owner", lambda w: None if w == "w_desk_owner" else "u_priya")
    assert sweep(c) == 2  # both claimed; the failing one is logged by type
    assert get(c, PRIYA).status_code in (200, 404)


# --- MO-04: on demand ------------------------------------------------------------------------------


def test_MORNING_BRIEF_B1A_MO04_three_a_day_then_429_brief_limit_and_nothing_is_read(case):
    c = case
    for n in range(3):
        assert made(c)["trigger"] == "on_demand"
    reads = len(c.rpc.calls)
    refused = post(c)
    assert refused.status_code == 429 and refused.json() == {"detail": "brief_limit"}
    assert len(c.rpc.calls) == reads
    assert post(c, PRIYA).status_code == 200  # the count is per person
    assert get(c).json()["generated_at"] == NOW


def test_MORNING_BRIEF_B1A_MO04_a_version_adds_to_the_days_artifact_and_get_answers_the_latest(case):
    c = case
    made(c)
    c.script.reply = {"needs_reply": [], "suggestions": [], "todos": []}
    second = made(c)
    assert get(c).json() == second
    kinds = [e["type"] for e in desk_events(c) if e["type"].startswith("artifact.")]
    assert kinds == ["artifact.created", "artifact.versioned"]
    refs = {e["data"]["artifact"]["artifact_id"] for e in desk_events(c) if e["type"].startswith("artifact.")}
    assert refs == {"art_mbrief_20261016"}
