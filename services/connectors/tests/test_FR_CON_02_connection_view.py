"""FR-CON-02 / LIVE-GAPS-1b: `TokenBroker.connection_view` returns only (state, scopes, expires_at), writes nothing."""

from __future__ import annotations

from typing import Any

from tilo_connectors.tokens import FakeKms, InMemoryTokenStore, OAuthSettings, TokenBroker


class _Http:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, url: str, *, data: Any) -> Any:
        self.calls += 1
        raise AssertionError("connection_view must not call the provider")


def _broker(store: InMemoryTokenStore, http: _Http) -> TokenBroker:
    return TokenBroker(
        store=store,
        kms=FakeKms(),
        http=http,
        settings=OAuthSettings(client_id="client-example", client_secret="-".join(["fake", "secret"])),
        clock=lambda: "2026-10-08T00:00:00.000Z",
        emit=lambda _part: None,
    )


def test_FR_CON_02_connection_view_returns_only_state_scopes_expiry() -> None:
    store, http = InMemoryTokenStore(), _Http()
    broker = _broker(store, http)
    assert broker.connection_view("u_a", "gmail") == (None, [], None)
    broker.store_tokens(
        "u_a", "gmail", {"access_token": "a", "refresh_token": "r", "scope": "s2 s1", "expires_in": 3600}
    )
    state, scopes, expires_at = broker.connection_view("u_a", "gmail")
    assert (state, scopes) == ("connected", ["s1", "s2"])
    assert expires_at == store.get("u_a", "gmail")["expires_at"]
    assert broker.connection_view("u_b", "gmail") == (None, [], None)
    store.put("u_a", "gmail", {"v": 1, "state": "expired", "scopes": ["s1"], "expires_at": None})
    assert broker.connection_view("u_a", "gmail") == ("expired", [], None)
    assert http.calls == 0


def test_FR_CON_02_connection_view_sanitises_expiry_scopes_and_non_live_rows() -> None:
    store, http = InMemoryTokenStore(), _Http()
    broker = _broker(store, http)
    base = {"v": 1, "state": "connected", "scopes": ["s1"], "expires_at": "2026-10-08T01:02:03.000Z"}
    store.put("u", "a", base)
    assert broker.connection_view("u", "a") == ("connected", ["s1"], "2026-10-08T01:02:03.000Z")
    store.put("u", "b", {**base, "expires_at": "tomorrow"})
    assert broker.connection_view("u", "b")[2] is None
    store.put("u", "c", {**base, "scopes": "abc"})
    assert broker.connection_view("u", "c")[1] == []
    store.put("u", "d", {**base, "scopes": [f"s{i}" for i in range(80)] + ["x" * 201, 5]})
    assert len(broker.connection_view("u", "d")[1]) == 50
    store.put("u", "e", {**base, "state": "weird"})
    assert broker.connection_view("u", "e") == ("weird", [], None)
    assert http.calls == 0
