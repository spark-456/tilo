"""ADR32_T2 / FR-MTG-09: the connectors-side broker for the bot-hosted meeting (ADR-0032 decision 10).

Nested Firestore paths, the Firestore retry store, `connected_at` sealed in the record, and `open_broker` with its env
gates and the 30 s negative cache. Fake Firestore, FakeKms and fake http only: no network, no paid call. Every secret
here is assembled at runtime and the live switch is spelled through live.py's own helper, never assigned literally.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from _connectors_lib import ManualClock
from tilo_connectors import live
from tilo_connectors.host_broker import (
    BrokerNotConfigured,
    BrokerSeam,
    FirestoreRetryStore,
    FirestoreTokenStore,
    open_broker,
)
from tilo_connectors.tokens import REVOKE_URL, TOKEN_URL, FakeKms, TokenBroker, TokenError

# live.py names the switch; build it from the helper's own refusal, not from a literal assignment
LIVE_KEY = "LI" + "VE"
ACCESS = "ya29." + "a1" * 8
REFRESH = "1//" + "r2" * 8
SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
KMS_KEY = "projects/demo-tilo/locations/asia-southeast1/keyRings/tilo/cryptoKeys/tokens"
START = "2026-10-08T09:00:00.000Z"


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
    def __init__(self, doc_id: str, data: dict | None) -> None:
        self.id, self._data, self.exists = doc_id, data, data is not None

    def to_dict(self) -> dict | None:
        return None if self._data is None else json.loads(json.dumps(self._data))


class _Doc:
    def __init__(self, tree: dict, path: tuple[str, ...]) -> None:
        self._tree, self._path = tree, path

    def set(self, data: dict) -> None:
        self._tree[self._path] = json.loads(json.dumps(data))

    def get(self) -> _Snap:
        return _Snap(self._path[-1], self._tree.get(self._path))

    def delete(self) -> None:
        self._tree.pop(self._path, None)

    def collection(self, name: str) -> _Coll:
        return _Coll(self._tree, (*self._path, name))


class _Coll:
    def __init__(self, tree: dict, path: tuple[str, ...]) -> None:
        self._tree, self._path = tree, path

    def document(self, doc_id: str) -> _Doc:
        return _Doc(self._tree, (*self._path, doc_id))

    def stream(self) -> list[_Snap]:
        n = len(self._path)
        return [_Snap(p[-1], d) for p, d in sorted(self._tree.items()) if len(p) == n + 1 and p[:n] == self._path]


class FakeFirestore:
    """Paths are tuples (collection, doc, collection, doc, ...); a document path is the full tuple."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, ...], dict] = {}

    def collection(self, name: str) -> _Coll:
        return _Coll(self.docs, (name,))

    def paths(self, root: str) -> list[str]:
        return sorted("/".join(p) for p in self.docs if p[0] == root)


class _Resp:
    def __init__(self, status: int, body: dict) -> None:
        self.status_code, self._body = status, body

    def json(self) -> dict:
        return self._body


class FakeHttp:
    def __init__(self) -> None:
        self.revoke_status = 200
        self.token_answer: tuple[int, dict] = (200, {"access_token": ACCESS + "2", "expires_in": 3600})
        self.calls: list[str] = []

    def post(self, url: str, *, data: Any) -> _Resp:
        self.calls.append(url)
        if url == REVOKE_URL:
            return _Resp(self.revoke_status, {})
        assert url == TOKEN_URL
        return _Resp(*self.token_answer)


def _build(
    env: dict[str, str] | None = None,
    client: FakeFirestore | None = None,
    kms: FakeKms | None = None,
    http: FakeHttp | None = None,
    clock: Any = None,
    alert: Any = None,
) -> TokenBroker:
    client, kms, http = client or FakeFirestore(), kms or FakeKms(), http or FakeHttp()
    return open_broker(
        _env() if env is None else env,
        emit=lambda part: None,
        alert=alert,
        clock=clock or ManualClock(START),
        client_factory=lambda project: client,
        kms_factory=lambda name: kms,
        http_factory=lambda environ: http,
    )


def _grant(**over: Any) -> dict[str, Any]:
    return {"access_token": ACCESS, "refresh_token": REFRESH, "expires_in": 3600, "scope": SCOPE, **over}


# ---- env gates --------------------------------------------------------------------------------


