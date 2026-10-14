"""FR-SET-01 and FR-SET-02 (ADR-0039, rules USET-01..08): `GET` and `PUT /v1/me/settings` and the settings store.

The oracle is the contract: `contracts/user_settings.schema.json`, its fixtures (valid, invalid, crossref) and the
reference check in `tests/contracts/test_FR_SET_01_02_user_settings_contract.py`. No network, no model, no cloud: a
fake clock, in-memory people stores and the Firestore fake."""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import pytest
from _ppl11c_fs_fake import FakeFirestore
from fastapi import HTTPException
from fastapi.testclient import TestClient
from tilo_api import app, deps, user_settings
from tilo_api.cards import CardStore
from tilo_api.user_settings import MemorySettingsStore, StoredPreferences, settings_store_of
from tilo_api.user_settings_firestore import FirestoreSettingsStore, SettingsStoreError
from tilo_people.stores import PeopleStores
from tilo_policy.schemas import conforms

FIXTURES = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "fixtures"
ALEX, SAM = "u_alex", "u_sam"
NOW = "2026-10-12T09:30:00.000Z"
PATH = "/v1/me/settings"
SCHEMA = "user_settings.schema.json"


def _json(*parts: str) -> Any:
    return json.loads(FIXTURES.joinpath(*parts).read_text(encoding="utf-8"))


def _cases(kind: str) -> list[pathlib.Path]:
    return sorted((FIXTURES / "user_settings" / "crossref" / kind).glob("*.json"))


FIRST = _json("user_settings.update", "valid", "first_save.json")


class Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV", "TILO_JUDGE_LIVE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(deps, "ORG_ID", "org_tilo")
        self.stores = PeopleStores.in_memory()
        self.user, self.demo, self.signed_in = ALEX, False, True

        def principal() -> deps.Principal:
            if not self.signed_in:
                raise HTTPException(status_code=401, detail="not signed in")
            return deps.Principal(user_id=self.user, role="owner", demo_session=self.demo, full_session=not self.demo)

        ov = app.dependency_overrides
        ov[deps.get_current_principal] = principal
        ov[deps.get_people_stores] = lambda: self.stores
        ov[deps.get_clock] = lambda: lambda: NOW
        self.client = TestClient(app, raise_server_exceptions=False)

    @property
    def store(self) -> MemorySettingsStore:
        return settings_store_of(self.stores)  # type: ignore[return-value]

    def put(self, body: Any = None, **kw: Any) -> Any:
        return self.client.put(PATH, json=copy.deepcopy(FIRST if body is None else body), **kw)

    def as_user(self, user: str) -> None:
        self.user = user


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    return Rig(monkeypatch)


def test_FR_SET_01_nothing_saved_reads_the_unsaved_defaults_never_a_stored_record(rig: Rig) -> None:
    got = rig.client.get(PATH)
    assert got.status_code == 200 and got.headers["cache-control"] == "no-store"
    doc = got.json()
    assert (doc["owner_id"], doc["org_id"], doc["version"], doc["updated_at"]) == (ALEX, "org_tilo", 0, None)
    assert conforms(SCHEMA, doc)
    assert rig.store.read("org_tilo", ALEX) is None, "a read stores nothing"


def test_FR_SET_01_a_valid_save_stores_version_plus_one_with_owner_org_and_time_from_the_server(rig: Rig) -> None:
    saved = rig.put()
    assert saved.status_code == 200
    doc = saved.json()
    assert (doc["owner_id"], doc["org_id"], doc["version"], doc["updated_at"]) == (ALEX, "org_tilo", 1, NOW)
    assert conforms(SCHEMA, doc) and doc["profile"] == FIRST["profile"]
    assert rig.client.get(PATH).json() == doc
    second = {**FIRST, "version": 1, "profile": {**FIRST["profile"], "title": "Chief of staff"}}
    again = rig.put(second)
    assert again.status_code == 200 and again.json()["version"] == 2
    assert rig.client.get(PATH).json()["profile"]["title"] == "Chief of staff"


