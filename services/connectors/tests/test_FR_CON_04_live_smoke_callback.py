"""FR-CON-04 live smoke harness, part 2: the one-shot OAuth callback listener (PRD 12.1, 16.1, SEC-02).

`tilo_connectors.live.CallbackServer` waits for Google's redirect on 127.0.0.1, accepts exactly one request
that carries the expected `state`, and then closes. A stray, forged or oversized request never ends the wait
and never reaches the token exchange. API_FR_CON_04_live_smoke.md pins the names. No test leaves 127.0.0.0/8.

Every test fails today with `ModuleNotFoundError: tilo_connectors.live`.
"""

from __future__ import annotations

import inspect
import re
import socket
import threading
import time

import pytest
from _live_lib import (
    CALLBACK_PATH,
    get_callback,
    no_external_network,  # noqa: F401 - autouse guard
    port_is_closed,
)
from _oauth_lib import fake_secret, leaks


def live():
    import importlib

    return importlib.import_module("tilo_connectors.live")


class Waiting:
    """A CallbackServer whose wait() runs in a thread, so the test can play the browser."""

    def __init__(self, state: str, timeout_s: float = 10.0) -> None:
        self.server = live().CallbackServer(expected_state=state, port=0, timeout_s=timeout_s)
        self.port = self.server.port
        self.result = None
        self.error: BaseException | None = None
        self.done = threading.Event()
        self.started = time.monotonic()
        threading.Thread(target=self._wait, daemon=True).start()

    def _wait(self) -> None:
        try:
            self.result = self.server.wait()
        except BaseException as exc:  # noqa: BLE001
            self.error = exc
        finally:
            self.done.set()

    def finished(self, timeout: float = 10.0) -> bool:
        return self.done.wait(timeout)

    def close(self) -> None:
        self.server.close()


@pytest.fixture()
def waiting():
    made: list[Waiting] = []

    def make(state: str | None = None, timeout_s: float = 10.0) -> Waiting:
        w = Waiting(state or fake_secret("state"), timeout_s)
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()


# ---------------------------------------------------------------------------
# Binding


def test_FR_CON_04_live_callback_binds_loopback_only(waiting):
    w = waiting()
    assert w.server.address == ("127.0.0.1", w.port)
    params = inspect.signature(live().CallbackServer.__init__).parameters
    assert not {"host", "bind", "address", "interface"} & set(params), "there is no way to bind elsewhere"
    # A listener on 0.0.0.0 also answers on every other 127.x address; one bound to 127.0.0.1 does not.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        assert probe.connect_ex(("127.0.0.2", w.port)) != 0, "the listener answers on more than 127.0.0.1"
    if socket.has_ipv6:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe6:
            probe6.settimeout(1.0)
            assert probe6.connect_ex(("::1", w.port, 0, 0)) != 0, "the listener answers on IPv6 loopback"
    assert not w.finished(0.2), "nothing arrived, so the wait goes on"


def test_FR_CON_04_live_callback_default_port_and_path_are_the_registered_redirect():
    assert live().CALLBACK_PATH == CALLBACK_PATH == "/oauth/google/callback"
    assert inspect.signature(live().CallbackServer.__init__).parameters["port"].default == 8080


# ---------------------------------------------------------------------------
# One valid callback, then closed


def test_FR_CON_04_live_callback_accepts_one_valid_request_then_shuts_down(waiting):
    state, code = fake_secret("state"), fake_secret("code")
    w = waiting(state)

    status, headers, body = get_callback(w.port, {"code": code, "state": state})

    assert status == 200
    assert w.finished() and w.error is None
    assert w.result.code == code and w.result.error is None
    assert port_is_closed(w.port), "the listener must be closed after the one callback"
    with pytest.raises(OSError):
        get_callback(w.port, {"code": fake_secret("code2"), "state": state})  # a reused state finds nobody
    assert not leaks(body + str(headers), [code, state]), "the page must not echo the code or the state"


def test_FR_CON_04_live_callback_page_is_not_cached_and_sends_no_referrer(waiting):
    state = fake_secret("state")
    w = waiting(state)
    _, headers, _ = get_callback(w.port, {"code": fake_secret("code"), "state": state})
    assert "no-store" in headers.get("cache-control", "")
    assert headers.get("referrer-policy") == "no-referrer"  # the URL in the address bar holds the code
    assert headers.get("content-type", "").startswith(("text/html", "text/plain"))


