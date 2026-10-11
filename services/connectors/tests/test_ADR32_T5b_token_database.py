"""ADR32_T5b / FR-MTG-09: connectors keeps tokens in the separate Firestore database, and refuses `(default)` for them.

`TILO_TOKEN_DATABASE` is required and strictly checked (a Firestore database id, never `(default)`); `open_broker` hands
it to the client factory, and one client serves token_grants and token_revoke_retry. No code path falls
back to the default database. Fake Firestore only: no network. Secrets here are assembled at runtime.
"""

from __future__ import annotations

import importlib
import inspect
import types
from typing import Any

import pytest
from test_ADR32_T2_host_broker import FakeFirestore, FakeHttp, _env
from tilo_connectors import host_broker
from tilo_connectors.host_broker import BrokerNotConfigured, open_broker
from tilo_connectors.tokens import FakeKms

DB = "tilo-tokens"


def _open(env: dict[str, str], seen: list[tuple[Any, ...]], client: Any = None) -> Any:
    def factory(*args: Any, **kwargs: Any) -> Any:
        seen.append((*args, *kwargs.values()))
        return client or FakeFirestore()

    return open_broker(
        env,
        emit=lambda part: None,
        alert=lambda part: None,
        client_factory=factory,
        kms_factory=lambda name: FakeKms(),
        http_factory=lambda environ: FakeHttp(),
    )


def test_ADR32_T5b_FR_MTG_09_env_names_the_database() -> None:
    assert _env()["TILO_TOKEN_DATABASE"] == DB


def test_ADR32_T5b_FR_MTG_09_open_broker_passes_project_and_database_to_the_client_factory() -> None:
    seen: list[tuple[Any, ...]] = []
    _open(_env(), seen)
    assert seen == [("demo-tilo", DB)]  # one client, so all three collections share the one database


def test_ADR32_T5b_FR_MTG_09_one_client_serves_the_token_and_the_retry_collections() -> None:
    client = FakeFirestore()
    seen: list[tuple[Any, ...]] = []
    broker = _open(_env(), seen, client)
    assert len(seen) == 1
    assert isinstance(broker._store._users, type(client.collection("x")))
    assert broker._store._users is not broker._retry._users
    assert (broker._store._root, broker._retry._root) == (host_broker.TOKEN_COLLECTION, host_broker.RETRY_COLLECTION)


def test_ADR32_T5b_FR_MTG_09_a_missing_database_is_refused() -> None:
    env = _env()
    del env["TILO_TOKEN_DATABASE"]
    seen: list[tuple[Any, ...]] = []
    with pytest.raises(BrokerNotConfigured) as caught:
        _open(env, seen)
    assert "TILO_TOKEN_DATABASE" in str(caught.value)
    assert seen == [], "no client is built, so nothing can fall back to (default)"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "(default)",
        "(DEFAULT)",
        "default",
        "(default) ",
        " tilo-tokens",
        "tilo-tokens\n",
        "Tilo-Tokens",
        "tilo_tokens",
        "abc",
        "-tilo-tokens",
        "tilo-tokens-",
        "1tilo-tokens",
        "a" * 64,
        "tilo-tokens/x",
        "projects/p/databases/tilo-tokens",
        "tilo‑tokens",
        "tilo-tokens١",
    ],
)
def test_ADR32_T5b_FR_MTG_09_malformed_database_ids_are_refused(bad: str) -> None:
    seen: list[tuple[Any, ...]] = []
    with pytest.raises(BrokerNotConfigured) as caught:
        _open({**_env(), "TILO_TOKEN_DATABASE": bad}, seen)
    assert seen == []
    assert "TILO_TOKEN_DATABASE" in str(caught.value)
    assert str(caught.value).startswith("set TILO_TOKEN_DATABASE to the token database id")  # one fixed text
    assert len(str(caught.value)) < 100, "the value is never echoed"
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("good", ["tilo-tokens", "tokens-dev-1", "a" * 63, "abcd"])
def test_ADR32_T5b_FR_MTG_09_valid_non_default_ids_build(good: str) -> None:
    seen: list[tuple[Any, ...]] = []
    _open({**_env(), "TILO_TOKEN_DATABASE": good}, seen)
    assert seen == [("demo-tilo", good)]


def test_ADR32_T5b_FR_MTG_09_the_default_client_is_built_for_the_named_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    module = types.ModuleType("google.cloud.firestore")
    module.Client = lambda **kw: calls.append(kw) or FakeFirestore()  # type: ignore[attr-defined]
    real_import = importlib.import_module
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name, *a: module if name == "google.cloud.firestore" else real_import(name, *a),
    )
    host_broker._default_client("demo-tilo", DB)
    assert calls == [{"project": "demo-tilo", "database": DB}]


def test_ADR32_T5b_FR_MTG_09_no_code_path_builds_a_client_without_a_database() -> None:
    source = inspect.getsource(host_broker)
    assert "firestore.Client(project=project)" not in source
    assert "database=database" in source


def test_ADR32_T5b_FR_MTG_09_the_process_environment_is_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TILO_TOKEN_DATABASE", DB)
    env = _env()
    del env["TILO_TOKEN_DATABASE"]
    with pytest.raises(BrokerNotConfigured):  # an explicit env mapping is the whole truth
        _open(env, [])