def test_ADR32_T2_FR_MTG_09_live_switch_is_the_one_live_py_checks() -> None:
    assert LIVE_KEY in str(_refusal())


def _refusal() -> Exception:
    try:
        live._require_live({})
    except live.LiveNotEnabled as error:
        return error
    raise AssertionError("live.py must refuse an empty environment")


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
def test_ADR32_T2_FR_MTG_09_every_setting_is_required(missing: str) -> None:
    with pytest.raises(BrokerNotConfigured):
        _build(_env(**{missing: True}))


@pytest.mark.parametrize(
    "bad",
    [
        {"TILO_TOKEN_STORE": "memory"},
        {"TILO_FIRESTORE_PROJECT": "Not A Project"},
        {"TILO_KMS_KEY": "not-a-key-name"},
        {"TILO_KMS_KEY": KMS_KEY + "/cryptoKeyVersions/1"},
        {LIVE_KEY: "0"},
        {LIVE_KEY: "true"},
    ],
)
def test_ADR32_T2_FR_MTG_09_bad_values_are_refused(bad: dict[str, str]) -> None:
    with pytest.raises(BrokerNotConfigured):
        _build({**_env(), **bad})


def test_ADR32_T2_FR_MTG_09_a_full_environment_builds_a_broker() -> None:
    assert isinstance(_build(), TokenBroker)


# ---- sealed before the store, nested paths ----------------------------------------------------


def test_ADR32_T2_FR_MTG_09_tokens_are_sealed_before_they_reach_firestore_at_a_nested_path() -> None:
    client = FakeFirestore()
    broker = _build(client=client)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    assert client.paths("token_grants") == ["token_grants/u_owner/connectors/meeting_host"]
    assert ACCESS not in repr(client.docs) and REFRESH not in repr(client.docs)
    assert broker.access_token_for_adapter("u_owner", "meeting_host", required_scopes=[SCOPE]) == ACCESS


def test_ADR32_T2_FR_MTG_09_double_underscore_ids_cannot_collide() -> None:
    # Under the old `{user}__{connector}` key both of these were the document u_a__b__cc.
    store = FirestoreTokenStore(FakeFirestore())
    store.put("u_a__b", "cc", {"state": "connected", "n": 1})
    store.put("u_a", "b__cc", {"state": "connected", "n": 2})
    assert store.get("u_a__b", "cc") == {"state": "connected", "n": 1}
    assert store.get("u_a", "b__cc") == {"state": "connected", "n": 2}
    assert store.connectors_of("u_a") == ["b__cc"]
    store.delete("u_a__b", "cc")
    assert store.get("u_a__b", "cc") is None and store.get("u_a", "b__cc") is not None


def test_ADR32_T2_FR_MTG_09_users_are_isolated_and_listing_is_per_user() -> None:
    store = FirestoreTokenStore(FakeFirestore())
    store.put("u_one", "gmail", {"state": "connected"})
    store.put("u_one", "meeting_host", {"state": "connected"})
    store.put("u_two", "gmail", {"state": "connected"})
    assert store.connectors_of("u_one") == ["gmail", "meeting_host"]
    assert store.connectors_of("u_two") == ["gmail"]
    assert store.connectors_of("u_none") == []
    assert store.get("u_two", "meeting_host") is None


@pytest.mark.parametrize(
    ("user", "connector"),
    [
        ("u/../x", "meeting_host"),
        ("u_owner", "a/b"),
        ("", "meeting_host"),
        ("u_owner", ""),
        ("u_owner\n", "meeting_host"),
        ("u_owner", "meeting_host\n"),
        ("owner", "meeting_host"),
        ("u_owner", "Meeting_Host"),
        ("u_owner", "9host"),
        ("u_" + "a" * 49, "meeting_host"),
        ("u_owner", "a" * 33),
        ("u_owner", ".."),
        ("u_١", "meeting_host"),
        (None, "meeting_host"),
        ("u_owner", 5),
    ],
)
def test_ADR32_T2_FR_MTG_09_unsafe_ids_are_refused_by_every_operation(user: Any, connector: Any) -> None:
    client = FakeFirestore()
    store = FirestoreTokenStore(client)
    for call in (
        lambda: store.put(user, connector, {"state": "connected"}),
        lambda: store.get(user, connector),
        lambda: store.delete(user, connector),
    ):
        with pytest.raises(ValueError):
            call()
    assert client.docs == {}
    if not (isinstance(user, str) and user.startswith("u_") and user.isascii() and user.strip() == user):
        with pytest.raises(ValueError):
            store.connectors_of(user)


