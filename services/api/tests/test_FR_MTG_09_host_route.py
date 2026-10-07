"""FR-MTG-09 (MTG09-b, API half): `POST /v1/meetings/{id}/host`, the statuses and the refusals (API_MTG09_b.md,
services/connectors/tests/API_FR_MTG_09.md "Ordered flow" step 1 and "Builder notes").

404 for anyone but the owner (PE-05: the same 404 as the meeting's other routes, no oracle), 409 for a meeting that is
not `scheduled`/`bot` or is already hosted, 422 with the MH rule id for a draft the connector refuses (MH-01 to MH-06),
422 for any body (the request names nothing), the SEC-15 gate, and 503 `not_configured` for every unwired seam. A
refused request starts no run, writes no event, stores no artifact, queues no entry and calls nobody.
"""

from __future__ import annotations

import pytest
from _mtg09b_lib import (
    ASHA,
    ATTACKER,
    DEV_MAIL,
    IST,
    MEETING,
    ORG,
    OWNER,
    PRIYA,
    PRIYA_MAIL,
    R_HOST,
    SAM,
    T_END,
    T_START,
    TITLE,
    WHEN_IST,
    WORLD,
    HostRig,
    attendees_of,
    block_network,
    expected_exact,
    meeting,
    person,
)
from _ppl11a_lib import DEV, MEERA, OTHER_ORG, run_threads
from _ppl11c_lib import assert_gated, assert_unwired_is_503, gone_meeting, refusals


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture()
def hr(people_rig):
    return HostRig(people_rig())


def _snapshot(hr: HostRig) -> dict:
    return hr.nothing_happened()


def test_FR_MTG_09_host_route_exists_and_the_owner_gets_the_world_back(hr):
    hr.rig.require_route(R_HOST)
    response = hr.host()
    assert response.status_code == 200, response.text[:300]
    assert response.json()["world_id"] == WORLD, "the world the meeting's host run lives in; never taken from a request"
    assert response.headers.get("cache-control") == "no-store", "PE-22: no copy outlives the request"
    hr.wait_gate()


def test_FR_MTG_09_host_route_404_for_non_owner(hr):
    hr.rig.require_route(R_HOST)
    hr.rig.real.meetings.create({**meeting(), "id": "mt_elsewhere", "org_id": OTHER_ORG})
    before = _snapshot(hr)
    seen = []
    for actor in (DEV, SAM, MEERA, PRIYA, "u_ghost"):  # a team mate, an org owner (not this meeting's), a stranger
        for meeting_id in (MEETING, "mt_elsewhere", "mt_never_made", "bad_id"):
            seen.append(hr.host(actor, meeting_id))
    owner_unknown = [hr.host(OWNER, i) for i in ("mt_elsewhere", "mt_never_made", "bad_id")]
    assert {r.status_code for r in seen + owner_unknown} == {404}
    assert len(refusals(seen + owner_unknown)) == 1, "one body whatever the cause: no oracle (PE-05)"
    assert _snapshot(hr) == before, "a stranger starts no run, writes no event, calls nobody"


def test_FR_MTG_09_host_route_404_for_a_deleted_meeting(hr):
    hr.rig.require_route(R_HOST)
    stored = hr.rig.stored("meetings", MEETING)
    hr.rig.real.meetings.replace(gone_meeting(stored, "deleted"), expected_version=1)
    before = _snapshot(hr)
    assert hr.host().status_code == 404
    assert _snapshot(hr) == before


@pytest.mark.parametrize(
    "change",
    [{"status": "live"}, {"status": "ended"}, {"status": "discarded"}, {"source": "upload"}],
    ids=lambda c: "-".join(f"{k}={v}" for k, v in c.items()),
)
def test_FR_MTG_09_host_route_409_for_a_meeting_that_is_not_scheduled_or_not_a_bot_meeting(hr, change):
    hr.rig.require_route(R_HOST)
    stored = hr.rig.stored("meetings", MEETING)
    hr.rig.real.meetings.replace({**stored, **change}, expected_version=1)
    before = _snapshot(hr)
    response = hr.host()
    assert response.status_code == 409, response.text[:300]
    assert _snapshot(hr) == before


