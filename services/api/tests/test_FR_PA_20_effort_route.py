"""FR-PA-20 (Should; PRD addendum people and agents, decision D-4): "Effort tracker: Tilo's own effort only, credits and
time-saved estimate per meeting and per task from P8 (14.4), shown on S-26 and the world HUD. No human time tracking."
Acceptance: "Numbers equal the ledger for 5 fixture runs; no per-person human-time field exists in any contract."
Depends on FR-MTR-05 (the time-saved method with ranges and the method page, PRD 14.2).

This is the API half (no screen): one owner-only read, `GET /v1/effort`, whose numbers come only from the Treasury
ledger and the recorded events of the worlds the signed-in person owns. Routes, shapes, seams and defaults are pinned
in `API_FR_PA_20.md`; the contract and no-human-time guards are in `test_FR_PA_20_no_human_time.py`.

    GET /v1/effort   200 {credit_usd, totals, meetings[], tasks[]}   404 not_found   401   503 (see below)

Sources: PRD 14.1 (credit), 14.2 and 14.4 (time saved), 14.5 FR-MTR-05, FR-MTR-10 (`/costs`, same ledger seam), PRD
addendum D-4 and FR-PA-20, `people.rules.md` PE-22 (no-store), PE-26 (a world role changes nothing on a person-scoped
read), HR-1 (complete or absent), PL-01, NFR-24, EFF-01. These fail today: the route does not exist (404 from the
router, caught by `Rig.require_route`) and `tilo_api.deps.get_time_baselines` does not exist. No network, no provider.
"""

from __future__ import annotations

import copy
import json
import math
import os
from types import SimpleNamespace

import jsonschema
import pytest
from _api_lib import REPO_ROOT
from _fr_pa_20_lib import (
    ALLOWED_KEYS,
    BASELINES,
    CREDIT_USD,
    GUEST,
    HUMAN_TIME_KEY,
    METHOD_URL,
    OWNER_RUNS,
    PATH,
    R_EFFORT,
    RUN_OF,
    SENTINEL,
    TIME_SAVED,
    Effort,
    commits,
    expected_time_saved,
    ledger_credits,
    make,
    meeting_row,
    minutes_of,
    task,
    triple,
    walk_keys,
    walk_strings,
)
from _ppl11a_lib import ORG, OTHER_ORG, OWNER, PRIYA, STANDARD_PERSONS
from _ppl11c_lib import assert_gated, assert_unwired_is_503

SAM = "u_sam"  # a person of the org who owns no world and no meeting
CREDITS = {"w_e1": 80.0, "w_e2": 120.0, "w_e3": 42.0, "w_e4": 160.0, "w_e5": 0.0}  # worked out by hand in the lib
MEETINGS_LISTED = ["mt_e1", "mt_e2", "mt_foreign", "mt_none"]  # u_owner's, by id; mt_gone (deleted) is not there


@pytest.fixture()
def fx(people_rig, tmp_path) -> Effort:
    return make(people_rig, tmp_path)


def _time_saved_validator() -> jsonschema.Draft202012Validator:
    meter = json.loads((REPO_ROOT / "contracts" / "meter.schema.json").read_text("utf-8"))
    return jsonschema.Draft202012Validator(
        {"$schema": meter["$schema"], "$ref": "#/$defs/time_saved", "$defs": meter["$defs"]}
    )


def _every_time_saved(body: dict) -> list[dict]:
    return [
        body["totals"]["time_saved"],
        *(m["time_saved"] for m in body["meetings"]),
        *(t["time_saved"] for t in body["tasks"]),
    ]


# --- the shape ------------------------------------------------------------------------------------


