"""MTG-WIRE-1: the two production seams behind the bot-hosted meeting (FR-MTG-09, ADR-0024).

`deps.get_token_broker` and `deps.get_meeting_host_transport` stay 503 `not_configured` unless the environment asks
for them in full. Every credential here is assembled at runtime (CLAUDE.md), nothing is live, nothing is paid.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from tilo_api import deps, host_wiring
from tilo_connectors.tokens import FakeKms, TokenBroker

LIVE_KEY = "LI" + "VE"  # the live switch is the user's: never written as an assignment
ACCESS = "ya29." + "a1" * 8
REFRESH = "1//" + "r2" * 8
SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
KMS_KEY = "projects/demo-tilo/locations/asia-southeast1/keyRings/tilo/cryptoKeys/tokens"


def _env(**drop: bool) -> dict[str, str]:
    env = {
        "TILO_TOKEN_STORE": "firestore",
        "TILO_FIRESTORE_PROJECT": "demo-tilo",
        "TILO_KMS_KEY": KMS_KEY,
        "GOOGLE_OAUTH_CLIENT_ID": "client-id-" + "x" * 6,
        "GOOGLE_OAUTH_CLIENT_SECRET": "client-sec-" + "y" * 6,
        LIVE_KEY: "1",
    }
    return {k: v for k, v in env.items() if k not in drop}


class _Snap:
    def __init__(self, data: dict | None) -> None:
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict | None:
        return self._data


class _Doc:
    def __init__(self, docs: dict, key: str) -> None:
        self._docs, self._key = docs, key

    def set(self, data: dict) -> None:
        self._docs[self._key] = dict(data)

    def get(self) -> _Snap:
        return _Snap(self._docs.get(self._key))

    def delete(self) -> None:
        self._docs.pop(self._key, None)


class _Query:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def stream(self) -> list[_Snap]:
        return [_Snap(r) for r in self._rows]


class _Collection:
    def __init__(self, docs: dict) -> None:
        self._docs = docs

    def document(self, key: str) -> _Doc:
        return _Doc(self._docs, key)

    def where(self, *, filter: Any) -> _Query:  # noqa: A002 - the library's own keyword
        return _Query([d for d in self._docs.values() if d.get(filter.field_path) == filter.value])


class FakeFirestore:
    def __init__(self) -> None:
        self.collections: dict[str, dict] = {}

    def collection(self, name: str) -> _Collection:
        return _Collection(self.collections.setdefault(name, {}))


class _Http:
    def post(self, url: str, *, data: Any) -> Any:
        raise AssertionError("no network in a wiring test")


def _build(env: dict[str, str] | None = None, client: FakeFirestore | None = None, emit: Any = None) -> TokenBroker:
    client = client or FakeFirestore()
    return host_wiring.open_host_broker(
        _env() if env is None else env,
        client_factory=lambda project: client,
        kms_factory=lambda name: FakeKms(),
        http_factory=lambda environ: _Http(),
        emit=emit or (lambda part: None),
    )


@pytest.fixture(autouse=True)
def _cold() -> Any:
    deps.get_token_broker.cache_clear()
    deps.get_meeting_host_transport.cache_clear()
    yield
    deps.get_token_broker.cache_clear()
    deps.get_meeting_host_transport.cache_clear()


def test_MTG_WIRE_1_seams_refuse_without_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TILO_TOKEN_STORE", "TILO_KMS_KEY", "GOOGLE_OAUTH_CLIENT_ID", LIVE_KEY):
        monkeypatch.delenv(name, raising=False)
    for seam in (deps.get_token_broker, deps.get_meeting_host_transport):
        with pytest.raises(HTTPException) as caught:
            seam()
        assert (caught.value.status_code, caught.value.detail) == (503, "not_configured")


@pytest.mark.parametrize(
    "missing",
    [
        "TILO_TOKEN_STORE",
        "TILO_FIRESTORE_PROJECT",
        "TILO_KMS_KEY",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        LIVE_KEY,
    ],
)
def test_MTG_WIRE_1_every_setting_is_required(missing: str) -> None:
    with pytest.raises(host_wiring.HostNotConfigured):
        _build(_env(**{missing: True}))


@pytest.mark.parametrize(
    "bad",
    [
        {"TILO_TOKEN_STORE": "memory"},
        {"TILO_FIRESTORE_PROJECT": "Not A Project"},
        {"TILO_KMS_KEY": "not-a-key-name"},
        {LIVE_KEY: "0"},
    ],
)
def test_MTG_WIRE_1_bad_values_are_refused(bad: dict[str, str]) -> None:
    with pytest.raises(host_wiring.HostNotConfigured):
        _build({**_env(), **bad})


def test_MTG_WIRE_1_builds_a_broker_over_firestore_and_seals_the_tokens() -> None:
    client = FakeFirestore()
    broker = _build(client=client)
    broker.store_tokens(
        "u_owner",
        "meeting_host",
        {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600, "scope": SCOPE},
    )
    stored = client.collections["token_grants"]
    assert len(stored) == 1
    assert ACCESS not in repr(stored) and REFRESH not in repr(stored)  # sealed before it reaches Firestore
    assert broker.access_token_for_adapter("u_owner", "meeting_host", required_scopes=[SCOPE]) == ACCESS


def test_MTG_WIRE_1_bot_grant_is_its_own_record() -> None:
    client = FakeFirestore()
    broker = _build(client=client)
    body = {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600, "scope": SCOPE}
    broker.store_tokens("u_owner", "meeting_host", body)
    broker.store_tokens(
        "u_owner", "google_calendar", {**body, "scope": "https://www.googleapis.com/auth/calendar.readonly"}
    )
    store = host_wiring.FirestoreTokenStore(client)
    assert store.connectors_of("u_owner") == ["google_calendar", "meeting_host"]
    store.delete("u_owner", "meeting_host")  # revoking the bot's grant leaves the person's
    assert store.get("u_owner", "meeting_host") is None
    assert store.get("u_owner", "google_calendar") is not None


def test_MTG_WIRE_1_store_rejects_unsafe_ids() -> None:
    store = host_wiring.FirestoreTokenStore(FakeFirestore())
    for user, connector in (("u/../x", "meeting_host"), ("u_owner", "a/b"), ("", "meeting_host")):
        with pytest.raises(ValueError):
            store.put(user, connector, {"state": "connected"})


def test_MTG_WIRE_1_the_broker_is_built_once_and_a_failure_is_not_remembered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def fake_open(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise host_wiring.HostNotConfigured("first try fails")
        return SimpleNamespace()

    monkeypatch.setattr(host_wiring, "open_host_broker", fake_open)
    with pytest.raises(HTTPException):
        deps.get_token_broker()
    first = deps.get_token_broker()
    assert deps.get_token_broker() is first and len(calls) == 2


def test_MTG_WIRE_1_a_build_error_is_never_echoed_or_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "sk-" + "z" * 12

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(secret)

    monkeypatch.setattr(host_wiring, "open_host_broker", boom)
    with caplog.at_level(logging.DEBUG), pytest.raises(HTTPException) as caught:
        deps.get_token_broker()
    assert caught.value.detail == "not_configured" and caught.value.__cause__ is None
    assert secret not in caplog.text and secret not in str(caught.value.detail)


def test_MTG_WIRE_1_transport_needs_the_live_switch_and_is_the_live_transport() -> None:
    with pytest.raises(host_wiring.HostNotConfigured):
        host_wiring.open_host_transport({})
    built = host_wiring.open_host_transport({LIVE_KEY: "1"})
    assert type(built).__name__ == "LiveTransport"


def test_MTG_WIRE_1_revoked_bot_grant_reaches_the_outbox_sink() -> None:
    seen: list[dict] = []
    sink = host_wiring.connection_sink(lambda part: seen.append(part) or 0)
    sink({"type": "connection.revoked", "user_id": "u_owner", "data": {"connector": "meeting_host"}})
    assert len(seen) == 1
    sink({"type": "connection.revoked"})  # a malformed part never raises out of the broker's emit
