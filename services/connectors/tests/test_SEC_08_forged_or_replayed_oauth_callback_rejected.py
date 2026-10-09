"""SEC-08 (PRD 16.4: "Signed webhooks and signed email links" -> "Forged or replayed requests rejected"; PRD 16.2) for
the inbound surfaces of tilo-connectors.

Inbound surfaces of tilo-connectors, enumerated from the code (route decorators, `hmac` / `compare_digest` users and
the OAuth modules under services/connectors/src, 2026-10-07):

1. The Google OAuth redirect: `ConsentService.handle_callback(user_id, state, code)`. Not an HMAC-signed request: the
   `state` is a 256-bit random, per-flow, per-user, 600 s, single-use anti-forgery token held server side, so a
   forged state has nothing to match and a replayed one is already spent. It is the one inbound request tilo-connectors
   accepts from outside, and it is listed here because SEC-08's claim ("forged or replayed requests rejected") covers
   it even though the mechanism is a state table, not a signature.
2. The one-shot loopback listener of the live smoke harness: `tilo_connectors.live.CallbackServer` (127.0.0.1 only,
   `hmac.compare_digest` on the state, one accepted request, then closed). Real sockets, loopback only.
3. Route guard: `tilo_connectors.app` mounts `/health` and `/healthz` only. There is no webhook receiver (Calendar and
   Gmail pushes are received by tilo-channels, tested in services/channels/tests; WhatsApp left scope, ADR-0019). The
   guard fails when a new route appears, so a new inbound route cannot ship without SEC-08 cases added here.

Acceptance claim: a forged, tampered, missing, someone else's, expired or replayed callback is rejected, BEFORE any
authorisation code is exchanged, and leaves no token stored and no event emitted; a genuine, fresh callback is
accepted (positive control).

Defaults where the PRD is silent (as FR-CON-03 already chose): state lifetime 600 s, tested at 599 s and 601 s; a
refused state that belongs to a live flow is spent by its first presenter, whoever that is ("every state is spent by
its first use"), so a stranger who learns a state can cancel the person's connect but can never complete it.
No real secrets: client id, client secret, states and codes are random runtime strings from the fakes.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from _live_lib import get_callback, port_is_closed
from _live_lib import no_external_network as no_external_network  # noqa: F401 - autouse guard
from _oauth_lib import CARD_ID, DRIVE_FILE, OTHER, OWNER, fake_secret, finish_flow, make_env, start_flow
from fastapi.routing import APIRoute
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_connectors.consent import ConsentRefused
from tilo_connectors.live import CALLBACK_PATH, CallbackServer

HEALTH_ROUTES = frozenset({("GET", "/health"), ("GET", "/healthz")})
# Signed by Google OIDC (HB-01, ADR-0032): tilo-api's ID token for the connectors audience, checked before the body is
# read. Their forged / missing / wrong-account / wrong-claim / unset-config cases are in test_ADR32_T3_host_routes.py
# (a replayed token is bounded by its expiry and a replayed send is the outbox's idempotent no-op, ADR-0032 HB-01/04).
SIGNED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", f"/internal/meeting-host/{name}") for name in ("send", "status", "disconnect")}
)


def _flip(state: str) -> str:
    return state[:-1] + ("A" if state[-1] != "A" else "B")


def _assert_nothing_happened(env) -> None:
    assert env.google.exchange_calls() == [], "refused before any code is exchanged"
    assert env.store.live_keys() == [], "no token stored"
    assert env.emitted == [], "no event emitted"


def _callback(env, flow, user, *, state):
    code = env.google.issue_code(
        flow.scopes, challenge=flow.query["code_challenge"], redirect_uri=flow.query["redirect_uri"]
    )
    return env.service.handle_callback(user_id=user, state=state, code=code)


# ---------------------------------------------------------------------------------------------------------------
# 1. ConsentService.handle_callback


def test_SEC_08_oauth_positive_control_a_genuine_fresh_callback_connects_once():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    result = finish_flow(env, flow, OWNER)

    assert result.granted_scopes == frozenset({DRIVE_FILE}) and result.card_id == CARD_ID
    assert env.store.live_keys() == [(OWNER, "google_drive")]
    assert len(env.google.exchange_calls()) == 1


@pytest.mark.parametrize(
    "forge",
    [
        lambda flow: fake_secret("state"),  # a state nobody issued
        lambda flow: _flip(flow.state),  # one character off
        lambda flow: flow.state[:-3],  # truncated
        lambda flow: flow.state + "x",  # extended
        lambda flow: flow.state.upper() if flow.state.upper() != flow.state else flow.state.lower(),  # re-cased
        lambda flow: "",  # missing
    ],
    ids=["unissued", "one-char-off", "truncated", "extended", "re-cased", "empty"],
)
def test_SEC_08_oauth_forged_or_missing_state_is_rejected_before_any_exchange_and_stores_nothing(forge):
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    with pytest.raises(ConsentRefused):
        _callback(env, flow, OWNER, state=forge(flow))

    _assert_nothing_happened(env)
    finish_flow(env, flow, OWNER)  # a forgery that never matched did not spend the genuine flow
    assert env.store.live_keys() == [(OWNER, "google_drive")]


def test_SEC_08_oauth_state_presented_for_another_signed_in_person_is_rejected_and_stores_nothing():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])

    with pytest.raises(ConsentRefused):
        _callback(env, flow, OTHER, state=flow.state)  # the owner's state, a different person's session

    _assert_nothing_happened(env)
    assert env.broker.connection_state(OTHER, "google_drive") != "connected"


def test_SEC_08_oauth_state_is_good_for_its_lifetime_and_rejected_one_second_after_with_nothing_stored():
    env = make_env()
    inside = start_flow(env, OWNER, "google_drive", ["write"])
    env.clock.advance(599)
    assert finish_flow(env, inside, OWNER).connector == "google_drive"  # positive control at the edge

    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    env.clock.advance(601)
    with pytest.raises(ConsentRefused):
        _callback(env, flow, OWNER, state=flow.state)
    _assert_nothing_happened(env)


def test_SEC_08_oauth_replayed_callback_is_rejected_and_exchanges_and_stores_nothing_more():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    finish_flow(env, flow, OWNER)
    exchanges, keys, events = len(env.google.exchange_calls()), env.store.live_keys(), list(env.emitted)

    for _ in range(3):
        with pytest.raises(ConsentRefused):
            _callback(env, flow, OWNER, state=flow.state)

    assert len(env.google.exchange_calls()) == exchanges
    assert env.store.live_keys() == keys
    assert env.emitted == events


def test_SEC_08_oauth_replayed_callback_outside_the_window_is_rejected():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    finish_flow(env, flow, OWNER)
    env.clock.advance(3600)

    with pytest.raises(ConsentRefused):
        _callback(env, flow, OWNER, state=flow.state)
    assert len(env.google.exchange_calls()) == 1


def test_SEC_08_oauth_replayed_concurrently_connects_at_most_once():
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    code = env.google.issue_code(
        flow.scopes, challenge=flow.query["code_challenge"], redirect_uri=flow.query["redirect_uri"]
    )
    barrier = threading.Barrier(12)

    def attempt(_: int) -> str:
        barrier.wait()
        try:
            env.service.handle_callback(user_id=OWNER, state=flow.state, code=code)
            return "accepted"
        except ConsentRefused:
            return "refused"

    with ThreadPoolExecutor(12) as pool:
        outcomes = list(pool.map(attempt, range(12)))

    assert outcomes.count("accepted") == 1
    assert len(env.google.exchange_calls()) == 1


@settings(max_examples=60, deadline=None)
@given(junk=st.text(max_size=80))
def test_SEC_08_oauth_property_no_state_that_was_not_issued_is_ever_accepted(junk):
    env = make_env()
    flow = start_flow(env, OWNER, "google_drive", ["write"])
    if junk == flow.state:
        return

    with pytest.raises(ConsentRefused):
        _callback(env, flow, OWNER, state=junk)

    _assert_nothing_happened(env)


# ---------------------------------------------------------------------------------------------------------------
# 2. The loopback callback listener (real sockets, 127.0.0.1 only)


class _Listener:
    """A CallbackServer whose wait() runs in a thread, so the test can play the browser."""

    def __init__(self, state: str) -> None:
        self.server = CallbackServer(expected_state=state, port=0, timeout_s=10.0)
        self.port = self.server.port
        self.result = None
        self.done = threading.Event()
        threading.Thread(target=self._wait, daemon=True).start()

    def _wait(self) -> None:
        try:
            self.result = self.server.wait()
        except Exception:  # noqa: BLE001 - the timeout path is not under test here
            pass
        finally:
            self.done.set()


@pytest.fixture()
def listener():
    made: list[_Listener] = []

    def make(state: str) -> _Listener:
        made.append(_Listener(state))
        return made[-1]

    yield make
    for item in made:
        item.server.close()


def test_SEC_08_loopback_positive_control_the_genuine_redirect_is_accepted_once_then_the_door_closes(listener):
    state, code = fake_secret("state"), fake_secret("code")
    box = listener(state)

    status, _, _ = get_callback(box.port, {"code": code, "state": state})

    assert status == 200
    assert box.done.wait(5) and box.result is not None and box.result.code == code
    end = time.monotonic() + 3
    while not port_is_closed(box.port) and time.monotonic() < end:
        time.sleep(0.05)
    assert port_is_closed(box.port), "after one accepted request nothing listens any more"


@pytest.mark.parametrize(
    "params",
    [
        lambda state: {"code": fake_secret("code"), "state": fake_secret("state")},  # forged state
        lambda state: {"code": fake_secret("code"), "state": _flip(state)},  # tampered state
        lambda state: {"code": fake_secret("code")},  # missing state
        lambda state: {"code": fake_secret("code"), "state": ""},  # empty state
        lambda state: [("code", fake_secret("code")), ("state", state), ("state", _flip(state))],  # doubled state
        lambda state: [("code", fake_secret("code")), ("state", _flip(state)), ("state", state)],  # doubled state
    ],
    ids=["forged", "tampered", "missing", "empty", "doubled-genuine-first", "doubled-forged-first"],
)
def test_SEC_08_loopback_forged_or_unsigned_redirect_is_rejected_and_never_ends_the_wait(listener, params):
    state = fake_secret("state")
    box = listener(state)

    status, _, body = get_callback(box.port, params(state))

    assert status == 400, status
    assert not box.done.wait(0.3), "a rejected request must not end the wait or hand a code on"
    assert box.result is None
    assert body == "Not accepted."
    # and the genuine redirect still works afterwards
    code = fake_secret("code")
    assert get_callback(box.port, {"code": code, "state": state})[0] == 200
    assert box.done.wait(5) and box.result.code == code


def test_SEC_08_loopback_replayed_redirect_is_rejected_after_the_first_is_accepted(listener):
    state = fake_secret("state")
    box = listener(state)
    first = fake_secret("code")
    assert get_callback(box.port, {"code": first, "state": state})[0] == 200
    assert box.done.wait(5)

    try:
        status = get_callback(box.port, {"code": fake_secret("code"), "state": state})[0]
    except OSError:
        status = None  # the listener is already closed: even better

    assert status in (None, 400, 404)
    assert box.result.code == first, "the replayed code never replaced the first"


def test_SEC_08_loopback_request_to_another_path_is_rejected_even_with_the_right_state(listener):
    state = fake_secret("state")
    box = listener(state)

    status, _, _ = get_callback(box.port, {"code": fake_secret("code"), "state": state}, path="/oauth/other")

    assert status == 404
    assert not box.done.wait(0.3)
    assert CALLBACK_PATH == "/oauth/google/callback"


# ---------------------------------------------------------------------------------------------------------------
# 3. Route guard


def test_SEC_08_connectors_app_mounts_no_inbound_route_outside_the_signed_surface_list():
    from tilo_connectors.app import app

    mounted = {(method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods}
    mounted |= {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    unknown = mounted - HEALTH_ROUTES - SIGNED_ROUTES

    assert unknown == set(), (
        f"{sorted(unknown)} is an inbound route with no SEC-08 test: add forged, tampered, missing, expired and "
        "replayed cases for it to this file, then list it in SIGNED_ROUTES"
    )

    def plain(route) -> bool:  # an include_router() entry (newer FastAPI wraps it) is fine when it holds only APIRoutes
        inner = getattr(route, "original_router", None)
        return isinstance(route, APIRoute) or (inner is not None and all(isinstance(r, APIRoute) for r in inner.routes))

    assert all(plain(r) for r in app.routes), "a mounted sub-app or non-API route: list its routes here"
    assert app.openapi_url is None