def test_FR_PA_20_the_owner_reads_one_allowlisted_body_with_rows_in_a_fixed_order(fx):
    body = fx.body()
    assert set(body) == ALLOWED_KEYS["top"]
    assert body["credit_usd"] == CREDIT_USD
    assert set(body["totals"]) == ALLOWED_KEYS["totals"]
    assert all(set(m) == ALLOWED_KEYS["meeting"] for m in body["meetings"])
    assert all(set(t) == ALLOWED_KEYS["task"] for t in body["tasks"])
    assert all(set(ts) == ALLOWED_KEYS["time_saved"] for ts in _every_time_saved(body))
    assert [t["run_id"] for t in body["tasks"]] == ["r_e1", "r_e2", "r_e3", "r_e4", "r_e5"], (
        "a task is a run, by run id"
    )
    assert [m["meeting_id"] for m in body["meetings"]] == MEETINGS_LISTED


# --- credits: numbers equal the ledger (the acceptance test) --------------------------------------


@pytest.mark.parametrize(("world", "credits"), CREDITS.items())
def test_FR_PA_20_each_of_the_five_fixture_runs_credits_equal_the_ledger(fx, world, credits):
    run = OWNER_RUNS[world]
    row = task(fx.body(), world)
    assert row["run_id"] == run
    assert row["credits"] == ledger_credits(fx.ledger, [run]) == credits  # equal, not close
    assert math.isclose(row["usd"], credits * CREDIT_USD, rel_tol=0, abs_tol=1e-12)


def test_FR_PA_20_the_totals_equal_the_ledger_of_the_owners_runs_and_no_one_elses(fx):
    body = fx.body()
    mine = list(OWNER_RUNS.values())
    assert body["totals"]["credits"] == ledger_credits(fx.ledger, mine) == 402.0
    assert body["totals"]["credits"] == math.fsum(t["credits"] for t in body["tasks"])
    assert math.isclose(body["totals"]["usd"], 402.0 * CREDIT_USD, rel_tol=0, abs_tol=1e-12)
    assert (body["totals"]["tasks"], body["totals"]["completed_tasks"]) == (5, 3)  # r_e4 and r_e5 never completed
    assert ledger_credits(fx.ledger, ["r_p1"]) == 120.0, "the other owner's spend is in the ledger, and not in the body"
    assert "r_p1" not in json.dumps(body)


def test_FR_PA_20_FR_MTR_01_only_committed_spend_counts_at_each_entrys_recorded_credits(fx):
    """r_e2 holds a reservation that was never committed and r_e4 two calls priced by two sheets (40 at v1, 120 at v2):
    the body is the ledger's 120 and 160, not 120 + the reserve, not 80 or 240."""
    kinds = {e.kind for e in fx.ledger if e.run == "r_e2"}
    assert {"reserve", "commit"} <= kinds, "the fixture should hold a reservation next to the commit"
    body = fx.body()
    assert task(body, "w_e2")["credits"] == 120.0
    assert task(body, "w_e4")["credits"] == 160.0
    assert {e.price_effective_date for e in commits(fx.ledger, ["r_e4"])} == {"2026-01-01", "2026-06-01"}


def test_FR_PA_20_FR_MTR_10_the_credits_are_the_cost_report_of_the_same_runs(fx):
    """One ledger, one reading: `/costs` and `/v1/effort` give the same credits per run and in total."""
    effort = fx.body()
    fx.rig.as_user(OWNER, role="owner", world_id=None)
    costs = fx.rig.client.get("/costs")
    assert costs.status_code == 200
    report = costs.json()
    assert report["totals"]["credits"] == effort["totals"]["credits"]
    assert {t["run_id"]: t["credits"] for t in report["tasks"]} == {t["run_id"]: t["credits"] for t in effort["tasks"]}
    assert report["credit_usd"] == effort["credit_usd"]


# --- time saved (PRD 14.2 method, FR-MTR-05) ------------------------------------------------------


@pytest.mark.parametrize("world", OWNER_RUNS)
def test_FR_PA_20_FR_MTR_05_a_tasks_time_saved_is_its_finished_units_times_the_baselines(fx, world):
    """minutes = sum(unit_count x median), low = sum(unit_count x 25th percentile), high = sum(unit_count x 75th)."""
    row = task(fx.body(), world)
    assert triple(row["time_saved"]) == TIME_SAVED[world]
    assert triple(row["time_saved"]) == expected_time_saved(fx.store.events[world], BASELINES)