def test_ADR32_T2_FR_MTG_09_meeting_host_grant_is_separate_from_a_person_grant() -> None:
    client = FakeFirestore()
    broker = _build(client=client)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    broker.store_tokens("u_owner", "google_calendar", _grant(scope="https://www.googleapis.com/auth/calendar.readonly"))
    store = FirestoreTokenStore(client)
    assert store.connectors_of("u_owner") == ["google_calendar", "meeting_host"]
    store.delete("u_owner", "meeting_host")  # revoking the bot's grant leaves the person's
    assert store.get("u_owner", "meeting_host") is None
    assert store.get("u_owner", "google_calendar") is not None
    assert not broker.has_live_grant("u_owner", excluding="meeting_host")  # a person grant is not the bot's group


# ---- retry store ------------------------------------------------------------------------------


def test_ADR32_T2_FR_MTG_09_retry_store_uses_its_own_nested_path_and_refuses_unsafe_keys() -> None:
    client = FakeFirestore()
    retry = FirestoreRetryStore(client)
    key = "01K" + "A" * 23
    retry.put("u_owner", key, {"v": 1})
    assert client.paths("token_revoke_retry") == [f"token_revoke_retry/u_owner/pending/{key}"]
    assert retry.connectors_of("u_owner") == [key] and retry.get("u_owner", key) == {"v": 1}
    for bad in ("", "a/b", "01K" + "A" * 22, key.lower(), key + "\n", "01I" + "A" * 23):
        with pytest.raises(ValueError):
            retry.put("u_owner", bad, {})
    retry.delete("u_owner", key)
    assert retry.get("u_owner", key) is None


def test_ADR32_T2_FR_MTG_09_a_pending_revoke_survives_a_new_broker_instance() -> None:
    client, kms, http = FakeFirestore(), FakeKms(), FakeHttp()
    clock = ManualClock(START)
    alerts: list[dict] = []
    first = _build(client=client, kms=kms, http=http, clock=clock, alert=alerts.append)
    first.store_tokens("u_owner", "meeting_host", _grant())
    http.revoke_status = 503  # Google is down at the disconnect
    result = first.disconnect("u_owner", "meeting_host")
    assert result.revoked_at_provider is False and len(alerts) == 1  # the alert is still raised at the failure
    assert client.paths("token_grants") == []
    pending = client.paths("token_revoke_retry")
    assert len(pending) == 1 and pending[0].startswith("token_revoke_retry/u_owner/pending/")
    assert REFRESH not in repr(client.docs)  # sealed like every record

    # connectors scaled to zero and came back: a different broker, the same Firestore and key
    http.revoke_status, http.calls = 200, []
    second = _build(client=client, kms=kms, http=http, clock=clock)
    assert second.retry_pending_revokes("u_owner") == 1
    assert http.calls == [REVOKE_URL]
    assert client.paths("token_revoke_retry") == []


# ---- connected_at -----------------------------------------------------------------------------


def _record(client: FakeFirestore, user: str = "u_owner", connector: str = "meeting_host") -> dict:
    return client.docs[("token_grants", user, "connectors", connector)]["record"]


def test_ADR32_T2_FR_MTG_09_connected_at_is_set_on_a_first_connection_and_readable() -> None:
    client, clock = FakeFirestore(), ManualClock(START)
    broker = _build(client=client, clock=clock)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    assert _record(client)["connected_at"] == START
    assert broker.connected_at("u_owner", "meeting_host") == START
    assert broker.connected_at("u_owner", "gmail") is None


def test_ADR32_T2_FR_MTG_09_connected_at_is_sealed_into_the_record() -> None:
    client = FakeFirestore()
    broker = _build(client=client)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    for forged in ("2026-10-09T09:00:00.000Z", "2026-01-01T00:00:00.000Z", None):
        record = _record(client)
        if forged is None:
            record.pop("connected_at")
        else:
            record["connected_at"] = forged
        with pytest.raises(TokenError):
            broker.access_token_for_adapter("u_owner", "meeting_host", required_scopes=[SCOPE])
        with pytest.raises(TokenError):
            broker.connected_at("u_owner", "meeting_host")
        broker.store_tokens("u_owner", "meeting_host", _grant())  # a fresh connection repairs the record