def test_FR_SET_01_a_save_survives_a_new_client_session_through_the_same_store(rig: Rig) -> None:
    assert rig.put().status_code == 200
    fresh = TestClient(app, raise_server_exceptions=False)  # another device: nothing but the store in common
    assert fresh.get(PATH).json()["profile"] == FIRST["profile"]


def test_FR_SET_01_two_people_read_and_write_only_their_own_settings(rig: Rig) -> None:
    assert rig.put().status_code == 200
    rig.as_user(SAM)
    theirs = rig.client.get(PATH).json()
    assert (theirs["owner_id"], theirs["version"]) == (SAM, 0), "another person's saved document is never read"
    other = {**FIRST, "profile": {**FIRST["profile"], "name": "Sam Rivera"}}
    assert rig.put(other).json()["owner_id"] == SAM
    rig.as_user(ALEX)
    assert rig.client.get(PATH).json()["profile"]["name"] == FIRST["profile"]["name"]
    assert rig.store.read("org_tilo", SAM)["profile"]["name"] == "Sam Rivera"


def test_FR_SET_01_the_same_person_id_in_another_org_reads_nothing_of_the_first(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert rig.put().status_code == 200
    monkeypatch.setattr(deps, "ORG_ID", "org_other")
    got = rig.client.get(PATH).json()
    assert (got["org_id"], got["version"]) == ("org_other", 0)


def test_FR_SET_01_no_verified_principal_is_401_and_touches_nothing(rig: Rig) -> None:
    rig.signed_in = False
    assert rig.client.get(PATH).status_code == 401
    assert rig.put().status_code == 401
    rig.signed_in = True
    assert rig.store.read("org_tilo", ALEX) is None


@pytest.mark.parametrize(
    "path", sorted((FIXTURES / "user_settings.update" / "invalid").glob("*.json")), ids=lambda p: p.stem
)
def test_FR_SET_01_a_write_the_contract_refuses_is_422_and_changes_nothing(rig: Rig, path: pathlib.Path) -> None:
    assert rig.put().status_code == 200
    before = rig.store.read("org_tilo", ALEX)
    refused = rig.put(json.loads(path.read_text(encoding="utf-8")))
    assert refused.status_code == 422 and refused.json()["code"] == "invalid_settings"
    assert rig.store.read("org_tilo", ALEX) == before
    assert "alex@example.com" not in refused.text and "u_" not in refused.text, "no value is echoed"


@pytest.mark.parametrize("path", _cases("valid"), ids=lambda p: p.stem)
def test_FR_SET_01_valid_crossref_cases_are_accepted(rig: Rig, path: pathlib.Path) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    _seed(rig, case["stored_version"])
    assert rig.put(case["update"]).status_code == 200


@pytest.mark.parametrize("path", _cases("invalid"), ids=lambda p: p.stem)
def test_FR_SET_01_invalid_crossref_cases_reach_the_stated_verdict_and_write_nothing(
    rig: Rig, path: pathlib.Path
) -> None:
    case = json.loads(path.read_text(encoding="utf-8"))
    _seed(rig, case["stored_version"])
    before = rig.store.read("org_tilo", ALEX)
    got = rig.put(case["update"])
    assert got.status_code == (409 if case["rule"] == "USET-02" else 422), path.name
    assert rig.store.read("org_tilo", ALEX) == before
    if case["rule"] == "USET-03":
        assert got.json()["fields"] and got.json()["code"] == "invalid_settings"


def _seed(rig: Rig, version: int) -> None:
    if version:
        doc = {**user_settings.defaults(ALEX), "version": version, "updated_at": NOW}
        assert rig.store.write("org_tilo", ALEX, expected_version=0, document=doc)


def test_FR_SET_01_a_stale_write_is_409_with_the_current_version_and_the_document_is_kept(rig: Rig) -> None:
    assert rig.put().status_code == 200
    assert rig.put({**FIRST, "version": 1}).status_code == 200
    stale = rig.put({**FIRST, "version": 1, "profile": {**FIRST["profile"], "name": "Late Device"}})
    assert (stale.status_code, stale.json()["code"], stale.json()["version"]) == (409, "version_conflict", 2)
    assert rig.client.get(PATH).json()["profile"]["name"] != "Late Device"


def test_FR_SET_01_a_rival_write_between_read_and_write_is_409(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MemorySettingsStore, "write", lambda *a, **k: False)
    assert rig.put().status_code == 409


def test_FR_SET_02_the_decisions_row_keeps_a_channel_other_rows_may_be_all_off(rig: Rig) -> None:
    off = {"phone": False, "email": False, "slack": False}
    bad = {**FIRST, "notifications": {**FIRST["notifications"], "decisions": off}}
    refused = rig.put(bad)
    assert refused.status_code == 422 and refused.json()["fields"] == ["notifications.decisions"]
    ok = {**FIRST, "notifications": {**FIRST["notifications"], "spend": off, "digest": off, "weekly": off}}
    assert rig.put(ok).status_code == 200


@pytest.mark.parametrize(
    "threshold",
    ["£1,000", "1000", 1000, {"amount_minor": 1000}, {"amount_minor": 10.5, "currency": "INR"}, True],
)
def test_FR_SET_02_an_ambiguous_threshold_is_refused_never_parsed(rig: Rig, threshold: Any) -> None:
    body = copy.deepcopy(FIRST)
    body["quiet_hours"]["threshold"] = threshold
    assert rig.put(body).status_code == 422
    assert rig.store.read("org_tilo", ALEX) is None


def test_FR_SET_02_a_currency_the_api_has_no_minor_unit_for_is_refused_and_a_known_one_is_kept(rig: Rig) -> None:
    body = copy.deepcopy(FIRST)
    body["quiet_hours"]["threshold"] = {"amount_minor": 5000, "currency": "ZZZ"}
    assert rig.put(body).json()["fields"] == ["quiet_hours.threshold"]
    body["quiet_hours"]["threshold"] = {"amount_minor": 5000, "currency": "INR"}
    assert rig.put(body).json()["quiet_hours"]["threshold"] == {"amount_minor": 5000, "currency": "INR"}


@pytest.mark.parametrize("name", ["Alex​Morgan", "‮Alex", "   ", "Alex Morgan"])
def test_FR_SET_01_invisible_or_blank_profile_text_is_refused_not_corrected(rig: Rig, name: str) -> None:
    body = copy.deepcopy(FIRST)
    body["profile"]["name"] = name
    got = rig.put(body)
    assert got.status_code == 422 and rig.store.read("org_tilo", ALEX) is None


def test_FR_SET_01_the_body_is_capped_before_it_is_parsed_and_only_json_is_read(rig: Rig) -> None:
    junk = b"{" + b"x" * (user_settings.MAX_BODY_BYTES + 10)
    over = rig.client.put(PATH, content=junk, headers={"content-type": "application/json"})
    assert over.status_code == 413, "413, not the 422 a parse would give"
    assert rig.client.put(PATH, content=b"hi", headers={"content-type": "text/plain"}).status_code == 415
    nan = rig.client.put(PATH, content=b'{"version": NaN}', headers={"content-type": "application/json"})
    assert nan.status_code == 422
    listy = rig.client.put(PATH, content=b"[1]", headers={"content-type": "application/json"})
    assert listy.status_code == 422


def test_FR_SET_01_no_query_or_path_selects_another_person(rig: Rig) -> None:
    assert rig.put().status_code == 200
    rig.as_user(SAM)
    for query in ("?owner_id=u_alex", "?user=u_alex&org_id=org_tilo"):
        assert rig.client.get(PATH + query).json()["owner_id"] == SAM
    assert rig.client.get("/v1/me/settings/u_alex").status_code in (404, 405)


def test_FR_SET_01_a_demo_session_stores_nothing_reads_defaults_and_cannot_write(rig: Rig) -> None:
    rig.demo = True
    got = rig.client.get(PATH).json()
    assert (got["version"], got["updated_at"]) == (0, None)
    refused = rig.put()
    assert (refused.status_code, refused.json()["code"]) == (403, "full_session_required")
    rig.demo = False
    assert rig.store.read("org_tilo", ALEX) is None


def test_FR_SET_01_a_store_that_fails_is_a_fixed_503_with_no_text(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("secret-looking-detail alex@example.com")

    monkeypatch.setattr(MemorySettingsStore, "read", boom)
    for got in (rig.client.get(PATH), rig.put()):
        assert got.status_code == 503 and "secret-looking" not in got.text and "alex@" not in got.text


def test_FR_SET_01_deployed_the_memory_store_is_never_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    with pytest.raises(HTTPException) as refused:
        settings_store_of(PeopleStores.in_memory())
    assert (refused.value.status_code, refused.value.detail) == (503, "not_configured")


def test_FR_SET_01_saving_a_profile_email_changes_no_directory_record(rig: Rig) -> None:
    before = rig.stores.persons.list("org_tilo")
    assert rig.put().status_code == 200
    assert rig.stores.persons.list("org_tilo") == before == ()


def test_FR_SET_01_the_firestore_store_round_trips_and_is_compare_and_set() -> None:
    client = FakeFirestore()
    store = FirestoreSettingsStore(client)
    doc = {**user_settings.defaults(ALEX), "version": 1, "updated_at": NOW}
    assert store.read("org_tilo", ALEX) is None
    assert store.write("org_tilo", ALEX, expected_version=0, document=doc)
    assert not store.write("org_tilo", ALEX, expected_version=0, document=doc), "a stale version writes nothing"
    assert store.read("org_tilo", ALEX) == doc
    assert client.raw(f"orgs/org_tilo/user_settings/{ALEX}") == doc
    assert store.read("org_tilo", SAM) is None
    store.erase("org_tilo", ALEX)
    assert store.read("org_tilo", ALEX) is None


def test_FR_SET_01_the_firestore_store_refuses_a_document_that_is_not_the_persons() -> None:
    client = FakeFirestore()
    store = FirestoreSettingsStore(client)
    sam_doc = {**user_settings.defaults(SAM), "version": 1, "updated_at": NOW}
    with pytest.raises(SettingsStoreError):
        store.write("org_tilo", ALEX, expected_version=0, document=sam_doc)
    client.put(f"orgs/org_tilo/user_settings/{ALEX}", sam_doc)  # a planted or misfiled document
    with pytest.raises(SettingsStoreError):
        store.read("org_tilo", ALEX)
    with pytest.raises(SettingsStoreError):
        store.read("org_tilo", "u_../x")


def test_FR_SET_02_a_stored_quiet_window_never_hides_a_gate_with_or_without_a_threshold(rig: Rig) -> None:
    quiet = {"enabled": True, "start": "22:00", "end": "07:00", "timezone": "UTC"}
    for threshold in (None, {"amount_minor": 100000, "currency": "INR"}):
        body = copy.deepcopy(FIRST)
        body["quiet_hours"] = {**quiet, "threshold": threshold}
        body["version"] = rig.client.get(PATH).json()["version"]
        assert rig.put(body).status_code == 200
        prefs = StoredPreferences(rig.store).get(ALEX)
        assert prefs is not None and "threshold" not in prefs["quiet_hours"]
        assert set(prefs["quiet_hours"]) == set(quiet)
        cards = CardStore(clock=_Clock(), writer=_NoWriter(), preferences=StoredPreferences(rig.store))
        night = "2026-10-12T23:00:00.000Z"
        assert cards.should_notify({"kind": "gate", "world_id": "w1"}, user_id=ALEX, now=night)
        assert cards.should_notify({"rung": "blocked", "world_id": "w1"}, user_id=ALEX, now=night)
        assert not cards.should_notify({"rung": "needs_you", "world_id": "w1"}, user_id=ALEX, now=night)


def test_FR_SET_02_a_person_with_nothing_saved_behaves_as_before_and_a_failing_store_hides_nothing() -> None:
    assert StoredPreferences(MemorySettingsStore()).get(ALEX) is None

    class Broken(MemorySettingsStore):
        def read(self, org_id: str, user_id: str) -> Any:
            raise RuntimeError("down")

    assert StoredPreferences(Broken()).get(ALEX) is None


class _Clock:
    def now(self) -> str:
        return NOW


class _NoWriter:
    def write(self, *a: Any, **k: Any) -> None:
        raise AssertionError("a settings read writes no event")
