"""FR-CON-04 live smoke harness, part 1: the live HTTP layer (EFF-01, SEC-02, PRD 12.1, 16.1).

`tilo_connectors.live` has `LiveHttpClient` (the token broker's HttpClient) and `LiveTransport` (the Gmail and
Drive adapters' Transport). They are the only code in the repo that can reach Google, so they are refused
unless LIVE=1, talk only to a fixed list of Google hosts over https, follow no redirect, time out, retry
nothing themselves, and never let a token, an authorization header, a client secret or an auth code reach a
log, an exception or a repr. API_FR_CON_04_live_smoke.md pins the names. No test here leaves 127.0.0.0/8.

Every test fails today with `ModuleNotFoundError: tilo_connectors.live`.
"""

from __future__ import annotations

import base64
import http.client
import io
import json
import logging
import time
import traceback
from urllib.parse import urlsplit

import pytest
from _gapi_lib import FakeArtifacts
from _live_lib import (
    TrapServer,
    World,
    json_reply,
    live_hangup_port,  # noqa: F401 - fixture `hangup_port`
    live_world,  # noqa: F401 - fixture `world`
    no_external_network,  # noqa: F401 - autouse guard
)
from _oauth_lib import GMAIL_READONLY, OWNER, REVOKE_URL, TOKEN_URL, fake_secret, gmail_decl, leaks
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st


def live():
    import importlib

    return importlib.import_module("tilo_connectors.live")


def client(kind: str, world: World | None = None, environ: dict | None = None, **options):
    """LiveHttpClient or LiveTransport; with a world, pointed at its fake server (loopback http is opt-in)."""
    cls = getattr(live(), kind)
    if world is not None:
        options = {"endpoint_overrides": world.server.overrides(), "allow_loopback_http": True, **options}
    return cls({"LIVE": "1"} if environ is None else environ, **options)


def call(kind: str, target, url: str, *, token: str | None = None, form: dict | None = None, **kw):
    if kind == "LiveHttpClient":
        return target.post(url, data=form or {"a": "b"})
    headers = {"authorization": f"Bearer {token}"} if token else None
    return target.request("GET", url, headers=headers, **kw)


KINDS = ["LiveHttpClient", "LiveTransport"]


# ---------------------------------------------------------------------------
# EFF-01: nothing live without LIVE=1


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "environ", [{}, {"LIVE": ""}, {"LIVE": "0"}, {"LIVE": "true"}, {"LIVE": "yes"}, {"LIVE": " 1"}, {"LIVE": "01"}]
)
def test_FR_CON_04_live_requires_live_env(kind, environ):
    """EFF-01: only the exact value "1" enables a live client; the refusal names the variable."""
    with pytest.raises(live().LiveNotEnabled) as caught:
        client(kind, environ=environ)
    assert "LIVE=1" in str(caught.value)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CON_04_live_env_one_constructs_without_touching_the_network(kind):
    assert client(kind, environ={"LIVE": "1"}) is not None  # the no_external_network guard proves no socket


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CON_04_live_default_environ_is_the_process_environment(kind, monkeypatch):
    monkeypatch.delenv("LIVE", raising=False)
    with pytest.raises(live().LiveNotEnabled):
        getattr(live(), kind)()
    monkeypatch.setenv("LIVE", "1")  # the test's own patched environ, undone after the test
    assert getattr(live(), kind)() is not None


def test_FR_CON_04_live_smoke_requires_live_env_before_any_side_effect(world):
    """run_smoke checks LIVE first: no consent URL, no listener, no request, nothing printed."""
    environ = {k: v for k, v in world.environ.items() if k != "LIVE"}
    urls: list[str] = []
    out = io.StringIO()
    with pytest.raises(live().LiveNotEnabled):
        live().run_smoke(
            environ=environ,
            out=out,
            on_consent_url=urls.append,
            endpoint_overrides=world.server.overrides(),
            allow_loopback_http=True,
            store=world.store,
        )
    assert urls == [] and "accounts.google.com" not in out.getvalue()
    assert world.server.hits == []
    with pytest.raises(OSError):  # nothing listens on the callback port
        http.client.HTTPConnection("127.0.0.1", world.callback_port, timeout=1).request("GET", "/")


# ---------------------------------------------------------------------------
# The host allow-list