def test_FR_MTG_09_host_route_409_for_a_meeting_already_hosted(hr):
    hr.rig.require_route(R_HOST)
    card = hr.host_and_wait_gate()
    again = hr.host()
    assert again.status_code == 409, "a host run for this meeting is already waiting at its gate"
    assert [c["id"] for c in hr.gate_cards()] == [card["id"]], "no second card"
    assert len(hr.events("approval.requested")) == 1
    assert hr.answer(card["id"], "approve").status_code == 200
    from _clint2_lib import wait_for  # noqa: PLC0415

    wait_for(lambda: hr.events("data.transfer"), what="data.transfer")
    assert hr.host().status_code == 409, "an already hosted meeting is never hosted twice"
    hr.quiet()
    assert len(hr.calendar.requests) == 1 and sum(hr.calendar.invitations.values()) == 3
    assert len(hr.events("approval.requested")) == 1 and len(hr.events("data.transfer")) == 1


def test_FR_MTG_09_host_route_two_requests_at_once_make_one_run(hr):
    hr.rig.require_route(R_HOST)
    results = run_threads(2, lambda i: hr.rig.client.post(f"/v1/meetings/{MEETING}/host", json={}).status_code)
    assert sorted(results) == [200, 409]
    hr.wait_gate()
    hr.quiet()
    assert len(hr.events("approval.requested")) == 1 and len(hr.gate_cards()) == 1
    assert hr.calendar.requests == [] and hr.entries() == []


@pytest.mark.parametrize(
    "body",
    [{"world_id": "w_someone_elses"}, {"recipients": [ATTACKER]}, {"title": "other"}, {"owner": SAM}, [], "host"],
    ids=lambda b: str(b)[:30],
)
def test_FR_MTG_09_host_route_422_for_any_body(hr, body):
    hr.rig.require_route(R_HOST)
    before = _snapshot(hr)
    response = hr.host(body=body)
    assert response.status_code == 422
    assert ATTACKER not in response.text
    assert _snapshot(hr) == before, "nothing a request says reaches the invitation (PE-09 pattern)"


def _window(end: str | None, start: str = T_START) -> dict:
    return meeting(scheduled={"start": start, "end": end})


def _persons_p(count: int) -> list[dict]:
    return [person(f"u_p{n:02d}", f"p{n:02d}@example.com") for n in range(count)]


def _many(count: int) -> dict:
    return meeting(attendees=attendees_of(*[f"u_p{n:02d}" for n in range(count)]))


def _raw_row(hr: HostRig, record: dict) -> None:
    """A record the store would refuse (it validates on write), as if it had been stored before a rule tightened."""
    rows = hr.rig.real.meetings._rows  # noqa: SLF001 - the double's raw row
    rows[(ORG, record["id"])] = (rows[(ORG, record["id"])][0], record)


def _refusal_cases() -> list:
    long_zone = "America/Argentina/ComodRivadavia"
    return [
        pytest.param("MH-02", {"meeting": _window("2030-01-15T10:01:00.000Z")}, id="MH-02-61-minutes"),
        pytest.param("MH-02", {"meeting": _window(None)}, id="MH-02-no-end"),
        pytest.param("MH-02", {"now": T_START}, id="MH-02-start-not-after-now"),
        pytest.param("MH-02", {"now": "2030-01-15T09:30:00.000Z"}, id="MH-02-already-started"),
        pytest.param(
            "MH-03", {"meeting": meeting(attendees=attendees_of(OWNER, "u_ghost"))}, id="MH-03-no-person-record"
        ),
        pytest.param(
            "MH-03",
            {
                "people": [person("u_far", "far@example.net", org=OTHER_ORG)],
                "meeting": meeting(attendees=attendees_of(OWNER, "u_far")),
            },
            id="MH-03-other-org",
        ),  # fmt: skip
        pytest.param(
            "MH-03",
            {
                "people": [person("u_twin", "PRIYA@example.com")],
                "meeting": meeting(attendees=attendees_of(OWNER, PRIYA, "u_twin")),
            },
            id="MH-03-same-address-twice",
        ),  # fmt: skip
        pytest.param("MH-03", {"people": _persons_p(50), "meeting": _many(50)}, id="MH-03-51-recipients"),
        pytest.param(
            "MH-04",
            {"people": [], "owner_zone": "Mars/Olympus"},
            id="MH-04-unknown-time-zone",
        ),
        pytest.param(
            "MH-06",
            {"meeting": meeting(title="T" * 120), "owner_zone": long_zone},
            id="MH-06-card-sentence-too-long",
        ),
        pytest.param(
            "MH-01",
            {"raw": meeting(title="Join at https://evil.example/x")},
            id="MH-01-title-pattern",
        ),
    ]