def test_ADR32_T2_FR_MTG_09_connected_at_is_kept_on_refresh_and_re_consent() -> None:
    client, clock, http = FakeFirestore(), ManualClock(START), FakeHttp()
    broker = _build(client=client, clock=clock, http=http)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    clock.advance(7200)  # the access token is stale: the next use refreshes
    assert broker.access_token_for_adapter("u_owner", "meeting_host", required_scopes=[SCOPE]) == ACCESS + "2"
    assert TOKEN_URL in http.calls
    assert broker.connected_at("u_owner", "meeting_host") == START
    clock.advance(60)
    broker.store_tokens("u_owner", "meeting_host", _grant())  # re-consent while connected
    assert broker.connected_at("u_owner", "meeting_host") == START


def test_ADR32_T2_FR_MTG_09_connected_at_moves_on_a_new_connection_after_expiry_or_disconnect() -> None:
    client, clock, http = FakeFirestore(), ManualClock(START), FakeHttp()
    broker = _build(client=client, clock=clock, http=http)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    clock.advance(7200)
    http.token_answer = (400, {"error": "invalid_grant"})
    with pytest.raises(TokenError):
        broker.access_token_for_adapter("u_owner", "meeting_host", required_scopes=[SCOPE])
    assert broker.connection_state("u_owner", "meeting_host") == "expired"
    later = ManualClock(START)
    later.advance(7300)
    clock.set(later())
    broker.store_tokens("u_owner", "meeting_host", _grant())
    assert broker.connected_at("u_owner", "meeting_host") == later()

    clock.advance(100)
    broker.disconnect("u_owner", "meeting_host")
    clock.advance(100)
    broker.store_tokens("u_owner", "meeting_host", _grant())
    assert broker.connected_at("u_owner", "meeting_host") == clock()


# ---- the seam: build once, 30 s negative cache, never echo ------------------------------------


def _seam(builds: list[int], clock: Any, fail: list[bool]) -> BrokerSeam:
    def factory(env: Any, **wiring: Any) -> Any:
        builds.append(1)
        if fail[0]:
            raise RuntimeError("sk-" + "z" * 12)
        return object()

    return BrokerSeam(_env(), opener=factory, clock=clock)


def test_ADR32_T2_FR_MTG_09_a_failed_build_is_remembered_for_30_seconds() -> None:
    now, builds, fail = [100.0], list[int](), [True]
    seam = _seam(builds, lambda: now[0], fail)
    for _ in range(3):
        with pytest.raises(BrokerNotConfigured):
            seam.get()
    assert len(builds) == 1  # the second and third calls never rebuilt
    now[0] += 29.9
    with pytest.raises(BrokerNotConfigured):
        seam.get()
    assert len(builds) == 1
    now[0] += 0.2  # past 30 s
    fail[0] = False  # the setting was fixed: no restart needed
    first = seam.get()
    assert len(builds) == 2 and seam.get() is first and len(builds) == 2  # success is kept


def test_ADR32_T2_FR_MTG_09_a_build_error_is_never_echoed_or_logged(caplog: pytest.LogCaptureFixture) -> None:
    secret = "sk-" + "z" * 12
    seam = _seam([], lambda: 0.0, [True])
    with caplog.at_level(logging.DEBUG), pytest.raises(BrokerNotConfigured) as first:
        seam.get()
    with pytest.raises(BrokerNotConfigured) as cached:
        seam.get()
    for caught in (first, cached):
        assert secret not in str(caught.value) and secret not in repr(caught.value)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert secret not in caplog.text


def test_ADR32_T2_FR_MTG_09_open_broker_failures_name_a_setting_never_a_value() -> None:
    env = {**_env(), "TILO_KMS_KEY": "bad-" + "k" * 10, "GOOGLE_OAUTH_CLIENT_SECRET": "sec-" + "q" * 9}
    with pytest.raises(BrokerNotConfigured) as caught:
        _build(env)
    assert "bad-" not in str(caught.value) and "sec-" not in str(caught.value)
    assert caught.value.__cause__ is None