def test_FR_CON_04_live_default_allow_list_is_the_fixed_google_hosts():
    from tilo_connectors.adapters import DRIVE_API, DRIVE_UPLOAD_API, GMAIL_API

    expected = frozenset({"oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com"})
    assert live().ALLOWED_HOSTS == expected
    for kind in KINDS:
        assert frozenset(client(kind).allowed_hosts) == expected
    # and it covers every endpoint the broker and both adapters really call
    for url in (TOKEN_URL, REVOKE_URL, GMAIL_API, DRIVE_API, DRIVE_UPLOAD_API):
        assert urlsplit(url).hostname in expected, url


def test_FR_CON_04_live_default_has_no_loopback_or_override_way_in(world):
    """Production defaults: https only, Google hosts only. http to loopback needs the explicit flag."""
    for kind in KINDS:
        target = client(kind)
        with pytest.raises(live().HostRefused):
            call(kind, target, f"http://127.0.0.1:{world.server.port}/gmail/v1/users/me/profile")
    assert world.server.hits == []


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/gmail/v1/users/me/profile",
        "https://gmail.googleapis.com.evil.example/gmail/v1/users/me/profile",
        "https://evilgmail.googleapis.com/gmail/v1/users/me/profile",
        "https://evil.example/?h=gmail.googleapis.com",
        "https://gmail.googleapis.com@evil.example/x",
        "https://user:pw@gmail.googleapis.com/x",
        "http://gmail.googleapis.com/gmail/v1/users/me/profile",
        "http://oauth2.googleapis.com/token",
        "ftp://gmail.googleapis.com/x",
        "https://gmail.googleapis.com:8443/x",
        "https://127.0.0.1/x",
        "https://localhost/x",
        "https://[::1]/x",
        "//gmail.googleapis.com/x",
        "gmail.googleapis.com/x",
        "/gmail/v1/users/me/profile",
        "",
    ],
)
def test_FR_CON_04_live_refuses_hosts_outside_the_allow_list_before_any_request(kind, url):
    """A refused URL is refused before DNS and before a socket (the autouse guard records any attempt)."""
    with pytest.raises(live().HostRefused):
        call(kind, client(kind), url, token=fake_secret("at"))


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CON_04_live_refusal_message_holds_no_url_or_credential(kind):
    token, code = fake_secret("at"), fake_secret("code")
    url = f"https://evil.example/cb?code={code}&access_token={token}"
    with pytest.raises(live().HostRefused) as caught:
        call(kind, client(kind), url, token=token, form={"code": code, "client_secret": token})
    text = str(caught.value) + repr(caught.value) + "".join(traceback.format_exception(caught.value))
    assert not leaks(text, [token, code])
    assert "evil.example" not in str(caught.value)  # the refused URL is not echoed


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    prefix=st.sampled_from(["", "x.", "x@", "@", "user:pw@", "0.", "-", "."]),
    host=st.one_of(
        st.sampled_from(["oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com", "googleapis.com"]),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-", min_size=1, max_size=30),
    ),
    suffix=st.sampled_from(["", ".evil.example", ":80", ":8443", "@evil.example", ".", "%2e.evil", "\\@evil.example"]),
    scheme=st.sampled_from(["https", "http", "HTTPS", "ftp", "file", "ws", ""]),
)
def test_FR_CON_04_live_property_only_exact_https_google_hosts_pass(prefix, host, suffix, scheme):
    """Property: whatever URL is built from allowed-looking and random pieces, anything that is not exactly
    https + an allowed host (default port, no userinfo) is a HostRefused, never another error, never a socket."""
    url = f"{scheme}://{prefix}{host}{suffix}/gmail/v1/users/me/profile"
    parts = prefix + host + suffix
    plain = {"oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com"}
    assume(not (scheme.lower() == "https" and parts.lower().rstrip(".").removesuffix(":443") in plain))
    for kind in KINDS:
        with pytest.raises(live().HostRefused):
            call(kind, client(kind), url, token="x")


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CON_04_live_allowed_hosts_can_be_narrowed(kind, world):
    """Injecting a smaller allow-list refuses the host that is left out and still serves the one kept."""
    target = client(kind, world, allowed_hosts=["gmail.googleapis.com"])
    token = world.env.google.token_response([GMAIL_READONLY])["access_token"]
    with pytest.raises(live().HostRefused):
        call(kind, target, TOKEN_URL, token=token)
    assert world.server.hits == []
    if kind == "LiveTransport":
        reply = target.request(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"authorization": f"Bearer {token}"},
        )
        assert reply.status_code == 200 and len(world.server.hits) == 1


