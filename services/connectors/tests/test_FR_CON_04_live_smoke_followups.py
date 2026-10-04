"""FR-CON-04 live smoke harness, security follow-ups (user-reported sign-in worked; hardening before merge).

The allow-list can only be narrowed, a listener on [::1] stops the run, messages are fetched as metadata only,
the callback listener caps its handler threads, and an absurd timeout is a clean stop. The existing pinned
tests are unchanged. No test leaves 127.0.0.0/8.
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import re
import socket
import time

import pytest
from _live_lib import (
    CALLBACK_PATH,
    GMAIL_PREFIX,
    approve,
    get_callback,
    live_world,  # noqa: F401 - fixture `world`
    no_external_network,  # noqa: F401 - autouse guard
    port_is_closed,
    start_smoke,
)
from _oauth_lib import REPO_ROOT, fake_secret

SCRIPT = REPO_ROOT / "services" / "connectors" / "scripts" / "live_gmail_smoke.py"
KINDS = ["LiveHttpClient", "LiveTransport"]


def live():
    return importlib.import_module("tilo_connectors.live")


def script():
    spec = importlib.util.spec_from_file_location("live_gmail_smoke_followups", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 1. the allow-list can be narrowed, never widened


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "hosts",
    [["evil.example"], ["gmail.googleapis.com", "evil.example"], ["googleapis.com"], ["127.0.0.1"], ["localhost"]],
)
def test_FR_CON_04_live_allowed_hosts_cannot_be_widened(kind, hosts):
    with pytest.raises(ValueError):
        getattr(live(), kind)({"LIVE": "1"}, allowed_hosts=hosts)
    with pytest.raises(ValueError):
        getattr(live(), kind)({"LIVE": "1"}, allowed_hosts=[*live().ALLOWED_HOSTS, *hosts])


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CON_04_live_allowed_hosts_may_be_narrowed_or_empty(kind):
    assert getattr(live(), kind)({"LIVE": "1"}, allowed_hosts=[]).allowed_hosts == frozenset()
    one = getattr(live(), kind)({"LIVE": "1"}, allowed_hosts=["GMAIL.googleapis.com"])
    assert one.allowed_hosts == {"gmail.googleapis.com"}


def test_FR_CON_04_live_smoke_refuses_widened_hosts_before_any_side_effect(world):
    run = start_smoke(world, allowed_hosts=["evil.example"], callback_timeout_s=3)
    run.raised(live().SmokeError)
    assert "accounts.google.com" not in run.out.getvalue() and world.server.hits == []
    assert port_is_closed(world.callback_port)


# 2. something on [::1]:port could receive the code before the listener does


def _ipv6_listener(port: int) -> socket.socket:
    if not socket.has_ipv6:
        pytest.skip("no IPv6 here")
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    try:
        sock.bind(("::1", port))
        sock.listen(1)
    except OSError:
        sock.close()
        pytest.skip("[::1] is not usable here")
    return sock


def test_FR_CON_04_live_smoke_refuses_to_start_when_something_listens_on_ipv6_loopback(world):
    other = _ipv6_listener(world.callback_port)
    try:
        run = start_smoke(world, callback_timeout_s=3)
        error = run.raised(live().SmokeError)
        assert not isinstance(error, live().CallbackTimeout), "refused up front, not after waiting"
        assert "::1" in str(error) and "accounts.google.com" not in run.out.getvalue()
        assert world.server.hits == []
    finally:
        other.close()
    assert port_is_closed(world.callback_port)


def test_FR_CON_04_live_smoke_accepts_a_localhost_redirect_base_when_ipv6_is_free(world):
    environ = {**world.environ, "GOOGLE_OAUTH_REDIRECT_BASE_URL": f"http://localhost:{world.callback_port}"}
    world.seed_inbox(1)
    run = start_smoke(world, environ=environ)
    flow, _, reply = approve(world, run)
    assert reply[0] == 200 and flow.query["redirect_uri"] == f"http://localhost:{world.callback_port}{CALLBACK_PATH}"
    assert len(run.value().messages) == 1


# 4. messages are read as headers only


def test_FR_CON_04_live_smoke_fetches_headers_only_never_the_full_message(world):
    world.seed_inbox(3)
    run = start_smoke(world)
    approve(world, run)
    result = run.value()
    assert len(result.messages) == 3
    fetches = [h for h in world.server.gmail_hits("GET") if re.fullmatch(rf"{GMAIL_PREFIX}/messages/[^/]+", h.path)]
    assert len(fetches) == 3
    for hit in fetches:
        assert hit.query["format"] == ["metadata"]
        assert sorted(hit.query["metadataHeaders"]) == ["Date", "From", "Subject"]


def test_FR_CON_04_live_adapter_get_message_stays_full_by_default_and_takes_headers():
    from _gapi_lib import GMAIL_API, make_gapi_env
    from _oauth_lib import OWNER

    g = make_gapi_env()
    seeded = g.apis.seed_message(thread_id="thr_a", subject="Hello", body="Body text\n")
    assert g.gmail.get_message(OWNER, seeded["id"])["body_text"].strip() == "Body text"
    g.gmail.get_message(OWNER, seeded["id"], headers=["Date"])
    gets = [r for r in g.apis.requests if r.url == f"{GMAIL_API}/messages/{seeded['id']}"]
    assert gets[0].params["format"] == "full"
    assert gets[-1].params == {"format": "metadata", "metadataHeaders": ["Date"]}


# 5. the callback listener caps its handler threads


def _drop_or_empty(sock: socket.socket) -> bool:
    sock.settimeout(1.5)
    try:
        return sock.recv(64) == b""
    except (ConnectionResetError, ConnectionAbortedError):
        return True


def test_FR_CON_04_live_callback_drops_connections_beyond_the_handler_cap(waiting_server):
    state = fake_secret("state")
    server = waiting_server(state)
    idle = [socket.create_connection(("127.0.0.1", server.port), timeout=5) for _ in range(8)]
    try:
        time.sleep(0.4)  # let the accept loop hand each one a handler
        extra = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        extra.sendall(f"GET {CALLBACK_PATH}?code=x&state={state} HTTP/1.0\r\n\r\n".encode())
        started = time.monotonic()
        assert _drop_or_empty(extra), "the ninth connection must be dropped, not served"
        assert time.monotonic() - started < 1.5
        extra.close()
    finally:
        for sock in idle:
            sock.close()
    time.sleep(0.4)  # the handlers see the hang-up and free their slots
    assert get_callback(server.port, {"code": "fine", "state": state})[0] == 200
    assert server.wait().code == "fine"


@pytest.fixture()
def waiting_server():
    made = []

    def make(state: str):
        server = live().CallbackServer(expected_state=state, port=0, timeout_s=20)
        made.append(server)
        return server

    yield make
    for server in made:
        server.close()


# 6. an absurd timeout is a clean stop


@pytest.mark.parametrize("bad", [1e300, 3601, 10**9, float("nan"), float("inf"), 0, -5])
def test_FR_CON_04_live_callback_timeout_has_an_upper_bound(bad):
    with pytest.raises(ValueError):
        live().CallbackServer(expected_state="s", port=0, timeout_s=bad)


def test_FR_CON_04_live_callback_timeout_of_an_hour_is_accepted():
    live().CallbackServer(expected_state="s", port=0, timeout_s=3600).close()


@pytest.mark.parametrize("bad", ["1e300", "3601", "nan", "inf", "0", "-5"])
def test_FR_CON_04_live_smoke_cli_absurd_timeout_is_a_clean_stop(world, bad):
    out = io.StringIO()
    code = script().main(["--timeout", bad], environ=world.environ, out=out)
    assert code not in (0, None)
    text = out.getvalue()
    assert "Smoke check stopped" in text and "Traceback" not in text and "accounts.google.com" not in text
    assert world.server.hits == [] and port_is_closed(world.callback_port)