@pytest.mark.parametrize(("rule", "setup"), _refusal_cases())
def test_FR_MTG_09_host_route_422_with_the_MH_rule_id_for_a_draft_the_adapter_refuses(hr, rule, setup):
    hr.rig.require_route(R_HOST)
    hr.rig.add_people(setup.get("people", []))
    if "meeting" in setup:
        stored = hr.rig.stored("meetings", MEETING)
        hr.rig.real.meetings.replace(setup["meeting"], expected_version=1 if stored else 0)
    if "owner_zone" in setup:
        owner = hr.rig.stored("persons", OWNER)
        hr.rig.real.persons.replace({**owner, "time_zone": setup["owner_zone"]}, expected_version=1)
    if "raw" in setup:
        _raw_row(hr, setup["raw"])
    if "now" in setup:
        hr.rig.set_now(setup["now"])
    if rule == "MH-06":
        assert len(expected_exact("T" * 120, WHEN_IST, setup["owner_zone"], 3, 1)) > 500, "the case must be over 500"
    before = _snapshot(hr)
    response = hr.host()
    assert response.status_code == 422, (rule, response.status_code, response.text[:300])
    body = response.json()
    assert body["rule"] == rule and isinstance(body["detail"], str), body
    leaked = (TITLE, "T" * 20, "evil.example", ASHA, PRIYA_MAIL, DEV_MAIL, "https://", T_START, IST)
    assert not [s for s in leaked if s in response.text], (
        "the message names the rule and ids only, never a title, address or time"
    )
    assert _snapshot(hr) == before, "a refused draft starts no run and makes no artifact"


def test_FR_MTG_09_host_route_the_limits_pass_at_exactly_60_minutes_and_50_recipients(hr):
    hr.rig.require_route(R_HOST)
    hr.rig.add_people(_persons_p(49))
    hr.rig.real.meetings.replace(
        meeting(
            scheduled={"start": T_START, "end": T_END}, attendees=attendees_of(*[f"u_p{n:02d}" for n in range(49)])
        ),
        expected_version=1,
    )  # 49 attendee users and the owner: 50 recipients; 60 minutes: both at the limit
    assert hr.host().status_code == 200
    card = hr.wait_gate()
    assert len(card["gate"]["recipients"]) == 50 and card["gate"]["recipients"][0] == ASHA


@pytest.mark.parametrize("seam_name", ["artifact_store", "token_broker", "meeting_host_transport"])
def test_FR_MTG_09_host_route_an_unwired_seam_is_503_not_configured_and_starts_nothing(hr, seam_name):
    hr.rig.require_route(R_HOST)
    hr.rig.unwire(seam_name)
    before = _snapshot(hr)
    response = hr.host()
    assert response.status_code == 503, (seam_name, response.status_code, response.text[:200])
    assert response.json() == {"detail": "not_configured"}
    assert _snapshot(hr) == before and hr.store.runs == {}


def test_FR_MTG_09_host_route_is_behind_the_SEC_15_gate_and_fails_closed(people_rig):
    assert_gated(people_rig, [R_HOST])
    assert_unwired_is_503(people_rig, [R_HOST], "people_stores")