def test_FR_CON_04_live_endpoint_overrides_need_the_explicit_loopback_flag():
    """Re-pointing Google's hosts is a test seam: refused without the flag, and only to loopback http."""
    to_loopback = {"gmail.googleapis.com": "http://127.0.0.1:9"}
    for kind in KINDS:
        with pytest.raises(ValueError):
            client(kind, endpoint_overrides=to_loopback)  # no allow_loopback_http
        for bad in (
            {"gmail.googleapis.com": "https://evil.example"},
            {"gmail.googleapis.com": "http://evil.example:9"},
        ):
            with pytest.raises(ValueError):
                client(kind, endpoint_overrides=bad, allow_loopback_http=True)
        assert client(kind, endpoint_overrides=to_loopback, allow_loopback_http=True) is not None


# ---------------------------------------------------------------------------
# Redirects


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_FR_CON_04_live_never_follows_a_redirect_off_host(kind, status, world):
    trap = TrapServer()
    trap.start()
    try:
        token = world.env.google.token_response([GMAIL_READONLY])["access_token"]
        path = "/token" if kind == "LiveHttpClient" else "/gmail/v1/users/me/profile"
        world.server.reply(path, (status, {"Location": f"{trap.base_url}/stolen"}, b""))
        url = TOKEN_URL if kind == "LiveHttpClient" else "https://gmail.googleapis.com/gmail/v1/users/me/profile"
        with pytest.raises(live().HostRefused):
            call(kind, client(kind, world), url, token=token, form={"code": fake_secret("code")})
        assert len(world.server.hits) == 1  # the first request only
        assert trap.hits == [], "the redirect was followed: the bearer token or the form went to another host"
    finally:
        trap.stop()


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CON_04_live_a_redirect_to_a_foreign_https_host_is_refused_without_dns(kind, world):
    world.server.reply("/token", (302, {"Location": "https://evil.example/steal"}, b""))
    world.server.reply("/gmail/v1/users/me/profile", (302, {"Location": "https://evil.example/steal"}, b""))
    url = TOKEN_URL if kind == "LiveHttpClient" else "https://gmail.googleapis.com/gmail/v1/users/me/profile"
    with pytest.raises(live().HostRefused):
        call(kind, client(kind, world), url, token=fake_secret("at"))  # the guard fails the test on any resolve


# ---------------------------------------------------------------------------
# Timeouts and retries


def test_FR_CON_04_live_every_request_has_a_timeout():
    default = live().DEFAULT_TIMEOUT_S
    assert 0 < default <= 60
    for kind in KINDS:
        assert client(kind).timeout_s == default
        for bad in (0, -1, None, float("inf"), float("nan"), True):
            with pytest.raises(ValueError):
                client(kind, timeout_s=bad)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CON_04_live_a_slow_server_is_a_transport_error_within_the_timeout(kind, world):
    from tilo_connectors.adapters import TransportError

    path = "/token" if kind == "LiveHttpClient" else "/gmail/v1/users/me/profile"
    world.server.delay(path, 5.0)
    url = TOKEN_URL if kind == "LiveHttpClient" else "https://gmail.googleapis.com/gmail/v1/users/me/profile"
    started = time.monotonic()
    with pytest.raises(TransportError):
        call(kind, client(kind, world, timeout_s=0.3), url, token=fake_secret("at"))
    assert time.monotonic() - started < 3.0


def test_FR_CON_04_live_transport_makes_one_request_per_call_even_on_429_and_5xx(world):
    """Retries belong to the adapters (MAX_ATTEMPTS), so the transport must not add its own."""
    transport = client("LiveTransport", world)
    token = world.env.google.token_response([GMAIL_READONLY])["access_token"]
    url = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
    world.server.reply("/gmail/v1/users/me/profile", json_reply(503, {"error": {"code": 503}}), times=1)
    assert transport.request("GET", url, headers={"authorization": f"Bearer {token}"}).status_code == 503
    world.server.reply(
        "/gmail/v1/users/me/profile", json_reply(429, {"error": {"code": 429}}, {"Retry-After": "7"}), times=1
    )
    limited = transport.request("GET", url, headers={"authorization": f"Bearer {token}"})
    assert limited.status_code == 429 and limited.headers["retry-after"] == "7"
    assert len(world.server.gmail_hits()) == 2


