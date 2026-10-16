"""M1: memory is private, bounded, ephemeral in demo, and erased with its owner."""

import pytest
from fastapi import HTTPException
from tilo_api.memory_store import FirestoreMemoryStore, InMemoryMemoryStore, MemoryErasureStore, MemoryFull


def test_MI_01_MI_02_routes_hide_foreign_ids_and_preserve_source(monkeypatch):
    from fastapi.testclient import TestClient
    from tilo_api import app, deps, memory_routes

    monkeypatch.delenv("K_SERVICE", raising=False)
    store = InMemoryMemoryStore()
    user = ["u_alex"]
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(user[0], "owner")
    app.dependency_overrides[memory_routes.get_memory_store] = lambda: store
    app.dependency_overrides[deps.get_clock] = lambda: lambda: STAMP
    app.dependency_overrides[memory_routes.get_memory_safety] = lambda: type(
        "Safety", (), {"check": lambda self, text: {"flagged": False}}
    )()
    app.dependency_overrides[memory_routes.get_memory_events] = lambda: type(
        "Events", (), {"record": lambda self, actor: None}
    )()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        made = client.post("/v1/memory", json={"text": "I prefer mornings", "kind": "preference", "source": "user"})
        assert made.status_code == 201, made.text
        item = made.json()
        user[0] = "u_bob"
        assert (
            client.patch(f"/v1/memory/{item['id']}", json={"source": "tilo_suggested"}).content
            == client.patch("/v1/memory/mem_unknown", json={"source": "tilo_suggested"}).content
        )
        user[0] = "u_alex"
        assert client.patch(f"/v1/memory/{item['id']}", json={"source": "tilo_suggested"}).status_code == 422
        assert client.get("/v1/memory").json()["items"][0]["source"] == "user"
        assert client.delete(f"/v1/memory/{item['id']}").status_code == 204
        app.dependency_overrides[memory_routes.get_memory_safety] = lambda: type(
            "Down", (), {"check": lambda self, text: (_ for _ in ()).throw(RuntimeError("unavailable"))}
        )()
        assert client.post("/v1/memory", json={"text": "Private", "kind": "fact", "source": "user"}).status_code == 503
        assert store.list("org_tilo", "u_alex") == []
    finally:
        app.dependency_overrides.clear()


STAMP = "2026-10-16T03:00:00.000Z"


def test_MI_01_foreign_and_unknown_ids_are_indistinguishable():
    store = InMemoryMemoryStore()
    item, _ = store.create("org_tilo", "u_alex", "I prefer mornings", "preference", "user", STAMP)
    assert store.get("org_tilo", "u_bob", item["id"]) is None
    assert store.get("org_tilo", "u_bob", "mem_unknown") is None
    assert store.list("org_tilo", "u_bob") == []


def test_MI_02_duplicate_and_cap_are_atomic():
    store = InMemoryMemoryStore()
    first, created = store.create("org_tilo", "u_alex", " I prefer mornings ", "preference", "user", STAMP)
    again, created_again = store.create("org_tilo", "u_alex", "i PREFER mornings", "fact", "user", STAMP)
    assert created and not created_again and first == again
    for n in range(1, 100):
        store.create("org_tilo", "u_alex", f"Fact {n}", "fact", "user", STAMP)
    try:
        store.create("org_tilo", "u_alex", "One too many", "fact", "user", STAMP)
    except MemoryFull:
        pass
    else:
        raise AssertionError("101st note was accepted")
    assert len(store.list("org_tilo", "u_alex")) == 100


def test_MI_02_firestore_serializes_owner_creates_on_a_metadata_document():
    from _ppl11c_fs_fake import FakeFirestore

    client = FakeFirestore()
    store = FirestoreMemoryStore(client)
    item, created = store.create("org_tilo", "u_alex", "I prefer mornings", "preference", "user", STAMP)
    assert created and store.get("org_tilo", "u_alex", item["id"]) == item
    metadata = client.raw("orgs/org_tilo/users/u_alex/memory_meta/state")
    assert metadata == {"count": 1, "rev": 1}
    duplicate, created_again = store.create("org_tilo", "u_alex", "i PREFER mornings", "fact", "user", STAMP)
    assert not created_again and duplicate == item
    assert client.raw("orgs/org_tilo/users/u_alex/memory_meta/state") == metadata


