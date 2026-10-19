"""STARTER-1 (user-requested, BQ-STARTER-1): a default sample project, so a new account is never empty.

Served from the recorded stream the web fixture mode already plays (`contracts/fixtures/streams/village-basic.jsonl`
and `contracts/fixtures/layout/valid/village_basic.json`, shipped as package data): nothing new is recorded, no model
call. `GET /worlds` lists it (`sample: true`) for an owner with no worlds of their own or on `?include_sample=1`; its
events, layout and cards are served read-only; every write on it is 409 `sample_is_a_replay`.
Through the public interface only (`client`, `store`, `writer` from conftest.py).
"""

from __future__ import annotations

import copy
import json
import logging
import pathlib
import re

import pytest
from _api_lib import as_principal, make_principal
from _pw1b_lib import OWNER, W1, make_rig
from _pw1b_lib import world as pw_world
from tilo_api import app, deps, sample_world

SAMPLE = "w_sample_village_basic"
STREAM = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "streams" / "village-basic.jsonl"
LAYOUT = (
    pathlib.Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "layout" / "valid" / "village_basic.json"
)


def _recorded() -> list[dict]:
    return [json.loads(line) for line in STREAM.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sign_in(user: str = "u_new", role: str = "owner", world_id: str | None = None) -> None:
    as_principal(make_principal(user_id=user, role=role, world_id=world_id))


@pytest.fixture(autouse=True)
def _fresh_sample():
    sample_world.load.cache_clear()
    yield
    sample_world.load.cache_clear()


def test_STARTER_1_new_owner_sees_the_sample_in_the_list(client):
    _sign_in()
    body = client.get("/worlds").json()
    recorded = _recorded()
    assert body["next_cursor"] is None
    assert body["worlds"] == [
        {
            "world_id": SAMPLE,
            "title": f"Sample: {recorded[0]['data']['title']}",
            "status": "completed",
            "created_at": recorded[0]["ts"],
            "last_seq": recorded[-1]["seq"],
            "sample": True,
        }
    ]


def test_STARTER_1_sample_is_not_listed_once_the_owner_has_a_world(client, store):
    from test_S_14_worlds_list import seed_world

    seed_world(store, "w_mine", "u_new")
    _sign_in()
    assert [w["world_id"] for w in client.get("/worlds").json()["worlds"]] == ["w_mine"]


def test_STARTER_1_include_sample_adds_it_in_order_beside_own_worlds(client, store):
    from test_S_14_worlds_list import seed_world

    seed_world(store, "w_mine", "u_new", ts="2026-10-01T09:00:00.000Z")
    _sign_in()
    listed = client.get("/worlds", params={"include_sample": "1"}).json()["worlds"]
    assert [w["world_id"] for w in listed] == ["w_mine", SAMPLE]  # newest first, the sample is older
    assert [w.get("sample") for w in listed] == [None, True]  # a real world never carries the key
    # pagination walks both exactly once
    first = client.get("/worlds", params={"include_sample": "1", "limit": 1}).json()
    assert [w["world_id"] for w in first["worlds"]] == ["w_mine"] and first["next_cursor"]
    second = client.get("/worlds", params={"include_sample": "1", "limit": 1, "cursor": first["next_cursor"]}).json()
    assert [w["world_id"] for w in second["worlds"]] == [SAMPLE] and second["next_cursor"] is None


def test_STARTER_1_only_the_value_one_asks_for_it_and_viewers_never_get_it(client, store):
    from test_S_14_worlds_list import seed_world

    seed_world(store, "w_mine", "u_new")
    _sign_in()
    for value in ("0", "true", ""):
        assert SAMPLE not in [
            w["world_id"] for w in client.get("/worlds", params={"include_sample": value}).json()["worlds"]
        ]
    _sign_in("u_view", role="viewer", world_id="w_none")
    assert client.get("/worlds", params={"include_sample": "1"}).json()["worlds"] == []


def test_STARTER_1_sample_events_are_the_recorded_stream_for_any_signed_in_person(client):
    recorded = _recorded()
    for user, role in (("u_new", "owner"), ("u_other", "owner"), ("u_view", "viewer")):
        _sign_in(user, role)
        response = client.get(f"/worlds/{SAMPLE}/events")
        assert response.status_code == 200
        events = response.json()["events"]
        assert len(events) == len(recorded) == 44
        assert [e["seq"] for e in events] == list(range(1, 45))
        assert [e["type"] for e in events] == [e["type"] for e in recorded]
        assert {e["world_id"] for e in events} == {SAMPLE}
        assert [e["id"] for e in events] == [e["id"] for e in recorded]  # nothing re-minted
        assert [e["summary"] for e in events] == [e["summary"] for e in recorded]


def test_STARTER_1_sample_layout_is_the_recorded_layout_and_cards_are_empty(client):
    _sign_in()
    layout = client.get(f"/worlds/{SAMPLE}/layout")
    assert layout.status_code == 200
    recorded = json.loads(LAYOUT.read_text(encoding="utf-8"))
    assert layout.json() == {**recorded, "world_id": SAMPLE}
    cards = client.get(f"/worlds/{SAMPLE}/cards")
    assert cards.status_code == 200 and cards.json() == []


def test_STARTER_1_sample_reads_need_a_signed_in_person(client):
    app.dependency_overrides.pop(deps.get_current_principal, None)
    for suffix in ("events", "layout", "cards"):
        assert client.get(f"/worlds/{SAMPLE}/{suffix}").status_code == 401


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("post", "cards/c1/answer"),
        ("post", "approve"),
        ("post", "resume"),
        ("post", "pause"),
        ("post", "console/cards/c1/answer"),
        ("put", ""),
        ("patch", "events"),
        ("delete", ""),
        ("delete", "cards/c1"),
        ("post", "events"),
    ],
)
def test_STARTER_1_every_write_on_the_sample_is_409_and_touches_nothing(client, store, writer, method, suffix):
    _sign_in()
    before = (dict(store.worlds), dict(store.events), dict(store.policies), dict(store.tasks))
    path = f"/worlds/{SAMPLE}" + (f"/{suffix}" if suffix else "")
    response = client.request(method.upper(), path, json={"option": "approve"})
    assert response.status_code == 409
    assert response.json() == {"detail": "sample_is_a_replay"}
    assert writer.calls == []
    assert (dict(store.worlds), dict(store.events), dict(store.policies), dict(store.tasks)) == before