def test_FR_PA_20_FR_MTR_05_every_estimate_has_its_range_and_links_to_the_method(fx):
    body = fx.body()
    validator = _time_saved_validator()
    for ts in _every_time_saved(body):
        validator.validate(ts)  # the meter.schema.json time_saved shape, unchanged
        assert ts["low"] <= ts["minutes"] <= ts["high"]
        assert ts["method_url"] == METHOD_URL and ts["method_url"].startswith("https://")


def test_FR_PA_20_FR_MTR_05_steering_is_reported_as_not_measured_not_subtracted_as_zero(fx):
    """No attention spans are read by this route (BQ-PA20-3), so the meter's own rule applies: `steering_measured` is
    false (MT-05) and nothing is subtracted (the hand-worked minutes above are gross)."""
    body = fx.body()
    assert [ts["steering_measured"] for ts in _every_time_saved(body)] == [False] * (
        len(body["tasks"]) + len(body["meetings"]) + 1
    )


def test_FR_PA_20_FR_MTR_05_the_minutes_come_from_the_baselines_seam_not_from_constants(fx):
    fx.baselines["units"]["reply_handled"]["median"] = 4.0
    fx.baselines["method_url"] = "https://tilo.example.org/method/v2"
    body = fx.body()
    assert triple(task(body, "w_e1")["time_saved"])[0] == 3 * 4.0 + 10 * 0.5
    assert {ts["method_url"] for ts in _every_time_saved(body)} == {"https://tilo.example.org/method/v2"}


def test_FR_PA_20_a_unit_type_without_a_baseline_a_zero_count_and_a_redelivery_add_nothing(fx):
    body = fx.body()
    e3 = task(body, "w_e3")["time_saved"]
    assert triple(e3) == (2.0, 1.0, 4.0), "research x2 has no baseline: zero, never a guess; mail_triaged x4 counts"
    assert triple(task(body, "w_e4")["time_saved"]) == (0.0, 0.0, 0.0), "unit_count 0 adds nothing"
    assert triple(task(body, "w_e2")["time_saved"]) == (14.0, 8.0, 20.0), "the same event delivered twice counts once"
    fx.baselines["units"] = {}
    assert fx.get().status_code == 200
    assert all(triple(t["time_saved"]) == (0.0, 0.0, 0.0) for t in fx.get().json()["tasks"]), "no baselines: all zero"


def test_FR_PA_20_a_run_with_nothing_finished_reports_zero_minutes_with_its_range_not_null(fx):
    row = task(fx.body(), "w_e5")
    assert row["time_saved"] == {
        "minutes": 0,
        "low": 0,
        "high": 0,
        "steering_measured": False,
        "method_url": METHOD_URL,
    }
    assert row["credits"] == 0 and row["usd"] == 0 and row["completed"] is False


# --- per meeting, per task, total -----------------------------------------------------------------


def test_FR_PA_20_a_meetings_row_is_its_outpost_worlds_numbers(fx):
    body = fx.body()
    for meeting_id, world in (("mt_e1", "w_e1"), ("mt_e2", "w_e2")):
        row = meeting_row(body, meeting_id)
        assert (row["world_id"], row["tasks"]) == (world, 1)
        assert row["credits"] == CREDITS[world]
        assert triple(row["time_saved"]) == TIME_SAVED[world]
    assert [task(body, w)["meeting_id"] for w in OWNER_RUNS] == ["mt_e1", "mt_e2", None, None, None]


def test_FR_PA_20_a_meeting_without_a_world_is_a_zero_row_not_an_error(fx):
    row = meeting_row(fx.body(), "mt_none")
    assert row["world_id"] is None and row["tasks"] == 0 and row["credits"] == 0 and row["usd"] == 0
    assert triple(row["time_saved"]) == (0.0, 0.0, 0.0) and row["time_saved"]["method_url"] == METHOD_URL


