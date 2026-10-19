"""PROD-WIRE slice 1a, ADR-0026 decisions 1 and 8 (the door; same pattern as ADR-0023's FR-AGT-14b guard).

Pinned names: module `tilo_api.store_door` (services/api/src/tilo_api/store_door.py) exposing
`open_api_store(env=None, *, firestore_client_factory=None)` and `ApiStoreNotConfigured`. The factory is called with
the project id as its one positional argument (the schedule store's `firestore_client_factory(project)` shape).
The adapter module is `tilo_api.world_writer` (class `WorldWriterAdapter`); it is scanned here too.

Needs the uv workspace; run with `uv run pytest tests/repo`.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import re
import types
from typing import Any

import pytest

DOOR_SRC = "services/api/src/tilo_api/store_door.py"
WRITER_SRC = "services/api/src/tilo_api/world_writer.py"
LIVE = "tilo-pw1-test"  # a valid GCP project id (the schedule store's _PROJECT shape); not a real project
DEMO = "demo-pw1"
SERVICE = {"K_SERVICE": "tilo-api"}
SWITCH = {"TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": LIVE}
EMULATOR = {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8199"}
ENV_NAMES = ("FIRESTORE_EMULATOR_HOST", "TILO_API_STORE", "TILO_FIRESTORE_PROJECT", "GOOGLE_CLOUD_PROJECT", "K_SERVICE")


def _script(repo_root: pathlib.Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", repo_root / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Bomb:
    def __init__(self) -> None:
        self.built: list[Any] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.built.append((args, kwargs))
        raise AssertionError("a live Firestore client was opened")


class _Factory:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __call__(self, project: str) -> Any:
        self.calls.append(project)
        return types.SimpleNamespace(project=project)  # a stand-in client; it is never used to talk to anything


@pytest.fixture
def bomb(monkeypatch: pytest.MonkeyPatch) -> _Bomb:
    from google.cloud import firestore

    bomb = _Bomb()
    monkeypatch.setattr(firestore, "Client", bomb)
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return bomb


def test_PROD_WIRE_1a_importing_the_store_door_builds_no_client(bomb: _Bomb) -> None:
    module = importlib.import_module("tilo_api.store_door")
    importlib.reload(module)
    assert bomb.built == []


REFUSED = {
    "empty config": {},
    "memory is dev mode's, not this door's": {**SERVICE, **SWITCH, "TILO_API_STORE": "memory"},
    "another value": {**SERVICE, **SWITCH, "TILO_API_STORE": "sqlite"},
    "an empty value": {**SERVICE, **SWITCH, "TILO_API_STORE": ""},
    "no project": {**SERVICE, "TILO_API_STORE": "firestore"},
    "a bad project": {**SERVICE, "TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "Not A Project"},
    "a path-like project": {**SERVICE, "TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "tilo-x/../y"},
    "a live project outside Cloud Run": SWITCH,
    "a live project with only an emulator host": {**SWITCH, **EMULATOR},
    "a demo project without the emulator host": {**SWITCH, "TILO_FIRESTORE_PROJECT": DEMO},
    "K_SERVICE alone opens nothing": SERVICE,
}


@pytest.mark.parametrize("env", REFUSED.values(), ids=REFUSED.keys())
def test_PROD_WIRE_1a_the_door_refuses_and_builds_no_client(bomb: _Bomb, env: dict[str, str]) -> None:
    from tilo_api.store_door import ApiStoreNotConfigured, open_api_store

    factory = _Factory()
    with pytest.raises(ApiStoreNotConfigured):
        open_api_store(env, firestore_client_factory=factory)
    assert factory.calls == [] and bomb.built == []


def test_PROD_WIRE_1a_the_default_process_environment_refuses(bomb: _Bomb) -> None:
    from tilo_api.store_door import ApiStoreNotConfigured, open_api_store

    with pytest.raises(ApiStoreNotConfigured):
        open_api_store()  # the real process environment, cleared by the fixture
    assert bomb.built == []


def test_PROD_WIRE_1a_the_switch_a_valid_project_and_cloud_run_open_the_injected_client(bomb: _Bomb) -> None:
    from tilo_api.store_door import open_api_store

    factory = _Factory()
    assert open_api_store({**SERVICE, **SWITCH}, firestore_client_factory=factory) is not None
    assert factory.calls == [LIVE] and bomb.built == []


def test_PROD_WIRE_1a_outside_cloud_run_only_the_emulator_and_a_demo_project_open(bomb: _Bomb) -> None:
    from tilo_api.store_door import open_api_store

    factory = _Factory()
    env = {"TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": DEMO, **EMULATOR}
    assert open_api_store(env, firestore_client_factory=factory) is not None
    assert factory.calls == [DEMO] and bomb.built == []


@pytest.mark.parametrize("project", ["tilo-prod", "prod-demo-tilo", "Demo-tilo"])
def test_PROD_WIRE_1a_the_harness_firestore_store_guard_is_untouched(
    repo_root: pathlib.Path, bomb: _Bomb, monkeypatch: pytest.MonkeyPatch, project: str
) -> None:
    from tilo_harness.store import FirestoreStore

    with pytest.raises(Exception):  # noqa: B017 - the type is unspecified by the PRD 15.3 tests
        FirestoreStore(project_id="demo-tilo")  # no emulator host
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8199")
    with pytest.raises(Exception):  # noqa: B017
        FirestoreStore(project_id=project)
    source = (repo_root / "services/harness/src/tilo_harness/store.py").read_text(encoding="utf-8")
    assert "FIRESTORE_EMULATOR_HOST" in source and "demo" in source
    assert bomb.built == []


def test_PROD_WIRE_1a_the_new_sources_carry_no_model_id_no_secret_and_no_service_account_address(
    repo_root: pathlib.Path,
) -> None:
    lint, scan = _script(repo_root, "lint_model_ids"), _script(repo_root, "secret_scan")
    known = lint._configured_model_ids(repo_root)
    for relative in (DOOR_SRC, WRITER_SRC):
        path = repo_root / relative
        assert path.is_file(), f"{relative} is the module this slice pins"
        text = path.read_text(encoding="utf-8")
        found = set(lint.FAMILY_PATTERN.findall(text)) | {m for m in known if m in text}
        assert not found, f"{relative}: a model id outside config/ and packages/providers/ (PL-01): {sorted(found)}"
        assert scan.scan_file(str(path)) == [], f"{relative}: looks like a secret"
        assert not re.search(r"[\w.+-]+@[\w-]+\.iam\.gserviceaccount\.com", text), relative