def test_STARTER_1_a_write_on_the_sample_needs_sign_in_first(client):
    app.dependency_overrides.pop(deps.get_current_principal, None)
    assert client.post(f"/worlds/{SAMPLE}/cards/c1/answer", json={}).status_code == 401


def test_STARTER_1_other_worlds_are_untouched_by_the_sample_routes(client):
    _sign_in()
    assert client.get("/worlds/w_unknown/events").status_code == 404
    assert client.get("/worlds/w_unknown/layout").status_code == 404
    assert client.get("/worlds/w_sample_village_basic_2/events").status_code == 404


def _sample_task() -> deps.TaskRecord:
    brief = {"title": "t", "sources": [], "audience": None}
    return deps.TaskRecord("u_new", SAMPLE, "r_1", brief, brief, [], 1)


_ALL_FOUR = {
    "worlds": lambda record: {"worlds": {SAMPLE: record}},
    "parts": lambda record: {"parts": {SAMPLE: [{"id": "p1"}]}},
    "policy_worlds": lambda record: {"policy_worlds": {"pol_1": SAMPLE}},
    "tasks": lambda record: {"tasks": {"t_1": _sample_task()}},
}


@pytest.mark.parametrize("field", list(_ALL_FOUR))
def test_STARTER_1_a_real_world_can_never_take_the_sample_id(field, writer):
    """Refused as a world key, a parts key, a policy_worlds value and a task's world_id, in both stores."""
    record = deps.WorldRecord(owner="u_new", districts={}, run_id="r_1")
    given = _ALL_FOUR[field](record)
    plain = deps.Store()
    with pytest.raises(ValueError, match="sample"):
        plain.commit(**given)
    with pytest.raises(ValueError, match="sample"):
        plain.save(writer, **given)
    assert SAMPLE not in plain.worlds and not plain.tasks and not plain.policy_worlds and writer.calls == []
    rig = make_rig("memory")  # the deployed store over its in-memory backend
    durable, durable_writer = rig.process()
    with pytest.raises(ValueError, match="sample"):
        durable.commit(**given)
    with pytest.raises(ValueError, match="sample"):
        durable.save(durable_writer, **given)
    assert rig.backend.docs == {} and rig.backend.queues == {}


def test_STARTER_1_save_refuses_the_sample_id_and_stores_nothing(store, writer):
    record = deps.WorldRecord(owner="u_new", districts={}, run_id="r_1")
    with pytest.raises(ValueError, match="sample"):
        store.save(writer, worlds={SAMPLE: record})
    assert SAMPLE not in store.worlds and writer.calls == []


def test_STARTER_1_a_stored_doc_with_the_sample_id_is_never_adopted(client):
    """A doc that got into the backend under the reserved id is skipped by every load, and the list shows the
    sample once (not twice, not as null)."""
    rig = make_rig("memory")
    seeding, _ = rig.process()
    seeding.commit(worlds={W1: pw_world()})
    rig.backend.docs[("worlds", SAMPLE)] = copy.deepcopy(rig.backend.docs[("worlds", W1)])
    store, _ = rig.process()
    assert store.load_world(SAMPLE) is None
    store.load_owner(OWNER)
    assert SAMPLE not in store.worlds and W1 in store.worlds
    app.dependency_overrides[deps.get_store] = lambda: store
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=None))
    listed = client.get("/worlds", params={"include_sample": "1"}).json()["worlds"]
    assert [w["world_id"] for w in listed].count(SAMPLE) == 1 and None not in listed
    assert [w["world_id"] for w in listed] == [W1, SAMPLE] or [w["world_id"] for w in listed] == [SAMPLE, W1]


