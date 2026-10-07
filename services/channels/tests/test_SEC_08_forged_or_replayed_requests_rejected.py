"""SEC-08 (PRD 16.4: "Signed webhooks and signed email links" -> "Forged or replayed requests rejected";
PRD 16.2 "Spoofed WhatsApp commands" / "Forwarded email action links: signed, single-use, 24-hour links; gates need
sign-in"; PRD 6.3 "public ingress for verified webhooks only").

Acceptance claim, tested here for the signed inbound surfaces that live in `tilo-channels`: a forged, tampered,
unsigned, expired or replayed request is rejected AND causes no side effect; a correctly signed, fresh request is
accepted (positive control, so a verifier that rejects everything cannot pass).

Signed inbound surfaces of tilo-channels, enumerated from the code (grep of `hmac`, `compare_digest`, OIDC and route
decorators under services/channels/src, 2026-10-07):

1. Signed email action links: `tilo_channels.links.LinkService.redeem` (HMAC-SHA256 token, 24 h, single use). It is
   a library verifier: no HTTP route mounts it yet (the app has /health and /healthz only).
2. Gmail Pub/Sub push: `tilo_channels.gmail_watch.GmailPushEndpoint.receive` (Google-signed OIDC bearer token,
   audience, issuer, service account and email_verified checked, then the body parsed). Also a library endpoint with
   no mounted route yet. Replay protection is the watcher's: cursor plus the per-message `DedupeStore` claim.
3. Route guard: `tilo_channels.app` mounts no other route. WhatsApp's webhook (FR-CHN-02) left scope with ADR-0019,
   so there is no WhatsApp receiver to test. The guard below fails when any new non-health route appears, so a new
   webhook cannot ship without being added to `SIGNED_ROUTES` and given its own forged/replayed tests here.

Other services' signed surfaces (the Cloud Scheduler ticks, the OAuth callback state) have their own SEC-08 files in
services/api/tests, services/harness/tests and services/connectors/tests.

"No side effect" is observed through the doubles that stand for the effect: the link `NonceStore` (a refused link
burns no nonce, so it neither blocks the owner nor counts as used), the Gmail mailbox (no history read), the triage
step (never called), the event writer (nothing emitted).

Defaults where the PRD is silent (PRD 10.3 / 16.2 say "signed, single-use, 24-hour links"; they do not name a wire
format or a Pub/Sub replay window):
- a refused link never consumes its nonce (FR-CHN-07 D4), so "no side effect" for a link means `consumed` is empty;
- a replayed Pub/Sub push inside the token's life is not an error (Pub/Sub redelivers by design): it is accepted and
  processed at most once per message; a replay once the token has expired is rejected (PRD 16.2 reads "replayed
  webhooks are rejected" as the signed token's lifetime plus idempotent processing, FR-CHN-02 "duplicates processed
  once").
No real secrets: signing keys come from `secrets.token_bytes`, tokens from the fakes, at run time.
"""

from __future__ import annotations