def test_FR_CON_04_live_http_client_does_not_retry_a_token_call(world):
    world.server.reply("/token", json_reply(503, {"error": "backend_error"}))
    answer = client("LiveHttpClient", world).post(TOKEN_URL, data={"grant_type": "refresh_token"})
    assert answer.status_code == 503
    assert len(world.server.token_posts()) == 1  # an auth code works once: never replayed


def _gmail_adapter(world: World, **transport_options):
    from tilo_connectors.adapters import GmailAdapter

    world.env.connect(OWNER, "gmail", [GMAIL_READONLY])
    adapter = GmailAdapter(
        declaration=gmail_decl(),
        broker=world.env.broker,
        transport=client("LiveTransport", world, **transport_options),
        artifacts=FakeArtifacts(),
        owner_of=lambda world_id: OWNER,
        clock=world.env.clock,
        emit=world.env.emitted.append,
        sleep=world.sleeps.append,
    )
    return adapter


def test_FR_CON_04_live_adapter_retries_through_the_live_transport_stop_at_max_attempts(world):
    from tilo_connectors.adapters import MAX_ATTEMPTS, ProviderUnavailable

    world.server.reply("/gmail/v1/users/me/threads", json_reply(503, {"error": {"code": 503}}))
    with pytest.raises(ProviderUnavailable):
        _gmail_adapter(world).list_threads(OWNER)
    assert len(world.server.gmail_hits("GET")) == MAX_ATTEMPTS == 3
    assert all(s <= 60 for s in world.sleeps)


def test_FR_CON_04_live_adapter_honours_retry_after_through_the_live_transport(world):
    world.server.reply(
        "/gmail/v1/users/me/threads", json_reply(429, {"error": {"code": 429}}, {"Retry-After": "2"}), times=1
    )
    listed = _gmail_adapter(world).list_threads(OWNER)
    assert listed["threads"] == []
    assert len(world.server.gmail_hits("GET")) == 2 and world.sleeps == [2]
    limited = [p for p in world.env.emitted if p["type"] == "connection.rate_limited"]
    assert len(limited) == 1 and limited[0]["data"]["retry_after_s"] == 2


def test_FR_CON_04_live_a_dropped_connection_is_a_transport_error_the_adapter_turns_into_provider_unavailable(
    world, hangup_port
):
    from tilo_connectors.adapters import MAX_ATTEMPTS, ProviderUnavailable, TransportError

    dead = {"gmail.googleapis.com": f"http://127.0.0.1:{hangup_port}"}
    transport = client("LiveTransport", endpoint_overrides=dead, allow_loopback_http=True)
    with pytest.raises(TransportError):
        transport.request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile")
    with pytest.raises(ProviderUnavailable):
        _gmail_adapter(world, endpoint_overrides=dead).list_threads(OWNER)
    assert len(world.sleeps) == MAX_ATTEMPTS - 1


# ---------------------------------------------------------------------------
# What the transport sends and returns


def test_FR_CON_04_live_transport_sends_params_json_and_content_as_the_adapters_expect(world):
    echo = "/gmail/v1/users/me/echo"
    world.server.reply(
        echo,
        lambda hit: json_reply(
            200,
            {
                "method": hit.method,
                "query": hit.query,
                "ctype": hit.headers.get("content-type"),
                "auth": hit.headers.get("authorization"),
                "body_b64": base64.b64encode(hit.body).decode("ascii"),
            },
        ),
    )
    transport = client("LiveTransport", world)
    url = "https://gmail.googleapis.com" + echo
    reply = transport.request(
        "POST",
        url,
        params={"labelIds": ["INBOX", "UNREAD"], "maxResults": 5, "pageToken": None},
        headers={"authorization": "Bearer abc"},
        json={"message": {"raw": "eA=="}},
    )
    seen = reply.json()
    assert seen["method"] == "POST" and seen["auth"] == "Bearer abc"
    assert seen["query"] == {"labelIds": ["INBOX", "UNREAD"], "maxResults": ["5"]}  # None dropped, list repeated
    assert seen["ctype"].startswith("application/json")
    assert json.loads(base64.b64decode(seen["body_b64"])) == {"message": {"raw": "eA=="}}
    assert isinstance(reply.content, bytes) and reply.headers["content-type"].startswith("application/json")

    raw = transport.request("POST", url, content=b"a,b", headers={"content-type": "text/csv"}).json()
    assert base64.b64decode(raw["body_b64"]) == b"a,b" and raw["ctype"] == "text/csv"