def test_STARTER_1_a_plain_store_world_with_the_sample_id_is_dropped_from_the_list(client, store):
    from test_S_14_worlds_list import seed_world

    seed_world(store, SAMPLE, "u_new")  # seeded behind the guard, as a probe would
    _sign_in()
    listed = client.get("/worlds").json()["worlds"]
    assert [(w["world_id"], w.get("sample")) for w in listed] == [(SAMPLE, True)]
    assert listed[0]["title"].startswith("Sample: ")
    _sign_in("u_view", role="viewer", world_id=SAMPLE)
    assert client.get("/worlds").json()["worlds"] == []


def _leaf_routes(routes, prefix=""):
    """The app's routes with every included router opened up (this FastAPI keeps them as lazy wrappers)."""
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _leaf_routes(route.original_router.routes, prefix + route.include_context.prefix)
        elif getattr(route, "path", None) is not None:
            yield prefix + route.path, route


def test_STARTER_1_every_non_get_worlds_route_answers_409_for_the_sample_id(client, store, writer):
    """Walks the app's own routes, so a write route added later is covered without anyone remembering this file."""
    _sign_in()
    seen = 0
    for path, route in _leaf_routes(app.routes):
        methods = set(getattr(route, "methods", None) or ()) - {"GET", "HEAD", "OPTIONS"}
        if not path.startswith("/worlds/{") or not methods or SAMPLE in path:
            continue
        url = re.sub(r"\{world_id(:[^}]*)?\}", SAMPLE, path)
        url = re.sub(r"\{[^}]+\}", "x", url)
        assert url.startswith(f"/worlds/{SAMPLE}"), path
        for method in sorted(methods):
            response = client.request(method, url, json={"option": "approve"})
            assert response.status_code == 409, (method, path)
            assert response.json() == {"detail": "sample_is_a_replay"}, (method, path)
            seen += 1
    assert seen >= 5 and writer.calls == [] and SAMPLE not in store.worlds


def test_STARTER_1_served_events_are_the_recorded_ones_with_only_the_world_id_replaced(client):
    _sign_in()
    served = client.get(f"/worlds/{SAMPLE}/events").json()["events"]
    expected = [
        {**e, "world_id": SAMPLE, "target": SAMPLE if e["target"] == "w_village_basic" else e["target"]}
        for e in _recorded()
    ]
    assert served == expected
    assert "w_village_basic" not in json.dumps(served)


def test_STARTER_1_sample_delivery_is_empty_read_only_and_needs_sign_in(client):
    _sign_in()
    response = client.get(f"/worlds/{SAMPLE}/delivery")
    assert response.status_code == 200
    assert response.json() == {
        "world_id": SAMPLE,
        "artifacts": [],
        "credits_used": _recorded()[-1]["data"]["credits_used"],
        "time_saved": None,
    }
    app.dependency_overrides.pop(deps.get_current_principal, None)
    assert client.get(f"/worlds/{SAMPLE}/delivery").status_code == 401


def test_STARTER_1_fails_closed_when_the_files_are_missing(client, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(sample_world, "_data_dir", lambda: tmp_path / "nowhere")
    sample_world.load.cache_clear()
    _sign_in()
    with caplog.at_level(logging.INFO, logger="tilo_api.sample_world"):
        assert client.get("/worlds").json() == {"worlds": [], "next_cursor": None}
        assert client.get("/worlds", params={"include_sample": "1"}).json()["worlds"] == []
        assert client.get(f"/worlds/{SAMPLE}/events").status_code == 404
        assert client.get(f"/worlds/{SAMPLE}/layout").status_code == 404
        assert client.get(f"/worlds/{SAMPLE}/cards").status_code == 404
        assert client.get(f"/worlds/{SAMPLE}/delivery").status_code == 404
    lines = [r for r in caplog.records if r.name == "tilo_api.sample_world"]
    assert len(lines) == 1 and "sample project" in lines[0].getMessage()  # one line, however many requests
    assert client.post(f"/worlds/{SAMPLE}/approve").status_code == 409  # the id stays reserved


def test_STARTER_1_fails_closed_on_a_damaged_stream(client, monkeypatch, tmp_path):
    (tmp_path / "village-basic.jsonl").write_text("{not json\n", encoding="utf-8")
    (tmp_path / "village_basic.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sample_world, "_data_dir", lambda: tmp_path)
    sample_world.load.cache_clear()
    _sign_in()
    assert client.get("/worlds").json()["worlds"] == []


def test_STARTER_1_packaged_copy_is_byte_identical_to_the_contracts_original():
    data = pathlib.Path(sample_world.__file__).parent / "sample_data"
    assert (data / "village-basic.jsonl").read_bytes() == STREAM.read_bytes()
    assert (data / "village_basic.json").read_bytes() == LAYOUT.read_bytes()