@pytest.mark.parametrize(
    "params",
    [
        {"code": "c"},  # state missing
        {"code": "c", "state": ""},
        {"code": "c", "state": "zq7forged"},
        {"code": "c", "state": "WRONG-CASE"},
        [("code", "c"), ("state", "zq7forged"), ("state", "RIGHT")],  # parameter pollution: first wrong
        [("code", "c"), ("state", "RIGHT"), ("state", "zq7forged")],  # parameter pollution: second wrong
        [("code", "c"), ("state", "RIGHT"), ("state", "RIGHT")],  # a duplicate is ambiguous even if equal
        {"error": "access_denied", "state": "zq7forged"},  # a forged denial must not end the flow either
    ],
)
def test_FR_CON_04_live_callback_rejects_wrong_missing_or_duplicated_state(params, waiting):
    state = "RIGHT"
    w = waiting(state)
    status, headers, body = get_callback(w.port, params)
    assert status == 400
    assert not w.finished(0.3), "a rejected request must not end the wait"
    assert "zq7forged" not in body  # nothing the caller sent is echoed

    # the real redirect still works afterwards
    get_callback(w.port, {"code": "real-code", "state": state})
    assert w.finished() and w.result.code == "real-code"


def test_FR_CON_04_live_callback_ignores_other_paths_and_methods(waiting):
    state = fake_secret("state")
    w = waiting(state)
    assert get_callback(w.port, {"code": "c", "state": state}, path="/")[0] == 404
    assert get_callback(w.port, {"code": "c", "state": state}, path=CALLBACK_PATH + "/x")[0] == 404
    assert get_callback(w.port, {"code": "c", "state": state}, path="/oauth/google/callback2")[0] == 404
    assert get_callback(w.port, {"code": "c", "state": state}, method="POST")[0] in (400, 404, 405, 501)
    assert not w.finished(0.3)
    get_callback(w.port, {"code": "ok", "state": state})
    assert w.finished() and w.result.code == "ok"


def test_FR_CON_04_live_callback_survives_an_oversized_request(waiting):
    state = fake_secret("state")
    w = waiting(state)
    try:
        status = get_callback(w.port, {"code": "x" * 100_000, "state": state})[0]
        assert status in (400, 413, 414, 431)
    except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
        pass  # the server hung up on a request line it would not read: also a refusal
    assert not w.finished(0.2)
    assert get_callback(w.port, {"code": "fine", "state": state})[0] == 200
    assert w.finished() and w.result.code == "fine"


def test_FR_CON_04_live_callback_is_not_stalled_by_an_idle_connection(waiting):
    """A local process that connects and sends nothing must not block the real redirect (one thread per client)."""
    state = fake_secret("state")
    w = waiting(state)
    idle = socket.create_connection(("127.0.0.1", w.port), timeout=5)
    try:
        started = time.monotonic()
        assert get_callback(w.port, {"code": "fine", "state": state})[0] == 200
        assert time.monotonic() - started < 5.0
        assert w.finished() and w.result.code == "fine"
    finally:
        idle.close()


# ---------------------------------------------------------------------------
# error=access_denied and an empty answer


def test_FR_CON_04_live_callback_reports_access_denied_cleanly(waiting):
    state = fake_secret("state")
    w = waiting(state)
    status, _, body = get_callback(w.port, {"error": "access_denied", "state": state})
    assert status < 500 and "Traceback" not in body
    assert w.finished() and w.error is None
    assert w.result.error == "access_denied" and w.result.code is None
    assert port_is_closed(w.port)


@pytest.mark.parametrize("hostile", ["\x1b[31mred\nline2", "x" * 500, "a b;rm -rf", "é"])
def test_FR_CON_04_live_callback_error_text_is_a_short_safe_token(hostile, waiting):
    state = fake_secret("state")
    w = waiting(state)
    get_callback(w.port, {"error": hostile, "state": state})
    assert w.finished()
    assert re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", w.result.error), "an error text that reaches a terminal is sanitised"
    assert w.result.code is None


def test_FR_CON_04_live_callback_with_neither_code_nor_error_is_an_error_result(waiting):
    state = fake_secret("state")
    w = waiting(state)
    get_callback(w.port, {"state": state})
    assert w.finished() and w.result.code is None and w.result.error


# ---------------------------------------------------------------------------
# Timeout, repr


def test_FR_CON_04_live_callback_times_out_after_the_configured_seconds_and_frees_the_port(waiting):
    w = waiting(timeout_s=0.5)
    assert w.finished(5.0)
    assert isinstance(w.error, live().CallbackTimeout)
    assert 0.4 <= time.monotonic() - w.started < 4.0
    assert port_is_closed(w.port)
    assert "Traceback" not in str(w.error) and str(w.error)


def test_FR_CON_04_live_callback_values_never_appear_in_a_repr(waiting):
    state, code = fake_secret("state"), fake_secret("code")
    w = waiting(state)
    get_callback(w.port, {"code": code, "state": state})
    assert w.finished()
    text = " ".join([repr(w.server), str(w.server), repr(w.result), str(w.result)])
    assert not leaks(text, [state, code])


def test_FR_CON_04_live_callback_timeout_must_be_a_positive_finite_number():
    for bad in (0, -1, None, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            live().CallbackServer(expected_state="s", port=0, timeout_s=bad)
    with pytest.raises(ValueError):
        live().CallbackServer(expected_state="", port=0, timeout_s=1)  # no state, no flow