def test_FR_CON_04_live_transport_returns_error_statuses_and_non_json_bodies_as_responses(world):
    transport = client("LiveTransport", world)
    token = world.env.google.token_response([GMAIL_READONLY])["access_token"]
    base = "https://gmail.googleapis.com/gmail/v1/users/me"
    missing = transport.request("GET", base + "/messages/nope", headers={"authorization": f"Bearer {token}"})
    assert missing.status_code == 404 and isinstance(missing.json(), dict)  # a 4xx is a response, not an exception
    world.server.reply("/gmail/v1/users/me/plain", (200, {"Content-Type": "application/octet-stream"}, b"\x00\x01raw"))
    plain = transport.request("GET", base + "/plain", headers={"authorization": f"Bearer {token}"})
    assert plain.status_code == 200 and plain.content == b"\x00\x01raw"
    with pytest.raises(ValueError):  # the adapters catch ValueError for "Google answered without JSON"
        plain.json()
    assert all(k == k.lower() for k in plain.headers)


def test_FR_CON_04_live_http_client_posts_a_form_and_returns_status_and_json(world):
    answer = client("LiveHttpClient", world).post(TOKEN_URL, data={"grant_type": "authorization_code", "code": "c1"})
    hit = world.server.token_posts()[0]
    assert hit.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert hit.form == {"grant_type": "authorization_code", "code": "c1"}
    assert answer.status_code == 401 and isinstance(
        answer.json(), dict
    )  # no client id: the fake refuses, as Google does


# ---------------------------------------------------------------------------
# Secrets


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CON_04_live_network_errors_and_reprs_hold_no_secret(kind, caplog, capsys, hangup_port):
    from tilo_connectors.adapters import TransportError

    caplog.set_level(logging.DEBUG)
    token, code, client_secret = fake_secret("at"), fake_secret("code"), fake_secret("cs")
    environ = {"LIVE": "1", "GOOGLE_OAUTH_CLIENT_SECRET": client_secret}
    dead = f"http://127.0.0.1:{hangup_port}"
    target = client(
        kind,
        environ=environ,
        endpoint_overrides={"oauth2.googleapis.com": dead, "gmail.googleapis.com": dead},
        allow_loopback_http=True,
    )
    form = {"code": code, "client_secret": client_secret, "refresh_token": token}
    with pytest.raises(TransportError) as caught:
        call(
            kind,
            target,
            TOKEN_URL if kind == "LiveHttpClient" else "https://gmail.googleapis.com/x",
            token=token,
            form=form,
        )
    secrets_ = [token, code, client_secret]
    chain = "".join(traceback.format_exception(caught.value))
    seen = " ".join([str(caught.value), repr(caught.value), chain, repr(target), str(target), caplog.text])
    printed = capsys.readouterr()
    assert not leaks(seen + printed.out + printed.err, secrets_)
    assert http.client.HTTPConnection.debuglevel == 0  # http.client's debug mode prints request headers


def test_FR_CON_04_live_a_successful_call_logs_and_prints_nothing_secret(world, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    token = world.env.google.token_response([GMAIL_READONLY])["access_token"]
    code = fake_secret("code")
    client("LiveTransport", world).request(
        "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", headers={"authorization": f"Bearer {token}"}
    )
    client("LiveHttpClient", world).post(
        TOKEN_URL, data={"code": code, "client_secret": world.env.settings.client_secret}
    )
    printed = capsys.readouterr()
    secrets_ = [token, code, world.env.settings.client_secret]
    assert not leaks(caplog.text + printed.out + printed.err, secrets_)


def test_FR_CON_04_live_authorization_goes_only_to_the_intended_server(world):
    token = world.env.google.token_response([GMAIL_READONLY])["access_token"]
    client("LiveTransport", world).request(
        "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", headers={"authorization": f"Bearer {token}"}
    )
    (hit,) = world.server.hits
    assert hit.headers["authorization"] == f"Bearer {token}" and hit.path == "/gmail/v1/users/me/profile"
