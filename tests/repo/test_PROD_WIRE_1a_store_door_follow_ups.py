"""PROD-WIRE slice 1a follow-ups (security review) on `tilo_api.store_door.open_api_store`: a deployed process never
talks to an emulator host, an explicit `env` must agree with `os.environ` on it (the client library reads os.environ),
and `TILO_FIRESTORE_PROJECT` is pinned to `GOOGLE_CLOUD_PROJECT` when that is present."""

from __future__ import annotations

import types
from typing import Any

import pytest

LIVE = "tilo-pw1-test"
SERVICE = {"K_SERVICE": "tilo-api"}
SWITCH = {"TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": LIVE}
EMULATOR = {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8199"}
DEMO = {"TILO_API_STORE": "firestore", "TILO_FIRESTORE_PROJECT": "demo-pw1", **EMULATOR}
ENV_NAMES = ("FIRESTORE_EMULATOR_HOST", "TILO_API_STORE", "TILO_FIRESTORE_PROJECT", "GOOGLE_CLOUD_PROJECT", "K_SERVICE")


class _Factory:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, project: str) -> Any:
        self.calls.append(project)
        return types.SimpleNamespace(project=project)


@pytest.fixture
def clean(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    from google.cloud import firestore

    def bomb(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a live Firestore client was opened")

    monkeypatch.setattr(firestore, "Client", bomb)
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_PROD_WIRE_1a_follow_up_a_deployed_process_refuses_an_emulator_host_in_env_or_os_environ(
    clean: pytest.MonkeyPatch,
) -> None:
    from tilo_api.store_door import ApiStoreNotConfigured, open_api_store

    factory = _Factory()
    with pytest.raises(ApiStoreNotConfigured):
        open_api_store({**SERVICE, **SWITCH, **EMULATOR}, firestore_client_factory=factory)
    clean.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8199")
    with pytest.raises(ApiStoreNotConfigured):
        open_api_store({**SERVICE, **SWITCH}, firestore_client_factory=factory)
    assert factory.calls == []


def test_PROD_WIRE_1a_follow_up_an_explicit_env_must_agree_with_os_environ_on_the_emulator_host(
    clean: pytest.MonkeyPatch,
) -> None:
    from tilo_api.store_door import ApiStoreNotConfigured, open_api_store

    with pytest.raises(ApiStoreNotConfigured):  # env names an emulator, the library would read none
        open_api_store(DEMO)
    clean.setenv("FIRESTORE_EMULATOR_HOST", "10.0.0.9:8199")
    with pytest.raises(ApiStoreNotConfigured):  # os.environ names another one
        open_api_store(DEMO)
    with pytest.raises(ApiStoreNotConfigured):  # os.environ names one that env does not
        open_api_store({**SERVICE, **SWITCH})
    factory = _Factory()  # an injected factory builds the client itself, so there is nothing to disagree about
    assert open_api_store(DEMO, firestore_client_factory=factory) is not None
    clean.setenv("FIRESTORE_EMULATOR_HOST", EMULATOR["FIRESTORE_EMULATOR_HOST"])
    clean.setattr("google.cloud.firestore.Client", lambda **kw: types.SimpleNamespace(**kw))
    assert open_api_store(DEMO).project == "demo-pw1"  # the same host on both sides opens


def test_PROD_WIRE_1a_follow_up_the_project_is_pinned_to_google_cloud_project_when_present(
    clean: pytest.MonkeyPatch,
) -> None:
    from tilo_api.store_door import ApiStoreNotConfigured, open_api_store

    factory = _Factory()
    with pytest.raises(ApiStoreNotConfigured):
        open_api_store({**SERVICE, **SWITCH, "GOOGLE_CLOUD_PROJECT": "tilo-other-1"}, firestore_client_factory=factory)
    with pytest.raises(ApiStoreNotConfigured):
        open_api_store({**SERVICE, **SWITCH, "GOOGLE_CLOUD_PROJECT": ""}, firestore_client_factory=factory)
    assert factory.calls == []
    assert open_api_store({**SERVICE, **SWITCH, "GOOGLE_CLOUD_PROJECT": LIVE}, firestore_client_factory=factory)
    assert factory.calls == [LIVE]
