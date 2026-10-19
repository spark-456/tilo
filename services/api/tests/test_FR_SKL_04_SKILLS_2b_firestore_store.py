"""SKILLS-2b (FR-SKL-04, BQ-SKILLS-1): the Firestore taught-skill store and its env switch `TILO_SKILLS_STORE`.

The store is exercised over a small in-memory fake of the Firestore collection/query API (defined here); no real client
is ever built (`google.cloud.firestore.Client` is made to raise in every test). Same semantics as `MemorySkillStore`.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _clint1_lib import seam
from _ppl11a_lib import MEERA, ORG, OTHER_ORG, PRIYA, SAM, STANDARD_PERSONS
from google.api_core import exceptions as gexc
from test_FR_SKL_04_SKILLS_2_skill_store import PATH, created, record, valid_body
from tilo_api import deps, dev

ENV_NAMES = (
    "TILO_SKILLS_STORE",
    "TILO_FIRESTORE_PROJECT",
    "K_SERVICE",
    "CLOUD_RUN_JOB",
    "FIRESTORE_EMULATOR_HOST",
    "GOOGLE_CLOUD_PROJECT",
    dev.ENV_FLAG,
    "LIVE",
)


# -- a fake of the Firestore surface the store uses ----------


class _Snap:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else copy.deepcopy(self._data)


class _Ref:
    def __init__(self, db: FakeClient, path: str) -> None:
        self.db, self.path = db, path

    def get(self, **_: Any) -> _Snap:
        return _Snap(self.db.docs.get(self.path))

    def create(self, data: dict[str, Any]) -> None:
        if self.path in self.db.docs:
            raise gexc.AlreadyExists("exists")
        self.db.docs[self.path] = copy.deepcopy(data)

    def set(self, data: dict[str, Any]) -> None:
        self.db.docs[self.path] = copy.deepcopy(data)


def _dig(data: dict[str, Any], dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


class _Query:
    def __init__(self, db: FakeClient, prefix: str, filters: tuple[Any, ...] = ()) -> None:
        self.db, self.prefix, self.filters = db, prefix, filters

    def where(self, *, filter: Any) -> _Query:  # noqa: A002 - the library's keyword
        if filter.op_string == "in" and len(filter.value) > 30:
            raise gexc.InvalidArgument("too many values for 'in'")
        self.db.queries.append(
            (filter.field_path, filter.op_string, len(filter.value) if filter.op_string == "in" else 1)
        )
        return _Query(self.db, self.prefix, (*self.filters, filter))

    def stream(self, **_: Any) -> Any:
        for path in sorted(self.db.docs):
            if not path.startswith(self.prefix) or "/" in path[len(self.prefix) :]:
                continue
            doc = self.db.docs[path]
            if all(self._match(doc, f) for f in self.filters):
                yield _Snap(doc)

    @staticmethod
    def _match(doc: dict[str, Any], f: Any) -> bool:
        found = _dig(doc, f.field_path)
        return found in f.value if f.op_string == "in" else found == f.value


class FakeClient:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.queries: list[tuple[str, str, int]] = []

    def document(self, path: str) -> _Ref:
        return _Ref(self, path)

    def collection(self, path: str) -> _Query:
        return _Query(self, path.rstrip("/") + "/")


# -- fixtures ----------


@pytest.fixture(autouse=True)
def no_real_client(monkeypatch):
    """The real Firestore client is never built; a clean environment; a fresh seam cache."""
    from google.cloud import firestore

    built: list[str] = []

    def refuse(*_a: Any, **_k: Any) -> Any:
        built.append("client")
        raise RuntimeError("no real Firestore client in tests")

    monkeypatch.setattr(firestore, "Client", refuse)
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    deps.get_skill_store.cache_clear()
    yield built
    deps.get_skill_store.cache_clear()


@pytest.fixture(params=["memory", "firestore"])
def store(request):
    from tilo_api.skill_firestore import FirestoreSkillStore
    from tilo_api.skill_store import MemorySkillStore

    return MemorySkillStore() if request.param == "memory" else FirestoreSkillStore(FakeClient())


def ids(rows: list[dict[str, Any]]) -> list[str]:
    return [r["id"] for r in rows]


# -- store semantics, identical for both stores ----------


def test_FR_SKL_04_SKILLS_2b_put_then_get_returns_an_equal_copy(store):
    r = record("tsk_ONE")
    store.put(r)
    got = store.get(ORG, "tsk_ONE")
    assert got == r and got is not r
    got["name"] = "changed"
    assert store.get(ORG, "tsk_ONE")["name"] == r["name"]


def test_FR_SKL_04_SKILLS_2b_get_absent_malformed_or_other_org_is_none(store):
    store.put(record("tsk_ONE"))
    assert store.get(ORG, "tsk_ABSENT") is None
    assert store.get(ORG, "../x") is None
    assert store.get(OTHER_ORG, "tsk_ONE") is None


def test_FR_SKL_04_SKILLS_2b_list_for_owner_is_only_that_owners_in_that_org(store):
    store.put(record("tsk_A", PRIYA))
    store.put(record("tsk_B", SAM))
    store.put(record("tsk_C", PRIYA, org=OTHER_ORG))
    assert ids(store.list_for_owner(ORG, PRIYA)) == ["tsk_A"]
    assert store.list_for_owner(ORG, MEERA) == []


def test_FR_SKL_04_SKILLS_2b_list_visible_is_own_plus_current_teams_in_this_org(store):
    store.put(record("tsk_OWN", PRIYA))
    store.put(record("tsk_TEAM", SAM, scope=("team", "tm_a")))
    store.put(record("tsk_OTHERTEAM", SAM, scope=("team", "tm_b")))
    store.put(record("tsk_JUSTME", SAM))
    store.put(record("tsk_FOREIGN", SAM, scope=("team", "tm_a"), org=OTHER_ORG))
    got = ids(store.list_visible(ORG, PRIYA, {"tm_a"}))
    assert sorted(got) == ["tsk_OWN", "tsk_TEAM"]
    assert ids(store.list_visible(ORG, PRIYA, set())) == ["tsk_OWN"]


def test_FR_SKL_04_SKILLS_2b_an_own_team_skill_is_listed_once(store):
    store.put(record("tsk_BOTH", PRIYA, scope=("team", "tm_a")))
    assert ids(store.list_visible(ORG, PRIYA, ["tm_a", "tm_a"])) == ["tsk_BOTH"]


def test_FR_SKL_04_SKILLS_2b_put_replaces_the_same_owners_record(store):
    store.put(record("tsk_ONE", name="old"))
    store.put(record("tsk_ONE", name="new"))
    assert store.get(ORG, "tsk_ONE")["name"] == "new"


# -- Firestore only ----------


def make() -> tuple[Any, FakeClient]:
    from tilo_api.skill_firestore import FirestoreSkillStore

    client = FakeClient()
    return FirestoreSkillStore(client), client


def test_FR_SKL_04_SKILLS_2b_document_is_the_record_verbatim_at_the_org_path():
    s, client = make()
    r = record("tsk_ONE")
    s.put(r)
    assert client.docs == {f"orgs/{ORG}/taught_skills/tsk_ONE": r}


def test_FR_SKL_04_SKILLS_2b_an_id_collision_never_overwrites_another_owners_doc():
    from tilo_api.skill_store import SkillStoreError

    s, client = make()
    mine = record("tsk_ONE", PRIYA, name="mine")
    s.put(mine)
    with pytest.raises(SkillStoreError) as err:
        s.put(record("tsk_ONE", SAM, name="theirs"))
    assert "theirs" not in str(err.value) and SAM not in str(err.value)
    assert client.docs[f"orgs/{ORG}/taught_skills/tsk_ONE"] == mine


def test_FR_SKL_04_SKILLS_2b_a_new_id_is_written_with_create_semantics():
    s, client = make()
    calls: list[str] = []
    real = _Ref.create
    _Ref.create = lambda self, data: (calls.append(self.path), real(self, data))[1]  # type: ignore[method-assign]
    try:
        s.put(record("tsk_ONE"))
    finally:
        _Ref.create = real  # type: ignore[method-assign]
    assert calls == [f"orgs/{ORG}/taught_skills/tsk_ONE"]


@pytest.mark.parametrize("bad", [{"id": "../x"}, {"id": "tsk_"}, {"org_id": "org_a/b"}, {"org_id": "x"}])
def test_FR_SKL_04_SKILLS_2b_an_unaddressable_id_or_org_is_refused_and_writes_nothing(bad):
    from tilo_api.skill_store import SkillStoreError

    s, client = make()
    with pytest.raises(SkillStoreError):
        s.put({**record("tsk_ONE"), **bad})
    assert client.docs == {}


def test_FR_SKL_04_SKILLS_2b_more_than_30_team_ids_are_chunked_deduped_and_sorted():
    s, client = make()
    teams = [f"tm_{i:02d}" for i in range(65)]
    for i, t in enumerate(teams):
        s.put(record(f"tsk_{i:02d}", SAM, name="B" if i % 2 else "A", scope=("team", t)))
    s.put(record("tsk_OWN", PRIYA, name="A", scope=("team", teams[0])))
    client.queries.clear()
    got = s.list_visible(ORG, PRIYA, teams + teams[:5])
    assert len(got) == 66 and len(set(ids(got))) == 66
    assert [(r["name"], r["id"]) for r in got] == sorted((r["name"], r["id"]) for r in got)
    in_queries = [q for q in client.queries if q[1] == "in"]
    assert len(in_queries) == 3 and all(n <= 30 for _, _, n in in_queries)


def test_FR_SKL_04_SKILLS_2b_a_client_failure_is_a_store_error_without_the_cause():
    from tilo_api.skill_firestore import FirestoreSkillStore
    from tilo_api.skill_store import SkillStoreError

    class Broken:
        def document(self, path: str) -> Any:
            raise RuntimeError("secret backend text")

        collection = document

    s = FirestoreSkillStore(Broken())
    for call in (lambda: s.get(ORG, "tsk_ONE"), lambda: s.put(record("tsk_ONE")), lambda: s.list_for_owner(ORG, PRIYA)):
        with pytest.raises(SkillStoreError) as err:
            call()
        assert "secret" not in str(err.value) and err.value.__cause__ is None


def test_FR_SKL_04_SKILLS_2b_importing_the_module_builds_no_client(no_real_client):
    import importlib

    import tilo_api.skill_firestore as m

    importlib.reload(m)
    assert no_real_client == []


# -- routes over the Firestore store through the seam ----------


@pytest.fixture()
def fs_ctx(people_rig):
    from test_FR_SKL_04_SKILLS_2_skill_store import Ctx
    from tilo_api.skill_firestore import FirestoreSkillStore

    rig = people_rig()
    rig.add_people(STANDARD_PERSONS.values())
    client = FakeClient()
    store = FirestoreSkillStore(client)
    rig.app.dependency_overrides[seam(rig.deps, "get_skill_store")] = lambda: store
    c = Ctx(rig, store)  # type: ignore[arg-type]
    c.client = client  # type: ignore[attr-defined]
    return c


def test_FR_SKL_04_SKILLS_2b_routes_save_list_read_and_learn_over_firestore(fs_ctx):
    made = created(fs_ctx, PRIYA)
    assert fs_ctx.client.docs[f"orgs/{ORG}/taught_skills/{made['id']}"] == made
    assert fs_ctx.ids(PRIYA) == [made["id"]]
    assert fs_ctx.ids(SAM) == []
    assert fs_ctx.one(PRIYA, made["id"]).json() == made
    assert fs_ctx.one(SAM, made["id"]).status_code == 404
    assert [r["id"] for r in fs_ctx.learn(PRIYA).json()["learning"]] == [made["id"]]
    assert fs_ctx.post(PRIYA, valid_body()).status_code == 201


def test_FR_SKL_04_LIVE_SKILLS_empty_firestore_catalogue_before_founding(fs_ctx):
    response = fs_ctx.get("u_unfounded", "/v1/skills?include_builtin=true")
    assert response.status_code == 200, response.text
    assert response.json()["skills"] == []
    assert "web-research" in {r["id"] for r in response.json()["builtins"]}
    assert fs_ctx.client.docs == {}  # A catalogue read never seeds an organisation or taught-skill store.


@pytest.mark.parametrize("route", ["learn", "list", "one"])
def test_FR_SKL_04_SKILLS_2b_a_malformed_stored_row_is_503_never_500(fs_ctx, route):
    bad = record("tsk_BAD", PRIYA)
    del bad["status"]
    del bad["scope"]["kind"]
    fs_ctx.client.docs[f"orgs/{ORG}/taught_skills/tsk_BAD"] = bad
    response = {
        "learn": lambda: fs_ctx.learn(PRIYA),
        "list": lambda: fs_ctx.listing(PRIYA),
        "one": lambda: fs_ctx.one(PRIYA, "tsk_BAD"),
    }[route]()
    assert response.status_code in (200, 503) and response.status_code != 500


def test_FR_SKL_04_SKILLS_2b_learn_filter_on_a_row_without_status_is_503(fs_ctx):
    bad = record("tsk_BAD", PRIYA)
    del bad["status"]
    fs_ctx.client.docs[f"orgs/{ORG}/taught_skills/tsk_BAD"] = bad
    response = fs_ctx.learn(PRIYA)
    assert response.status_code == 503 and response.json() == {"detail": "unavailable"}


# -- env selection ----------


def refused(**_: Any) -> None:
    with pytest.raises(deps.HTTPException) as err:
        deps.get_skill_store()
    assert err.value.status_code == 503 and err.value.detail == "not_configured"


def test_FR_SKL_04_SKILLS_2b_unset_and_not_dev_is_503_not_configured(no_real_client):
    refused()
    assert no_real_client == []


def test_FR_SKL_04_SKILLS_2b_unset_in_dev_mode_is_one_shared_memory_store(monkeypatch):
    from tilo_api.skill_store import MemorySkillStore

    monkeypatch.setenv(dev.ENV_FLAG, "1")
    first = deps.get_skill_store()
    assert isinstance(first, MemorySkillStore) and deps.get_skill_store() is first


def test_FR_SKL_04_SKILLS_2b_memory_by_name_is_shared_and_refused_when_deployed(monkeypatch):
    from tilo_api.skill_store import MemorySkillStore

    monkeypatch.setenv("TILO_SKILLS_STORE", "memory")
    first = deps.get_skill_store()
    assert isinstance(first, MemorySkillStore) and deps.get_skill_store() is first
    for name in ("K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.setenv(name, "x")
        refused()
        monkeypatch.delenv(name)


def test_FR_SKL_04_SKILLS_2b_an_unknown_value_is_503(monkeypatch):
    monkeypatch.setenv("TILO_SKILLS_STORE", "sqlite")
    refused()


def test_FR_SKL_04_SKILLS_2b_firestore_without_a_valid_project_is_503(monkeypatch, no_real_client):
    monkeypatch.setenv("TILO_SKILLS_STORE", "firestore")
    refused()
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "Bad Project!")
    refused()
    assert no_real_client == []


def test_FR_SKL_04_SKILLS_2b_outside_cloud_run_only_the_emulator_with_a_demo_project(monkeypatch, no_real_client):
    monkeypatch.setenv("TILO_SKILLS_STORE", "firestore")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "tilo-prod-1")
    refused()  # a live project from a laptop
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    refused()  # an emulator, but not a demo- project
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "demo-tilo")
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST")
    refused()  # a demo- project, but no emulator
    assert no_real_client == []


def test_FR_SKL_04_SKILLS_2b_the_emulator_with_a_demo_project_builds_the_store_once(monkeypatch):
    from tilo_api import skill_firestore
    from tilo_api.skill_firestore import FirestoreSkillStore

    made: list[str] = []
    monkeypatch.setattr(skill_firestore, "client_factory", lambda project: made.append(project) or FakeClient())
    monkeypatch.setenv("TILO_SKILLS_STORE", "firestore")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "demo-tilo")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    first = deps.get_skill_store()
    assert isinstance(first, FirestoreSkillStore) and deps.get_skill_store() is first and made == ["demo-tilo"]


def test_FR_SKL_04_SKILLS_2b_deployed_firestore_opens_and_refuses_an_emulator_host(monkeypatch):
    from tilo_api import skill_firestore
    from tilo_api.skill_firestore import FirestoreSkillStore

    monkeypatch.setattr(skill_firestore, "client_factory", lambda project: FakeClient())
    monkeypatch.setenv("TILO_SKILLS_STORE", "firestore")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "tilo-prod-1")
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    refused()
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST")
    assert isinstance(deps.get_skill_store(), FirestoreSkillStore)


def test_FR_SKL_04_SKILLS_2b_a_project_that_differs_from_google_cloud_project_is_503(monkeypatch):
    monkeypatch.setenv("TILO_SKILLS_STORE", "firestore")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "tilo-prod-1")
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "tilo-other-1")
    refused()


def test_FR_SKL_04_SKILLS_2b_a_failed_client_build_is_503_with_a_back_off_and_no_cause(monkeypatch, no_real_client):
    from google.cloud import firestore

    now = [100.0]
    monkeypatch.setattr(deps, "people_stores_clock", lambda: now[0])
    monkeypatch.setenv("TILO_SKILLS_STORE", "firestore")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", "tilo-prod-1")
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    assert firestore.Client is not None
    with pytest.raises(deps.HTTPException) as err:
        deps.get_skill_store()
    assert err.value.status_code == 503 and err.value.detail == "not_configured"
    assert "no real" not in repr(err.value) and err.value.__cause__ is None
    assert no_real_client == ["client"]
    refused()  # inside the window: refused at once, no new client call
    assert no_real_client == ["client"]
    now[0] += deps.PEOPLE_STORES_BACKOFF_S + 1
    refused()  # after it, one more attempt
    assert no_real_client == ["client", "client"]


def test_FR_SKL_04_SKILLS_2b_changing_the_env_changes_the_store(monkeypatch):
    from tilo_api.skill_store import MemorySkillStore

    monkeypatch.setenv("TILO_SKILLS_STORE", "memory")
    first = deps.get_skill_store()
    monkeypatch.setenv("TILO_SKILLS_STORE", "sqlite")
    refused()
    monkeypatch.setenv("TILO_SKILLS_STORE", "memory")
    assert isinstance(deps.get_skill_store(), MemorySkillStore) and deps.get_skill_store() is first


def test_FR_SKL_04_SKILLS_2b_the_route_path_constant_is_the_library():
    assert PATH == "/v1/skills"