def test_MI_02_patch_preserves_source_and_delete_is_hard():
    store = InMemoryMemoryStore()
    item, _ = store.create("org_tilo", "u_alex", "I prefer mornings", "preference", "user", STAMP)
    changed = store.update("org_tilo", "u_alex", item["id"], {"kind": "fact"}, "2026-10-16T04:00:00.000Z")
    assert changed["source"] == "user" and changed["created_at"] == STAMP
    assert store.delete("org_tilo", "u_alex", item["id"])
    assert store.get("org_tilo", "u_alex", item["id"]) is None


def test_MI_09_erasure_removes_only_owners_notes():
    store = InMemoryMemoryStore()
    store.create("org_tilo", "u_alex", "A", "fact", "user", STAMP)
    store.create("org_tilo", "u_bob", "B", "fact", "user", STAMP)
    assert store.erase("u_alex") == 1
    assert store.count_owner("u_alex") == 0
    assert len(store.list("org_tilo", "u_bob")) == 1


def test_MI_03_secret_flagged_and_safety_down_leave_nothing_stored():
    from tilo_api.memory_routes import _safe_text

    class Safety:
        def __init__(self, flagged=False, down=False):
            self.flagged, self.down = flagged, down

        def check(self, text):
            if self.down:
                raise RuntimeError("provider down")
            return {"flagged": self.flagged}

    for text, safety, redactor, status in [
        ("a\u200bb", Safety(), lambda s: s, 422),
        ("a\U000e0100b", Safety(), lambda s: s, 422),
        ("secret value", Safety(), lambda s: "[redacted]", 422),
        ("unsafe", Safety(flagged=True), lambda s: s, 422),
        ("safe", Safety(down=True), lambda s: s, 503),
    ]:
        with pytest.raises(HTTPException) as refused:
            _safe_text(text, safety, redactor)
        assert refused.value.status_code == status


def test_MI_06_saved_event_has_no_note_text_and_is_owner_only():
    from tilo_api.memory_routes import MemoryEvents

    class Writer:
        def append(self, world, part):
            self.world, self.part = world, part

    class Desks:
        def desk_world(self, org, owner):
            return "w_desk_alex"

        def desk_owner(self, world):
            return "u_alex"

    writer = Writer()
    MemoryEvents(writer, Desks()).record("u_alex")
    assert writer.world == "w_desk_alex"
    assert writer.part["type"] == "memory.saved"
    assert writer.part["data"] == {"layer": "preferences", "item_count": 1}
    assert writer.part["vis"] == [] and writer.part["authz"] is None
    assert "I prefer" not in str(writer.part)
    with pytest.raises(ValueError):
        MemoryEvents(writer, Desks()).record("u_bob")


def test_MI_09_erasure_registry_adapter_rereads_memory_items():
    from tilo_memory.erasure import REQUIRED_STORES

    assert "memory_items" in REQUIRED_STORES
    store = InMemoryMemoryStore()
    store.create("org_tilo", "u_alex", "A", "fact", "user", STAMP)
    store.create("org_tilo", "u_bob", "B", "fact", "user", STAMP)
    adapter = MemoryErasureStore(store)
    own = next(r for r in adapter.records() if r.user_id == "u_alex")
    adapter.delete(own.record_id)
    assert [r.user_id for r in adapter.records()] == ["u_bob"]


def test_MI_01_demo_uses_session_memory_even_when_deployed(monkeypatch):
    from tilo_api import deps, memory_routes

    class Demo:
        def __init__(self):
            self.made = {}

        def _once(self, name, make):
            return self.made.setdefault(name, make())

    demo = Demo()
    monkeypatch.setenv("K_SERVICE", "service")
    monkeypatch.setattr(memory_routes.ephemeral, "for_request", lambda request: demo)
    monkeypatch.setattr(deps, "get_people_stores", lambda request: pytest.fail("durable store opened"))
    first = memory_routes.get_memory_store(object())
    assert first is memory_routes.get_memory_store(object())
    assert isinstance(first, InMemoryMemoryStore)
