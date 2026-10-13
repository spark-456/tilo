"""BQ-CTX-TEAMWORLD, slice TSW-4b (ADR-0040 decisions 4 and 5; S-14 `GET /worlds`; BQ-TEAMWORLD-8): the worlds list also
carries the worlds the caller reads as a team reader, each item marked `access: "team"`. Security-flagged: a new read
path to other people's data. The marker is only on a team item; the person's own items keep exactly their five keys.

Through the public interface only: the real `tilo_api.app` over the in-memory stores (`_tsw1_lib.Rig`).
"""

from __future__ import annotations

import json
import logging

import pytest
from _api_lib import base_event, make_district, make_world
from _tsw1_lib import ASHA, BEN, CARA, DEV, LAUNCH, OPS, ORG, ORGOWNER, OTHER_WORLD, WORLD, Rig, web
from tilo_api import deps

OWN_KEYS = {"world_id", "title", "status", "created_at", "last_seq"}
TEAM_KEYS = OWN_KEYS | {"access"}
OPS_WORLD = "w_ops_only"
T = [f"2026-10-0{n}T09:00:00.000Z" for n in range(1, 9)]


def _stream(world: str, owner: str, *, title: str, ts: str, hidden_first: bool = False) -> list[dict]:
    kw = {"world_id": world, "actor": owner, "ts": ts}
    vis: list | str = [] if hidden_first else "all"
    return [
        base_event(seq=1, type_="world.requested", data={"title": title}, vis=vis, summary="req", **kw),
        base_event(seq=2, type_="world.started", data={}, vis="all", summary="started", **kw),
        base_event(seq=3, type_="unit.started", data={"unit": "u1"}, vis=["D1"], district="D1", summary="d1", **kw),
        base_event(seq=4, type_="world.share_changed", data={"team": LAUNCH, "state": "on"}, vis=[], summary="m", **kw),
        base_event(seq=5, type_="world.completed", data={"credits_used": 9}, vis="all", summary="done", **kw),
    ]


def _add(rig: Rig, world: str, owner: str, *, title: str, ts: str, **kw) -> None:
    rig.store.worlds[world] = make_world(owner=owner, districts={"D1": make_district("One", "s")})
    rig.store.events[world] = _stream(world, owner, title=title, ts=ts, **kw)


@pytest.fixture()
def rig(monkeypatch) -> Rig:
    monkeypatch.setattr("tilo_api.worlds_list._load_sample", lambda: None)  # STARTER-1 has its own tests
    r = Rig()
    _add(r, WORLD, ASHA, title="Launch plan", ts=T[1])
    r.grant()  # Asha shared WORLD with tm_launch
    return r


def _list(rig: Rig, **params):
    return rig.client.get("/worlds", params={"limit": 100, **params})


def _ids(response) -> list[str]:
    return [w["world_id"] for w in response.json()["worlds"]]


def test_BQ_CTX_TEAMWORLD_S_14_a_team_item_carries_only_what_a_team_reader_already_sees(rig):
    rig.as_(web(BEN))
    response = _list(rig)
    assert response.status_code == 200
    assert response.json()["next_cursor"] is None
    (item,) = response.json()["worlds"]
    assert item == {
        "world_id": WORLD,
        "title": "Launch plan",
        "status": "completed",
        "created_at": T[1],
        "last_seq": 4,  # the reader's own renumbered view: the vis [] line is not counted (BQ-S14-4)
        "access": "team",
    }
    text = json.dumps(response.json())
    for secret in (ASHA, "asha@example.com", "credits", "r_launch_1", "D2", "cards", "needs_you"):
        assert secret not in text


def test_BQ_CTX_TEAMWORLD_S_14_a_hidden_world_requested_gives_the_reader_no_title_and_no_date(rig):
    rig.store.events[WORLD] = _stream(WORLD, ASHA, title="Private title", ts=T[1], hidden_first=True)
    rig.as_(web(BEN))
    (item,) = _list(rig).json()["worlds"]
    assert item["title"] is None and item["created_at"] is None and item["access"] == "team"
    assert "Private title" not in json.dumps(item)


def test_BQ_CTX_TEAMWORLD_S_14_the_owner_keeps_exactly_the_five_keys_and_is_listed_once(rig):
    _add(rig, "w_asha_two", ASHA, title="Second", ts=T[2])
    rig.as_(web(ASHA))  # Asha is a member of tm_launch herself, the world is shared with her own team
    items = _list(rig).json()["worlds"]
    assert sorted(i["world_id"] for i in items) == sorted([WORLD, "w_asha_two", OTHER_WORLD])
    assert all(set(i) == OWN_KEYS for i in items), "no access marker on the person's own worlds"