import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from _chn08_lib import (
    ADDRESS,
    AUDIENCE,
    PUSH_SA,
    RIYA,
    bearer,
    drop,
    push_body,
)
from _chn08_lib import make_rig as make_push_rig
from _chn_links_lib import (
    ALICE,
    BASE_URL,
    BOB,
    GATE,
    Q1,
    TTL,
    FakeNonceStore,
    fresh_key,
    links,
    make_rig,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Every route tilo-channels may expose without a person's session. Empty until a webhook route is mounted; add the
# route here only together with forged / tampered / missing / expired / replayed tests for it in this file.
SIGNED_ROUTES: frozenset[tuple[str, str]] = frozenset()
HEALTH_ROUTES = frozenset({("GET", "/health"), ("GET", "/healthz")})

SIGNATURE_REFUSALS = {"malformed", "bad_signature", "unknown_key"}


# ---------------------------------------------------------------------------------------------------------------
# Helpers


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _split(token: str) -> tuple[str, dict[str, Any], str]:
    kid, body, sig = token.split(".")
    return kid, json.loads(_b64d(body)), sig


def _with_claims(token: str, **changes: Any) -> str:
    """The same token with some claims changed and the ORIGINAL signature kept: a tampered body."""
    kid, claims, sig = _split(token)
    claims.update(changes)
    body = _b64e(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    return f"{kid}.{body}.{sig}"


def _flip_middle(text: str) -> str:
    i = len(text) // 2
    return text[:i] + ("B" if text[i] != "B" else "C") + text[i + 1 :]


def _refused(rig: Any, token: str, link: Any, **over: Any) -> str:
    L = links()
    with pytest.raises(L.LinkRefused) as info:
        rig.redeem(link, token=token, **over)
    return str(info.value.reason)


def _assert_pristine(rig: Any, link: Any) -> None:
    """No side effect: nothing consumed, and the owner's genuine link still redeems exactly once."""
    assert rig.store.consumed == {}, "a refused link must not burn the nonce"
    redemption = rig.redeem(link)
    assert redemption.card_id == link.card_id and redemption.user_id == link.user_id
    assert list(rig.store.consumed) == [link.nonce]


# ---------------------------------------------------------------------------------------------------------------
# 1. Signed email action links


def test_SEC_08_link_positive_control_a_fresh_signed_link_is_accepted_exactly_once():
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "answer", "per_kwh")

    redemption = rig.redeem(link)

    assert (redemption.card_id, redemption.user_id, redemption.action, redemption.option) == (
        Q1,
        ALICE,
        "answer",
        "per_kwh",
    )
    assert redemption.authn == "link" and redemption.requires_sign_in is False
    assert list(rig.store.consumed) == [link.nonce]


def test_SEC_08_link_signed_with_another_key_is_rejected_and_causes_no_side_effect():
    L = links()
    rig = make_rig()
    link = rig.issue()
    attacker = L.LinkService(
        keys=L.KeyRing(keys={rig.kid: fresh_key()}, active=rig.kid),  # the right key id, the wrong key
        nonces=FakeNonceStore(),
        clock=rig.clock,
        cards=rig.book,
        base_url=BASE_URL,
    )
    forged = attacker.issue(card_id=Q1, user_id=ALICE, action="answer", option="per_pack")

    assert _refused(rig, forged.token, link, card_id=Q1) == "bad_signature"
    _assert_pristine(rig, link)


def test_SEC_08_link_signed_with_an_unknown_key_id_is_rejected_and_causes_no_side_effect():
    L = links()
    rig = make_rig()
    link = rig.issue()
    attacker = L.LinkService(
        keys=L.KeyRing(keys={"evil": fresh_key()}, active="evil"),
        nonces=FakeNonceStore(),
        clock=rig.clock,
        cards=rig.book,
        base_url=BASE_URL,
    )
    forged = attacker.issue(card_id=Q1, user_id=ALICE, action="answer", option="per_kwh")

    assert _refused(rig, forged.token, link) == "unknown_key"
    _assert_pristine(rig, link)


def test_SEC_08_link_with_a_corrupted_signature_is_rejected_and_causes_no_side_effect():
    rig = make_rig()
    link = rig.issue()
    kid, body, sig = link.token.split(".")

    assert _refused(rig, f"{kid}.{body}.{_flip_middle(sig)}", link) in SIGNATURE_REFUSALS
    _assert_pristine(rig, link)


TAMPERS = {
    "option swapped": lambda link: {"o": "per_pack"},
    "card swapped": lambda link: {"c": "01J8Z3K4M5N6P7Q8R9S0T1V2W6"},
    "user swapped (forwarded to another person)": lambda link: {"u": BOB},
    "action upgraded to answer": lambda link: {"a": "answer", "o": "per_kwh"},
    "expiry pushed out a year": lambda link: {"e": int(link.expires_at.timestamp()) + 365 * 86400},
    "nonce replaced": lambda link: {"n": "n" * 22},
}


@pytest.mark.parametrize("what", sorted(TAMPERS))
def test_SEC_08_link_with_a_tampered_body_is_rejected_and_causes_no_side_effect(what):
    rig = make_rig()
    link = rig.issue(Q1, ALICE, "open", None) if what.startswith("action") else rig.issue()
    tampered = _with_claims(link.token, **TAMPERS[what](link))
    assert tampered != link.token

    assert _refused(rig, tampered, link) == "bad_signature"
    _assert_pristine(rig, link)


@pytest.mark.parametrize(
    "unsigned",
    [
        lambda token: token.rsplit(".", 1)[0],  # no signature part
        lambda token: token.rsplit(".", 1)[0] + ".",  # empty signature
        lambda token: "",
        lambda token: token.split(".")[1],  # the body alone
        lambda token: token.split(".")[0] + "." + token.split(".")[1] + ".A",  # a signature of one byte
    ],
    ids=["no-sig-part", "empty-sig", "empty-token", "body-only", "one-byte-sig"],
)
def test_SEC_08_link_with_a_missing_signature_is_rejected_and_causes_no_side_effect(unsigned):
    rig = make_rig()
    link = rig.issue()

    assert _refused(rig, unsigned(link.token), link) in SIGNATURE_REFUSALS
    _assert_pristine(rig, link)


def test_SEC_08_link_with_no_token_at_all_is_rejected():
    L = links()
    rig = make_rig()
    link = rig.issue()
    for nothing in (None, 0, b"", [], {}):
        with pytest.raises(L.LinkRefused):
            rig.service.redeem(nothing, card_id=link.card_id, action=link.action)
    _assert_pristine(rig, link)


def test_SEC_08_link_is_accepted_up_to_24_hours_and_rejected_after_without_side_effect():
    rig = make_rig()
    inside = rig.issue()
    rig.clock.advance(seconds=TTL.total_seconds() - 1)  # 23:59:59
    assert rig.redeem(inside).card_id == Q1  # positive control at the edge of the window

    rig = make_rig()
    link = rig.issue()
    rig.clock.advance(seconds=TTL.total_seconds() + 1)  # 24:00:01
    assert _refused(rig, link.token, link) == "expired"
    assert rig.store.consumed == {}, "an expired link burns nothing"


def test_SEC_08_link_replayed_is_rejected_and_the_second_use_has_no_side_effect():
    rig = make_rig()
    link = rig.issue()
    rig.redeem(link)
    consumed_after_first = dict(rig.store.consumed)

    assert _refused(rig, link.token, link) == "used"
    assert rig.store.consumed == consumed_after_first, "the replay changed the nonce table"


def test_SEC_08_link_replayed_on_another_instance_sharing_the_nonce_store_is_rejected():
    rig = make_rig()
    link = rig.issue()
    rig.redeem(link)
    other_instance = rig.new_service()

    with pytest.raises(links().LinkRefused) as info:
        rig.redeem(link, service=other_instance)
    assert info.value.reason == "used"


def test_SEC_08_link_replayed_outside_the_window_is_rejected_whether_used_or_not():
    rig = make_rig()
    link = rig.issue()
    rig.redeem(link)
    rig.clock.advance(seconds=TTL.total_seconds() + 3600)

    assert _refused(rig, link.token, link) in {"expired", "used"}
    unused = rig.issue(Q1, ALICE, "answer", "per_pack")  # issued at the later time, then aged out
    rig.clock.advance(seconds=TTL.total_seconds() + 3600)
    assert _refused(rig, unused.token, unused) == "expired"
    assert list(rig.store.consumed) == [link.nonce]


def test_SEC_08_link_replayed_concurrently_is_accepted_at_most_once():
    rig = make_rig()
    link = rig.issue()
    barrier = threading.Barrier(16)

    def attempt(_: int) -> str:
        barrier.wait()
        try:
            rig.redeem(link)
            return "accepted"
        except links().LinkRefused as exc:
            return exc.reason

    with ThreadPoolExecutor(16) as pool:
        outcomes = list(pool.map(attempt, range(16)))

    assert outcomes.count("accepted") == 1
    assert set(outcomes) - {"accepted"} == {"used"}


def test_SEC_08_link_a_possessed_signed_link_never_answers_a_gate():
    L = links()
    rig = make_rig()
    with pytest.raises(L.LinkRefused) as info:
        rig.issue(GATE, ALICE, "answer", "approve")
    assert info.value.reason == "not_allowed"  # nothing signed exists for it, so nothing can be replayed
    opened = rig.redeem(rig.issue(GATE, ALICE, "open", None))
    assert opened.requires_sign_in is True and opened.authn == "link"


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data())
def test_SEC_08_link_property_no_single_character_change_to_a_token_is_ever_accepted(data):
    rig = make_rig()
    link = rig.issue()
    token = link.token
    i = data.draw(st.integers(0, len(token) - 1))
    c = data.draw(st.characters(min_codepoint=33, max_codepoint=126).filter(lambda ch: ch != token[i]))
    mutated = token[:i] + c + token[i + 1 :]

    with pytest.raises(links().LinkRefused):
        rig.redeem(link, token=mutated)

    assert rig.store.consumed == {}