def test_FR_PA_20_a_meeting_pointing_at_someone_elses_world_counts_nothing_and_looks_like_no_world(fx):
    """`mt_foreign` is u_owner's, its `world_id` is u_priya's `w_p1` (120 credits, 10.5 minutes). Not the owner's world:
    the row is a no-world row, with no oracle on whether that world exists, and none of its numbers or ids appear."""
    body = fx.body()
    foreign, none = meeting_row(body, "mt_foreign"), meeting_row(body, "mt_none")
    assert {k: v for k, v in foreign.items() if k != "meeting_id"} == {
        k: v for k, v in none.items() if k != "meeting_id"
    }
    text = json.dumps(body)
    assert "w_p1" not in text and "r_p1" not in text and "mt_p1" not in text
    assert body["totals"]["credits"] == 402.0, "u_priya's 120 are not in u_owner's total"


def test_FR_PA_20_a_deleted_meeting_is_gone_but_its_worlds_spend_is_still_a_task(fx):
    """FR-MTG-10: a deleted meeting is gone for everyone. The credits the run cost are real and stay in the totals, as
    an unlinked task (`meeting_id` null)."""
    body = fx.body()
    assert "mt_gone" not in json.dumps(body)
    row = task(body, "w_e3")
    assert row["meeting_id"] is None and row["credits"] == 42.0 and triple(row["time_saved"]) == (2.0, 1.0, 4.0)
    assert body["totals"]["credits"] == 402.0


def test_FR_PA_20_the_totals_are_the_sum_of_the_task_rows_and_never_add_the_meeting_rows_again(fx):
    body = fx.body()
    assert triple(body["totals"]["time_saved"]) == minutes_of(body["tasks"]) == (31.5, 17.5, 49.0)
    assert body["totals"]["tasks"] == len(body["tasks"])
    meeting_credits = math.fsum(m["credits"] for m in body["meetings"])
    assert meeting_credits == 200.0 and meeting_credits <= body["totals"]["credits"], "meetings are a view, not extra"


# --- who sees what: owner only, no oracle ---------------------------------------------------------


def test_FR_PA_20_each_person_reads_only_the_worlds_she_owns(fx):
    mine, hers = fx.body(OWNER), fx.body(PRIYA)
    assert [t["run_id"] for t in hers["tasks"]] == ["r_p1"] and [m["meeting_id"] for m in hers["meetings"]] == ["mt_p1"]
    assert hers["totals"]["credits"] == 120.0 and triple(hers["totals"]["time_saved"]) == TIME_SAVED["w_p1"]
    assert task(hers, "w_p1")["meeting_id"] == "mt_p1", "linked by her own meeting, not by u_owner's mt_foreign"
    for foreign in ("w_e1", "r_e1", "mt_e1", "mt_foreign", "w_e5"):
        assert foreign not in json.dumps(hers), foreign
    assert hers["totals"]["credits"] != mine["totals"]["credits"]


def test_FR_PA_20_a_person_who_owns_no_world_gets_zeros_not_a_refusal(fx):
    body = fx.body(SAM)
    assert body["tasks"] == [] and body["meetings"] == []
    assert body["totals"]["credits"] == 0 and body["totals"]["tasks"] == 0 and body["totals"]["completed_tasks"] == 0
    assert triple(body["totals"]["time_saved"]) == (0.0, 0.0, 0.0)
    assert body["totals"]["time_saved"]["method_url"] == METHOD_URL


@pytest.mark.parametrize("role", ["viewer", "approver", "team_lead"])
def test_FR_PA_20_PE_26_a_world_role_on_the_session_changes_nothing(fx, role):
    """The read is the signed-in person's own; being a Viewer of someone's world shows nothing of it, and the owner's
    id with a lesser world role still reads her own worlds (like the plate)."""
    owners, hers = fx.body(OWNER), fx.body(PRIYA)
    fx.rig.as_user(OWNER, role=role, world_id="w_p1")
    assert fx.get().json() == owners
    fx.rig.as_user(PRIYA, role=role, world_id="w_e1")  # a Viewer of u_owner's world: still only her own
    response = fx.get()
    assert response.status_code == 200 and response.json() == hers
    assert "w_e1" not in response.text