def test_BQ_CTX_TEAMWORLD_S_14_a_revoked_share_disappears_on_the_next_request(rig):
    rig.as_(web(BEN))
    assert _ids(_list(rig)) == [WORLD]
    held = rig.people.world_shares.get(ORG, rig.shares()[0]["id"])
    revoked = {**held.record, "revoked": {"by": ASHA, "at": T[3]}}
    rig.people.world_shares.replace(revoked, expected_version=held.version)
    assert _list(rig).json() == {"worlds": [], "next_cursor": None}


def test_BQ_CTX_TEAMWORLD_S_14_a_lapsed_share_disappears_when_the_owner_leaves_and_does_not_revive(rig):
    rig.as_(web(BEN))
    assert _ids(_list(rig)) == [WORLD]
    owner = rig.people.persons.get(ORG, ASHA)  # the world's owner leaves the team: the share lapses (PE-31)
    left = rig.people.persons.replace({**owner.record, "memberships": []}, expected_version=owner.version)
    assert _ids(_list(rig)) == []
    rejoined = [{"team": LAUNCH, "assigned_by": {"by": ORGOWNER, "at": "2026-10-05T09:00:00.000Z"}}]
    rig.people.persons.replace({**owner.record, "memberships": rejoined}, expected_version=left.version)
    assert _ids(_list(rig)) == []  # rejoined after the grant: she has to share again


def test_BQ_CTX_TEAMWORLD_S_14_a_reader_who_leaves_the_team_stops_seeing_it(rig):
    rig.as_(web(BEN))
    assert _ids(_list(rig)) == [WORLD]
    reader = rig.people.persons.get(ORG, BEN)
    rig.people.persons.replace({**reader.record, "memberships": []}, expected_version=reader.version)
    assert _ids(_list(rig)) == []


def test_BQ_CTX_TEAMWORLD_S_14_another_persons_world_never_appears_without_a_share_in_force(rig):
    _add(rig, OPS_WORLD, ORGOWNER, title="Ops", ts=T[2])
    rig.grant(world=OPS_WORLD, team=OPS, by=ORGOWNER)  # shared with tm_ops: Ben is not in it
    _add(rig, "w_unshared", ASHA, title="Unshared", ts=T[3])  # no share at all
    _add(rig, "w_wrong_granter", ASHA, title="Granted by another", ts=T[4])
    rig.grant(world="w_wrong_granter", by=CARA)  # not the record owner: not in force (PE-31)
    rig.as_(web(BEN))
    assert _ids(_list(rig)) == [WORLD]
    rig.as_(web(CARA))  # Cara is in tm_ops only
    assert _ids(_list(rig)) == [OPS_WORLD]
    rig.as_(web(DEV))  # another org
    assert _ids(_list(rig)) == []
    rig.as_(web("u_nobody"))  # no person record
    assert _ids(_list(rig)) == []


def test_BQ_CTX_TEAMWORLD_S_14_no_request_input_names_a_team(rig):
    rig.as_(web(CARA))
    response = rig.client.get(
        "/worlds", params={"team": LAUNCH, "team_id": LAUNCH, "access": "team"}, headers={"X-Tilo-Team": LAUNCH}
    )
    assert response.status_code == 200 and response.json()["worlds"] == []


@pytest.mark.parametrize(
    "principal",
    [
        pytest.param(deps.Principal(BEN, "owner", world_id=WORLD, channel="web", full_session=True), id="bound"),
        pytest.param(deps.Principal(BEN, "owner", world_id=None, channel="email", full_session=True), id="email"),
        pytest.param(deps.Principal(BEN, "owner", world_id=None, channel="web", full_session=False), id="no marker"),
        pytest.param(web(BEN, demo_session=True), id="demo"),
        pytest.param(deps.Principal(BEN, "team_lead", world_id=None, channel="web", full_session=True), id="role"),
        pytest.param(deps.Principal(BEN, "viewer", world_id=None, channel="web", full_session=True), id="viewer"),
    ],
)
def test_BQ_CTX_TEAMWORLD_S_14_only_a_full_unbound_sign_in_session_reads_team_worlds(rig, principal):
    rig.as_(principal)
    response = _list(rig)
    assert response.status_code == 200
    assert not [w for w in response.json()["worlds"] if w.get("access") == "team"]