# ---------------------------------------------------------------------------------------------------------------
# 2. Gmail Pub/Sub push (Google-signed OIDC token)


def _pushed_nothing(rig: Any) -> None:
    assert rig.triage.calls == [], "no triage ran"
    assert rig.mailbox.calls_of("list_history", RIYA) == [], "no mailbox history was read"
    assert rig.events.parts == [], "nothing was emitted"


def _push_rig() -> Any:
    rig = make_push_rig()
    rig.watcher.start(RIYA)
    rig.mailbox.calls.clear()  # forget start()'s own calls
    return rig


def test_SEC_08_push_positive_control_a_correctly_signed_fresh_push_is_accepted_and_triaged_once():
    rig = _push_rig()
    mail = rig.mailbox.deliver(RIYA)

    response = rig.endpoint.receive(bearer(rig.verifier.issue()), push_body(ADDRESS[RIYA], mail.history_id))

    assert 200 <= response.status < 300
    assert rig.triage.ids(RIYA) == [mail.message_id]


FORGED_PUSH_HEADERS = {
    "no Authorization header": lambda rig: {"Content-Type": "application/json"},
    "empty bearer": lambda rig: {"Authorization": "Bearer "},
    "basic instead of bearer": lambda rig: {"Authorization": "Basic dXNlcjpwYXNz"},
    "token never issued (forged)": lambda rig: bearer("fake-oidc-forged-" + "x" * 24),
    "valid token with a corrupted character": lambda rig: bearer(_flip_middle(rig.verifier.issue())),
    "valid token with a truncated tail": lambda rig: bearer(rig.verifier.issue()[:-4]),
}


