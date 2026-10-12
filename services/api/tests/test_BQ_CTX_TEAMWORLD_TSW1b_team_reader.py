"""BQ-CTX-TEAMWORLD, slice TSW-1b (ADR-0040 decisions 4 to 6; FR-TEAM-03 to FR-TEAM-06; PE-31 to PE-34): a member of
a team a world is shared with reads it as a team reader (a derived Viewer of every district, read routes only),
creates work items bound to it, and lists the team view of its items. Security-flagged: a new read path to other
people's data. Every refusal is the one unknown-world 404, byte-equal to an unknown world's.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _api_lib import base_event
from _tsw1_lib import (
    ASHA,
    BEN,
    CARA,
    DEV,
    LATER,
    LAUNCH,
    LAYOUT,
    ORG,
    ORGOWNER,
    OTHER_WORLD,
    WORLD,
    Rig,
    share_id,
    web,
    work_item,
)
from fastapi import HTTPException
from tilo_api import deps

TEAM_VIEW = {"id", "title", "status", "due", "owner", "world_id"}


def _stream(world: str = WORLD) -> list[dict]:
    kw = {"world_id": world, "actor": ASHA}
    return [
        base_event(seq=1, type_="world.requested", data={"title": "T"}, vis="all", summary="for all", **kw),
        base_event(seq=2, type_="unit.started", data={"unit": "u1"}, vis=["D1"], district="D1", summary="d1", **kw),
        base_event(
            seq=3, type_="world.share_changed", data={"team": LAUNCH, "state": "on"}, vis=[], summary="mine", **kw
        ),
        base_event(seq=4, type_="unit.started", data={"unit": "u2"}, vis=["D2"], district="D2", summary="d2", **kw),
        base_event(seq=5, type_="world.completed", data={"credits_used": 3}, vis="all", summary="done", **kw),
    ]


@pytest.fixture()
def rig() -> Rig:
    r = Rig()
    r.store.events[WORLD] = _stream()
    r.store.events[OTHER_WORLD] = _stream(OTHER_WORLD)
    r.store.runs[WORLD] = SimpleNamespace(layout=LAYOUT, titles={}, cards=None)
    r.grant()  # Asha shared the world with tm_launch
    return r


def _read_all(rig: Rig, world: str = WORLD, **kw):
    return {
        "events": rig.client.get(f"/worlds/{world}/events", **kw),
        "layout": rig.client.get(f"/worlds/{world}/layout", **kw),
        "world": rig.client.get(f"/worlds/{world}", **kw),
        "delivery": rig.client.get(f"/worlds/{world}/delivery", **kw),
        "items": rig.client.get(f"/worlds/{world}/work-items", **kw),
    }


def _unknown(rig: Rig):
    return _read_all(rig, "w_no_such_world")


def test_BQ_CTX_TEAMWORLD_FR_TEAM_03_a_teammate_reads_events_layout_world_and_delivery(rig):
    rig.as_(web(BEN))
    got = _read_all(rig)
    assert {k: v.status_code for k, v in got.items()} == dict.fromkeys(got, 200)
    summaries = [e["summary"] for e in got["events"].json()["events"]]
    assert summaries == ["for all", "d1", "d2", "done"], "every district, never a vis [] line"
    assert [d["id"] for d in got["world"].json()["districts"]] == ["D1", "D2"]
    assert got["world"].json()["has_hidden_districts"] is False
    layout = got["layout"].json()
    assert [d["id"] for d in layout["semantic"]["levels"][0]["districts"]] == ["D1", "D2"] and layout[
        "geometry"
    ] is None
    assert got["delivery"].json()["credits_used"] == 3


def test_BQ_CTX_TEAMWORLD_FR_TEAM_03_the_owner_still_reads_everything_unchanged(rig):
    rig.as_(web(ASHA))
    events = rig.client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert [e["summary"] for e in events] == ["for all", "d1", "mine", "d2", "done"]
    assert "trace" in events[0] and events[0]["world_id"] == WORLD  # the owner's full record


def test_BQ_CTX_TEAMWORLD_PE_32_the_viewer_view_is_the_scoped_one_and_the_principals_districts_widen_nothing(rig):
    rig.as_(web(BEN, districts=("D1",)))  # a session that claims fewer or other districts changes nothing
    got = rig.client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert [e["summary"] for e in got] == ["for all", "d1", "d2", "done"]
    assert all(e["id"].startswith("v") and "run_id" not in e for e in got), "the scoped view, not the owner's record"


@pytest.mark.parametrize(
    "principal",
    [
        pytest.param(web(CARA), id="a person of another team"),
        pytest.param(web(DEV), id="a person of another org"),
        pytest.param(web("u_nobody"), id="no person record"),
        pytest.param(deps.Principal(BEN, "owner", world_id=OTHER_WORLD, channel="web", full_session=True), id="bound"),
        pytest.param(deps.Principal(BEN, "owner", world_id=None, channel="email", full_session=True), id="email"),
        pytest.param(deps.Principal(BEN, "owner", world_id=None, channel="web", full_session=False), id="no marker"),
        pytest.param(web(BEN, demo_session=True), id="demo"),
        pytest.param(deps.Principal(BEN, "team_lead", world_id=None, channel="web", full_session=True), id="role"),
    ],
)
def test_BQ_CTX_TEAMWORLD_PE_32_everyone_else_gets_the_unknown_world_404_byte_for_byte(rig, principal):
    unknown = _unknown(rig)
    assert {k: v.status_code for k, v in unknown.items()} == dict.fromkeys(unknown, 404)
    rig.as_(principal)
    got = _read_all(rig)
    for name, response in got.items():
        assert response.status_code == 404, name
        assert response.content == unknown[name].content, name


def test_BQ_CTX_TEAMWORLD_PE_32_no_header_query_or_body_names_the_team(rig):
    rig.as_(web(CARA))
    unknown = _unknown(rig)
    got = _read_all(rig, params={"team": LAUNCH, "team_id": LAUNCH}, headers={"X-Tilo-Team": LAUNCH})
    assert {k: (v.status_code, v.content) for k, v in got.items()} == {k: (404, v.content) for k, v in unknown.items()}


def test_BQ_CTX_TEAMWORLD_PE_31_a_share_of_one_world_opens_no_other_world_of_the_owner(rig):
    rig.as_(web(BEN))
    got = _read_all(rig, OTHER_WORLD)
    assert {k: v.status_code for k, v in got.items()} == dict.fromkeys(got, 404)


def _lose(rig: Rig, uid: str) -> None:
    held = rig.people.persons.get(ORG, uid)
    rig.people.persons.replace({**held.record, "memberships": []}, expected_version=held.version)


def test_BQ_CTX_TEAMWORLD_PE_31_a_revoke_is_effective_on_the_next_request_no_cache(rig):
    rig.as_(web(BEN))
    assert rig.client.get(f"/worlds/{WORLD}/events").status_code == 200
    rig.as_(web(ASHA))
    assert rig.client.delete(f"/worlds/{WORLD}/team-shares/{LAUNCH}").status_code == 200
    rig.as_(web(BEN))
    for path in ("events", "layout", "delivery", "work-items"):
        assert rig.client.get(f"/worlds/{WORLD}/{path}").status_code == 404, path


def test_BQ_CTX_TEAMWORLD_PE_31_removing_the_reader_from_the_team_is_effective_on_the_next_request(rig):
    rig.as_(web(BEN))
    assert rig.client.get(f"/worlds/{WORLD}").status_code == 200
    _lose(rig, BEN)
    assert rig.client.get(f"/worlds/{WORLD}").status_code == 404


def test_BQ_CTX_TEAMWORLD_PE_31_the_owner_leaving_the_team_lapses_the_share_and_it_does_not_revive(rig):
    rig.as_(web(BEN))
    ashas = rig.people.persons.get(ORG, ASHA)
    _lose(rig, ASHA)
    assert rig.client.get(f"/worlds/{WORLD}").status_code == 404
    rejoined = {"team": LAUNCH, "assigned_by": {"by": ORGOWNER, "at": "2026-10-09T09:00:00.000Z"}}
    held = rig.people.persons.get(ORG, ASHA)
    rig.people.persons.replace({**ashas.record, "memberships": [rejoined]}, expected_version=held.version)
    assert rig.client.get(f"/worlds/{WORLD}").status_code == 404, "membership assigned after the grant: share again"


def test_BQ_CTX_TEAMWORLD_PE_31_a_world_that_changed_owner_shares_nothing_until_the_new_owner_shares(rig):
    rig.store.worlds[WORLD].owner = CARA
    rig.as_(web(BEN))
    assert rig.client.get(f"/worlds/{WORLD}").status_code == 404


def test_BQ_CTX_TEAMWORLD_PE_32_every_other_route_of_the_world_keeps_the_unknown_world_404(rig):
    rig.as_(web(BEN))
    reads = ("cards", "console", "costs", "skill-proposals", "apps/a_1")
    writes = ("pause", "autopilot/stop", "cards/c1/answer", "cards/c1/share", "skill-proposals")
    for path in reads:
        unknown = rig.client.get(f"/worlds/w_no_such_world/{path}")
        got = rig.client.get(f"/worlds/{WORLD}/{path}")
        assert (got.status_code, got.content) == (unknown.status_code, unknown.content), path
    for path in writes:
        unknown = rig.client.post(f"/worlds/w_no_such_world/{path}", json={})
        got = rig.client.post(f"/worlds/{WORLD}/{path}", json={})
        assert (got.status_code, got.content) == (unknown.status_code, unknown.content), path
    assert rig.store.worlds[WORLD].paused is False


def test_BQ_CTX_TEAMWORLD_PE_32_a_team_reader_cannot_share_or_revoke(rig):
    rig.as_(web(BEN))
    assert rig.client.put(f"/worlds/{WORLD}/team-shares/{LAUNCH}").status_code == 404
    assert rig.client.delete(f"/worlds/{WORLD}/team-shares/{LAUNCH}").status_code == 404
    assert rig.shares()[0]["revoked"] is None


# --- work items: `world_id` set only at creation, the team view as a list read model --------------------------------
def _add(rig: Rig, *records: dict) -> None:
    for r in records:
        rig.people.work_items.create(r)


def _create(rig: Rig, **body):
    payload = {"title": "Draft the launch note", "source": {"kind": "manual", "ref": None}, **body}
    return rig.client.post("/v1/work-items", json=payload)


def test_BQ_CTX_TEAMWORLD_FR_TEAM_04_the_owner_and_a_team_reader_create_items_bound_to_the_world(rig):
    for who in (ASHA, BEN):
        rig.as_(web(who))
        got = _create(rig, world_id=WORLD)
        assert got.status_code == 201, got.text
        assert got.json()["world_id"] == WORLD and got.json()["owner"] == who


def test_BQ_CTX_TEAMWORLD_FR_TEAM_04_an_item_without_a_world_stays_personal(rig):
    rig.as_(web(BEN))
    got = _create(rig)
    assert got.status_code == 201 and "world_id" not in got.json()


def test_BQ_CTX_TEAMWORLD_FR_TEAM_04_nobody_binds_an_item_to_a_world_they_cannot_read(rig):
    rig.as_(web(CARA))
    unknown = _create(rig, world_id="w_no_such_world")
    for world in (WORLD, OTHER_WORLD):
        got = _create(rig, world_id=world)
        assert got.status_code == 403 and got.content == unknown.content
    rig.as_(web(BEN))
    assert _create(rig, world_id=OTHER_WORLD).status_code == 403  # shared world is WORLD only
    assert rig.people.work_items.list(ORG) == ()


def test_BQ_CTX_TEAMWORLD_FR_TEAM_04_a_lapsed_share_binds_nothing_and_a_malformed_world_is_422(rig):
    rig.as_(web(BEN))
    assert _create(rig, world_id="not a world").status_code == 422
    held = rig.people.world_shares.get(ORG, share_id(WORLD, LAUNCH))
    rig.people.world_shares.replace(
        {**held.record, "revoked": {"by": ASHA, "at": LATER}}, expected_version=held.version
    )
    rig.now = "2026-10-12T09:00:00.000Z"
    assert _create(rig, world_id=WORLD).status_code == 403


def test_BQ_CTX_TEAMWORLD_FR_TEAM_04_a_request_cannot_bind_an_item_of_someone_else_or_a_tilo_made_one(rig):
    rig.as_(web(BEN))
    got = rig.client.post(
        "/v1/work-items",
        json={"title": "x", "source": {"kind": "manual", "ref": None}, "world_id": WORLD, "owner": ASHA},
    )
    assert got.status_code == 422  # a closed body: the owner is the caller, always


def test_BQ_CTX_TEAMWORLD_FR_TEAM_05_a_teammate_lists_the_team_view_of_the_items_of_the_world(rig):
    _add(
        rig,
        work_item("wi_a_open", ASHA),
        work_item("wi_b_done", BEN, status="done"),
        work_item("wi_a_personal", ASHA, world=None),
        work_item("wi_a_other_world", ASHA, world=OTHER_WORLD),
        work_item("wi_a_flagged", ASHA, flagged=True),
        work_item("wi_a_dropped", ASHA, status="dropped"),
        work_item("wi_c_not_in_team", CARA),
    )
    for who in (BEN, ASHA):
        rig.as_(web(who))
        body = rig.client.get(f"/worlds/{WORLD}/work-items").json()
        assert [i["id"] for i in body["items"]] == ["wi_a_open", "wi_b_done"], who
        assert all(set(i) == TEAM_VIEW and i["world_id"] == WORLD for i in body["items"])
        assert "source" not in str(body) and "history" not in str(body)


def test_BQ_CTX_TEAMWORLD_FR_TEAM_05_an_item_whose_owner_left_the_team_is_not_listed(rig):
    _add(rig, work_item("wi_a_open", ASHA), work_item("wi_b_open", BEN))
    _lose(rig, BEN)
    rig.as_(web(ASHA))
    assert [i["id"] for i in rig.client.get(f"/worlds/{WORLD}/work-items").json()["items"]] == ["wi_a_open"]


def test_BQ_CTX_TEAMWORLD_FR_TEAM_06_existing_items_stay_personal_even_after_the_world_is_shared(rig):
    _add(rig, work_item("wi_old", ASHA, world=None))  # made before the share, no world_id: the migration
    rig.as_(web(BEN))
    assert rig.client.get(f"/worlds/{WORLD}/work-items").json()["items"] == []
    assert rig.client.get("/v1/work-items/wi_old").status_code == 404  # and still no way to read it in full


def test_BQ_CTX_TEAMWORLD_FR_TEAM_06_a_teammate_can_read_the_row_and_change_nothing(rig):
    _add(rig, work_item("wi_a_open", ASHA))
    rig.as_(web(BEN))
    for path in ("", "/edit", "/done", "/snooze", "/reopen", "/not-mine", "/put-back"):
        method = rig.client.get if path == "" else rig.client.post
        kw = {} if path == "" else {"json": {"title": "x"}}
        assert method(f"/v1/work-items/wi_a_open{path}", **kw).status_code in (404, 422), path
    stored = rig.people.work_items.get(ORG, "wi_a_open")
    assert stored.version == 1 and stored.record["status"] == "open"


def test_BQ_CTX_TEAMWORLD_FR_TEAM_06_the_plate_and_the_people_list_never_carry_a_teammates_item(rig):
    _add(rig, work_item("wi_a_open", ASHA))
    rig.as_(web(BEN))
    assert rig.client.get("/v1/work-items").json()["items"] == []
    plate = rig.client.get("/v1/plate")
    assert "wi_a_open" not in plate.text


def test_BQ_CTX_TEAMWORLD_PE_32_an_unwired_people_store_never_opens_a_world_to_a_non_owner_but_the_owner_reads(rig):
    rig.people_error = HTTPException(status_code=503, detail="not_configured")
    rig.as_(web(BEN))
    assert rig.client.get(f"/worlds/{WORLD}/events").status_code == 404  # logged, no detail: like an unknown world
    rig.as_(web(ASHA))
    assert rig.client.get(f"/worlds/{WORLD}/events").status_code == 200