def test_FR_PA_20_a_stranger_and_a_person_of_another_org_get_the_same_404_with_no_numbers(fx):
    outsider = copy.deepcopy(STANDARD_PERSONS[OWNER])
    outsider.update(id="u_outsider", org_id=OTHER_ORG, display_name="Eve Outsider", email="eve@example.net")
    fx.rig.add("persons", outsider)  # a record, but of an org this process does not serve
    bodies = []
    for who in ("u_nobody", "u_outsider"):
        fx.rig.as_user(who)
        response = fx.get()
        assert response.status_code == 404, (who, response.status_code)
        bodies.append(response.content)
    assert bodies[0] == bodies[1] == b'{"detail":"not_found"}'  # the one body of the people API (no oracle)


def test_FR_PA_20_signed_out_is_401_and_a_deployed_visitor_is_gated_before_any_seam(fx, people_rig):
    fx.rig.sign_out()
    assert fx.get().status_code == 401
    assert_gated(people_rig, [R_EFFORT])  # SEC-15: visitor 403 under_construction, undeclared 403, signed out 401


# --- failing and unwired seams: complete or absent (HR-1) -----------------------------------------


def test_FR_PA_20_unwired_people_stores_ledger_or_baselines_is_503_not_configured_and_never_partial(fx, people_rig):
    for name, provider in (("get_ledger", lambda: fx.ledger), ("get_time_baselines", lambda: fx.baselines)):
        fx.wire(name, None)  # back to the production default of the seam
        response = fx.get()
        assert response.status_code == 503 and response.json() == {"detail": "not_configured"}, (
            name,
            response.text[:200],
        )
        assert "tasks" not in response.text and "credits" not in response.text
        fx.wire(name, provider)
    assert fx.get().status_code == 200
    assert_unwired_is_503(people_rig, [R_EFFORT], "people_stores")  # last: it builds a second rig on the same app


class _BrokenLedger:
    def __iter__(self):
        raise RuntimeError("the ledger store is down")

    def __len__(self):
        raise RuntimeError("the ledger store is down")


def _down():
    raise RuntimeError("the store is down")


def _down_any(*_args, **_kwargs):
    raise RuntimeError("the store is down")


def test_FR_PA_20_a_failing_ledger_is_the_fixed_503_with_no_numbers_and_no_trace(fx):
    """HR-1: an honest figure is complete or absent. A ledger that cannot be read (its seam raising, or a read that
    raises half way) is 503 `unavailable`, the people API's body for a source that fails (PE-27 plate, ambiguity 6)."""
    fx.set_ledger(_BrokenLedger())
    reading = fx.get()
    fx.wire("get_ledger", _down)
    resolving = fx.get()
    for response in (reading, resolving):
        assert response.status_code == 503 and response.json() == {"detail": "unavailable"}, response.text[:200]
        assert "credits" not in response.text and "Traceback" not in response.text and "down" not in response.text


def test_FR_PA_20_failing_baselines_or_failing_people_stores_are_the_same_fixed_503(fx):
    fx.wire("get_time_baselines", _down)
    first = fx.get()
    fx.wire("get_time_baselines", lambda: fx.baselines)
    for method in ("list", "get"):
        fx.rig.monkeypatch.setattr(fx.rig.stores.meetings, method, _down_any)
    second = fx.get()
    for response in (first, second):
        assert response.status_code == 503 and response.json() == {"detail": "unavailable"}, response.text[:200]
        assert "tasks" not in response.text


def test_FR_PA_20_a_malformed_baseline_is_503_not_configured_never_a_guess_or_a_500(fx):
    """The baselines are configuration (EV-G2, FR-MTR-01 pattern): a sheet that breaks its rules refuses the read."""
    for broken in (
        {"method_url": METHOD_URL, "units": {"reply_handled": {"p25": 5.0, "median": 3.5, "p75": 2.0}}},  # unordered
        {"method_url": "http://insecure.example.com/m", "units": {}},  # the meter's method_url is https only
        {"method_url": METHOD_URL, "units": {"reply_handled": {"p25": -1.0, "median": 3.5, "p75": 5.0}}},
        {"method_url": METHOD_URL},
        None,
    ):
        fx.baselines = broken
        response = fx.get()
        assert response.status_code == 503 and response.json() == {"detail": "not_configured"}, (
            broken,
            response.text[:200],
        )