@pytest.mark.parametrize("what", sorted(FORGED_PUSH_HEADERS))
def test_SEC_08_push_forged_or_unsigned_request_is_rejected_and_causes_no_side_effect(what):
    rig = _push_rig()
    mail = rig.mailbox.deliver(RIYA)

    response = rig.endpoint.receive(FORGED_PUSH_HEADERS[what](rig), push_body(ADDRESS[RIYA], mail.history_id))

    assert response.status in (401, 403), what
    assert len(response.body) <= 64
    _pushed_nothing(rig)


CLAIM_FORGERIES = {
    "another audience": {"aud": "https://evil.example.net/gmail/push"},
    "audience with a suffix": {"aud": AUDIENCE + "/x"},
    "no audience": {"aud": drop()},
    "another issuer": {"iss": "https://evil.example.net"},
    "another service account": {"email": "attacker@demo-tilo.iam.gserviceaccount.com"},
    "service account of another project": {"email": PUSH_SA.replace("demo-tilo", "other-project")},
    "email not verified": {"email_verified": False},
    "email_verified missing": {"email_verified": drop()},
}


@pytest.mark.parametrize("what", sorted(CLAIM_FORGERIES))
def test_SEC_08_push_with_forged_claims_is_rejected_and_causes_no_side_effect(what):
    rig = _push_rig()
    mail = rig.mailbox.deliver(RIYA)
    token = rig.verifier.issue(**CLAIM_FORGERIES[what])  # signed, but not by who the endpoint expects

    response = rig.endpoint.receive(bearer(token), push_body(ADDRESS[RIYA], mail.history_id))

    assert response.status in (401, 403), what
    _pushed_nothing(rig)