def test_BQ_CTX_TEAMWORLD_S_14_a_people_store_that_cannot_open_is_the_own_list_only_and_logs_no_detail(rig, caplog):
    _add(rig, "w_ben_own", BEN, title="Mine", ts=T[2])
    rig.as_(web(BEN))
    assert sorted(_ids(_list(rig))) == sorted([WORLD, "w_ben_own"])
    rig.people_error = RuntimeError("firestore down: secret-detail-123")
    with caplog.at_level(logging.DEBUG):
        response = _list(rig)
    assert response.status_code == 200
    assert _ids(response) == ["w_ben_own"]
    assert "secret-detail-123" not in caplog.text and "secret-detail-123" not in response.text


def test_BQ_CTX_TEAMWORLD_S_14_a_store_that_fails_on_one_shared_world_leaves_the_rest_not_a_500(rig):
    _add(rig, "w_two", ASHA, title="Two", ts=T[3])
    rig.grant(world="w_two")
    rig.as_(web(BEN))
    assert sorted(_ids(_list(rig))) == sorted([WORLD, "w_two"])
    real = rig.store.load_world

    def flaky(world_id: str, settle: bool = False):
        if world_id == "w_two":
            raise OSError("backend down")
        return real(world_id, settle=settle)

    rig.store.load_world = flaky  # type: ignore[method-assign]
    response = _list(rig)
    assert response.status_code == 200 and _ids(response) == [WORLD]


def test_BQ_CTX_TEAMWORLD_S_14_pages_walk_own_and_team_worlds_once_newest_first_and_a_revoke_leaves_no_gap(rig):
    _add(rig, "w_own_new", BEN, title="Own new", ts=T[6])
    _add(rig, "w_own_old", BEN, title="Own old", ts=T[0])
    for n, ts in ((1, T[2]), (2, T[4]), (3, T[5])):
        _add(rig, f"w_team{n}", ASHA, title=f"Team {n}", ts=ts)
        rig.grant(world=f"w_team{n}")
    rig.as_(web(BEN))
    expected = ["w_own_new", "w_team3", "w_team2", "w_team1", WORLD, "w_own_old"]  # by created_at, newest first
    assert _ids(_list(rig)) == expected
    seen: list[str] = []
    cursor = None
    while True:
        page = _list(rig, limit=2, **({"cursor": cursor} if cursor else {})).json()
        assert len(page["worlds"]) <= 2
        seen += [w["world_id"] for w in page["worlds"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == expected

    first = _list(rig, limit=2).json()  # a share is revoked between two pages: no duplicate, no other gap
    held = rig.people.world_shares.get(ORG, rig.shares()[-1]["id"])
    gone = held.record["world_id"]
    rig.people.world_shares.replace({**held.record, "revoked": {"by": ASHA, "at": T[7]}}, expected_version=held.version)
    rest = _list(rig, limit=100, cursor=first["next_cursor"]).json()["worlds"]
    assert [w["world_id"] for w in rest] == [w for w in expected[2:] if w != gone]


def test_BQ_CTX_TEAMWORLD_S_14_a_cursor_is_never_another_persons_and_never_widens_the_scope(rig):
    _add(rig, "w_own_new", BEN, title="Own new", ts=T[6])
    rig.as_(web(BEN))
    cursor = _list(rig, limit=1).json()["next_cursor"]
    assert cursor
    rig.as_(web(CARA))
    assert _list(rig, cursor=cursor).status_code in (400, 422)


def test_BQ_CTX_TEAMWORLD_S_14_the_sample_is_never_marked_team_and_nothing_is_listed_twice(rig, monkeypatch):
    monkeypatch.undo()  # the recorded sample is back
    rig.as_(web(BEN))
    items = _list(rig, include_sample="1").json()["worlds"]
    ids = [i["world_id"] for i in items]
    assert len(ids) == len(set(ids))
    assert all(i.get("access") != "team" for i in items if i.get("sample"))


def test_BQ_CTX_TEAMWORLD_S_14_the_list_writes_nothing(rig):
    rig.as_(web(BEN))
    before = (len(rig.shares()), {w: len(e) for w, e in rig.store.events.items()}, dict(rig.store.worlds))
    _list(rig)
    after = (len(rig.shares()), {w: len(e) for w, e in rig.store.events.items()}, dict(rig.store.worlds))
    assert before == after
    assert rig.store.pending_events == {}