# --- headers, read-only, determinism --------------------------------------------------------------


def test_FR_PA_20_PE_22_every_answer_is_no_store_when_it_answers_and_when_it_refuses(fx):
    answered = fx.get()
    fx.rig.as_user("u_nobody")
    refused = fx.get()
    fx.rig.as_user(OWNER)
    fx.rig.unwire("people_stores")
    unwired = fx.get()
    assert [r.status_code for r in (answered, refused, unwired)] == [200, 404, 503]
    for response in (answered, refused, unwired):
        assert response.headers["cache-control"] == "no-store"


def test_FR_PA_20_the_route_is_read_only_and_makes_no_model_call_and_no_live_call(fx):
    before = {
        "people": fx.rig.snapshot(),
        "events": copy.deepcopy(fx.store.events),
        "ledger": tuple(fx.ledger),
        "worlds": dict(fx.store.worlds),
    }
    assert fx.get().status_code == 200
    for method in ("post", "put", "patch", "delete"):
        response = getattr(fx.rig.client, method)(PATH)
        assert response.status_code == 405, (method, response.status_code)
    assert fx.rig.snapshot() == before["people"]
    assert fx.store.events == before["events"] and tuple(fx.ledger) == before["ledger"]
    assert dict(fx.store.worlds) == before["worlds"] and fx.store.pending_events == {}
    assert fx.rig.events.calls == [], "no event is written"
    assert fx.rig.router_calls == [], "no model router is built (PL-01, EFF-01)"
    assert fx.rig.flag_calls == [] and os.environ.get("LIVE") is None


def test_FR_PA_20_the_same_data_in_any_order_gives_byte_identical_answers(fx):
    first = fx.get().content
    assert fx.get().content == first, "no clock, no counter"
    for world in fx.store.events:
        fx.store.events[world] = list(reversed(fx.store.events[world]))
    fx.store.worlds = dict(reversed(list(fx.store.worlds.items())))
    fx.set_ledger(list(reversed(fx.ledger)))
    assert fx.get().content == first


# --- redaction: ids the caller owns and numbers, nothing else -------------------------------------


def test_FR_PA_20_the_body_holds_only_numbers_and_the_ids_the_caller_owns(fx):
    for world in RUN_OF:
        fx.store.runs[world] = SimpleNamespace(
            plan={"units": [{"id": "U1", "unit_type": "research", "title": SENTINEL}]}
        )
    response = fx.get()
    body = response.json()
    allowed = {"mt_e1", "mt_e2", "mt_none", "mt_foreign", *OWNER_RUNS, *OWNER_RUNS.values(), METHOD_URL}
    assert set(walk_strings(body)) <= allowed, set(walk_strings(body)) - allowed
    for leak in (SENTINEL, GUEST, "u_owner", "u_priya", ORG, "Asha", "asha@"):
        assert leak not in response.text, leak
    assert "u_" not in response.text, "no user id of any kind"


def test_FR_PA_20_PL_01_no_model_id_and_no_profile_reaches_the_effort_body(fx):
    """Profiles are the cost report's grouping, not this one's: the body has no profile and, by PL-01, no model id."""
    from _mtr10_lib import FLASH, LITE, model_ids  # noqa: PLC0415

    ids = model_ids()
    assert ids, "config/models*.yaml should list model ids; the check below would be vacuous without them"
    text = fx.get().text
    for model in ids:
        assert model not in text
    assert FLASH not in text and LITE not in text


def test_FR_PA_20_D_4_no_key_of_the_body_names_a_person_or_human_time(fx):
    body = fx.body()
    keys = {key for _, key in walk_keys(body)}
    assert keys, "walked nothing"
    assert not [k for k in keys if HUMAN_TIME_KEY.search(k)], sorted(k for k in keys if HUMAN_TIME_KEY.search(k))
    assert keys <= set().union(*ALLOWED_KEYS.values())