def test_SEC_08_push_expired_token_is_rejected_and_causes_no_side_effect():
    rig = _push_rig()
    mail = rig.mailbox.deliver(RIYA)
    token = rig.verifier.issue()
    rig.clock.advance(3601)  # the token lives one hour

    response = rig.endpoint.receive(bearer(token), push_body(ADDRESS[RIYA], mail.history_id))

    assert response.status in (401, 403)
    _pushed_nothing(rig)


def test_SEC_08_push_body_is_not_read_before_the_signature_is_checked():
    rig = _push_rig()

    unsigned = rig.endpoint.receive({}, b"{not json")
    signed_garbage = rig.endpoint.receive(bearer(rig.verifier.issue()), b"{not json")

    assert unsigned.status == 401, "an unsigned request is refused as unauthenticated, not as malformed"
    assert signed_garbage.status == 400
    _pushed_nothing(rig)


def test_SEC_08_push_replayed_request_is_processed_at_most_once_and_a_late_replay_is_rejected():
    rig = _push_rig()
    mail = rig.mailbox.deliver(RIYA)
    body = push_body(ADDRESS[RIYA], mail.history_id)
    token = rig.verifier.issue()

    assert 200 <= rig.endpoint.receive(bearer(token), body).status < 300
    for _ in range(3):  # Pub/Sub redelivery and an attacker replaying the captured request, same token
        rig.endpoint.receive(bearer(token), body)
    assert rig.triage.ids(RIYA) == [mail.message_id], "the message was triaged once"

    restarted = rig.new_watcher()  # another instance, same stores
    restarted.on_push(RIYA, str(mail.history_id))
    assert rig.triage.ids(RIYA) == [mail.message_id]

    rig.clock.advance(3601)  # the captured token is now outside its window
    late = rig.endpoint.receive(bearer(token), body)
    assert late.status in (401, 403)
    assert rig.triage.ids(RIYA) == [mail.message_id]


def test_SEC_08_push_replayed_concurrently_triages_each_message_once():
    rig = _push_rig()
    mail = rig.mailbox.deliver(RIYA)
    body = push_body(ADDRESS[RIYA], mail.history_id)
    tokens = [rig.verifier.issue() for _ in range(8)]
    barrier = threading.Barrier(8)

    def go(token: str) -> int:
        barrier.wait()
        return rig.endpoint.receive(bearer(token), body).status

    with ThreadPoolExecutor(8) as pool:
        statuses = list(pool.map(go, tokens))

    assert all(200 <= s < 300 for s in statuses)
    assert rig.triage.ids(RIYA) == [mail.message_id]


# ---------------------------------------------------------------------------------------------------------------
# 3. Route guard: no unsigned inbound route exists in tilo-channels


def test_SEC_08_channels_app_mounts_no_inbound_route_that_is_not_in_the_signed_surface_list():
    from fastapi.routing import APIRoute
    from tilo_channels.app import app

    mounted = {(method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods}
    # FastAPI 0.14x wraps included routers lazily, and a route can be left out of the schema: read both views.
    mounted |= {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops}
    unknown = mounted - HEALTH_ROUTES - SIGNED_ROUTES

    assert unknown == set(), (
        f"{sorted(unknown)} is an inbound route with no SEC-08 test: add forged, tampered, missing, expired and "
        "replayed cases for it to this file, then list it in SIGNED_ROUTES"
    )
    assert all(isinstance(r, APIRoute) for r in app.routes), "a mounted router or sub-app: list its routes here"
    assert app.openapi_url is None, "the route list is not published to strangers (issue #411)"
