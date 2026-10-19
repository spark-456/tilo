"""SEC-15 / SIGNIN (PRD 6 platform row "Firebase Authentication: Google sign-in and anonymous demo sessions", PRD R-06,
PRD supplement SEC-15, BQ-XWORLD-10): the production Firebase ID-token verifier and the Principal it yields.

NEW PUBLIC INTERFACE PINNED HERE (module `tilo_api.firebase_auth`, written beside `tilo_api.appcheck` and reusing its
cache / single-flight / cooldown pattern; none of it exists yet, so every test fails first on the missing module):

    FirebaseIdTokenVerifier(project, *, fetch=<default: Google securetoken JWKS>, clock=time.monotonic, wall=time.time)
        .verify(token: str) -> Mapping[str, Any]      # the verified claims; raises TokenRefused for anything else
    TokenRefused(code)                                 # `.code`: a fixed lower-case word, never token text
    JWKS_URL    == "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    ISSUER_PREFIX == "https://securetoken.google.com/"
    MAX_TOKEN_CHARS                                     # a longer token is refused without being parsed or any fetch
    user_id_for(uid: str) -> str                        # the stable mapping Firebase uid -> contract user_id
    principal_from_claims(claims, *, channel) -> deps.Principal

`fetch` has the same shape as appcheck's: `() -> dict[kid, RSAPublicKey]`. Tests never reach the default fetch (no
network); RSA keys are made at runtime; tokens are assembled at runtime and never committed.

What a verified token means (PRD defaults; each choice is also a BQ row in docs/open-questions.md):
- RS256 only, signature checked against the securetoken keys; `aud` == the Firebase project id (a string, exactly);
  `iss` == "https://securetoken.google.com/<project>" exactly; `sub` a non-empty string of at most 128 characters;
  `exp` in the future; `iat` and `auth_time` present, numbers, not in the future beyond a few seconds of skew.
- `firebase.sign_in_provider` is "google.com" or "anonymous"; nothing else (Tilo never handles passwords, PRD 16.1:
  "password", "custom", "phone", ... are refused).
- A Google sign-in needs `email_verified` true (BQ-SIGNIN-2). An anonymous token has no email.
- Principal: user_id from the uid, role "owner" (each person owns their own worlds, as the dev principal does),
  `channel` as given, `full_session` True ONLY for a Google sign-in (BQ-XWORLD-10: anonymous demo sessions stay bound
  to their own world), set by the server and never read from anything in a request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading

import pytest
from _signin_lib import NOW, PROJECT, FailingFetch, Fetch, _b64, _claims, _key, _token
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import deps, firebase_auth

USER_ID = re.compile(r"^u_[0-9A-Za-z_]{1,48}$")  # contracts/common.schema.json#/$defs/user_id


@pytest.fixture(scope="module")
def signer() -> rsa.RSAPrivateKey:
    return _key()


@pytest.fixture(scope="module")
def other_signer() -> rsa.RSAPrivateKey:
    return _key()


def _verifier(fetch, now: float = NOW) -> firebase_auth.FirebaseIdTokenVerifier:
    return firebase_auth.FirebaseIdTokenVerifier(PROJECT, fetch=fetch, clock=lambda: 0.0, wall=lambda: now)


# --- constants -------------------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_verifier_uses_the_securetoken_keys_and_issuer():
    assert (
        firebase_auth.JWKS_URL
        == "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    )
    assert firebase_auth.ISSUER_PREFIX == "https://securetoken.google.com/"
    assert 4096 <= firebase_auth.MAX_TOKEN_CHARS <= 16384


# --- accepted --------------------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_verifier_accepts_a_genuine_google_sign_in_token(signer):
    claims = _verifier(Fetch({"k1": signer.public_key()})).verify(_token(signer))
    assert claims["sub"] == _claims()["sub"]
    assert claims["firebase"]["sign_in_provider"] == "google.com"


def test_SEC_15_SIGNIN_verifier_accepts_a_genuine_anonymous_token(signer):
    claims = _verifier(Fetch({"k1": signer.public_key()})).verify(_token(signer, provider="anonymous"))
    assert claims["firebase"]["sign_in_provider"] == "anonymous"
    assert "email" not in claims


def test_SEC_15_SIGNIN_verifier_accepts_a_long_but_legitimate_token(signer):
    token = _token(signer, name="N" * 1500)
    assert 2500 < len(token) <= firebase_auth.MAX_TOKEN_CHARS
    assert _verifier(Fetch({"k1": signer.public_key()})).verify(token)["name"] == "N" * 1500


def test_SEC_15_SIGNIN_keys_are_cached_so_two_tokens_cost_one_fetch(signer):
    fetch = Fetch({"k1": signer.public_key()})
    verifier = _verifier(fetch)
    verifier.verify(_token(signer))
    verifier.verify(_token(signer, provider="anonymous"))
    assert fetch.calls == 1


def test_SEC_15_SIGNIN_a_rotated_key_is_picked_up_but_unknown_key_ids_cannot_hammer_the_endpoint(signer, other_signer):
    fetch = Fetch({"k1": signer.public_key()})
    verifier = _verifier(fetch)
    verifier.verify(_token(signer))
    for _ in range(6):  # a flood of tokens naming a key id nobody has
        with pytest.raises(firebase_auth.TokenRefused):
            verifier.verify(_token(other_signer, kid="not-a-real-kid"))
    assert fetch.calls <= 2, "an unknown key id may cause one refetch, not one per token"


def test_SEC_15_SIGNIN_single_flight_many_concurrent_first_tokens_cost_one_fetch(signer):
    release = threading.Event()
    calls = 0

    def slow_fetch():
        nonlocal calls
        calls += 1
        release.wait(5)
        return {"k1": signer.public_key()}

    verifier = _verifier(slow_fetch)
    token = _token(signer)
    outcomes: list[str] = []

    def worker():
        try:
            verifier.verify(token)
            outcomes.append("ok")
        except firebase_auth.TokenRefused:
            outcomes.append("refused")  # a caller that finds a refresh running may be refused: fail closed
        except Exception as exc:  # noqa: BLE001
            outcomes.append(f"BAD {type(exc).__name__}")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    release.set()
    for t in threads:
        t.join(10)
    assert calls == 1
    assert len(outcomes) == 8 and not [o for o in outcomes if o.startswith("BAD")], outcomes
    assert "ok" in outcomes


def test_SEC_15_SIGNIN_unavailable_keys_fail_closed_and_a_dead_endpoint_is_not_hammered(signer):
    fetch = FailingFetch()
    verifier = _verifier(fetch)
    for _ in range(5):
        # appcheck's pattern lets the first failing fetch's own error through and refuses the rest with
        # `keys_unavailable`; either way nothing is accepted, and the resolver turns any failure into a 401
        # (test_SEC_15_SIGNIN_principal.py). So only "an exception, never a pass" is pinned here.
        with pytest.raises(Exception):  # noqa: B017, PT011
            verifier.verify(_token(signer))
    assert fetch.calls == 1, "after a failed fetch no other starts inside the cooldown"


def test_SEC_15_SIGNIN_a_fetch_that_returns_no_usable_key_refuses(signer):
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(Fetch({})).verify(_token(signer))


# --- refused: wrong algorithm ----------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_alg_none_is_refused_before_any_key_is_fetched(signer):
    fetch = Fetch({"k1": signer.public_key()})
    head = _b64(json.dumps({"alg": "none", "kid": "k1"}).encode())
    body = _b64(json.dumps(_claims()).encode())
    for token in (f"{head}.{body}.", f"{head}.{body}.{_b64(b'x')}"):
        with pytest.raises(firebase_auth.TokenRefused):
            _verifier(fetch).verify(token)
    assert fetch.calls == 0


@pytest.mark.parametrize("alg", ["HS256", "HS384", "RS384", "RS512", "ES256", "PS256", "none", "None", "", None, 256])
def test_SEC_15_SIGNIN_only_rs256_is_accepted(signer, alg):
    fetch = Fetch({"k1": signer.public_key()})
    head = _b64(json.dumps({"alg": alg, "kid": "k1"}).encode())
    body = _b64(json.dumps(_claims()).encode())
    signing = f"{head}.{body}"
    signature = signer.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(fetch).verify(f"{signing}.{_b64(signature)}")
    assert fetch.calls == 0


def test_SEC_15_SIGNIN_hs256_signed_with_the_public_key_as_the_secret_is_refused(signer):
    """The classic algorithm-confusion attack: HMAC the token with the PEM of the public key."""
    pem = signer.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    head = _b64(json.dumps({"alg": "HS256", "kid": "k1"}).encode())
    body = _b64(json.dumps(_claims()).encode())
    signature = hmac.new(pem, f"{head}.{body}".encode(), hashlib.sha256).digest()
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(Fetch({"k1": signer.public_key()})).verify(f"{head}.{body}.{_b64(signature)}")


# --- refused: wrong signer, kid, claims ------------------------------------------------------------------------


def test_SEC_15_SIGNIN_a_token_signed_by_another_key_is_refused(signer, other_signer):
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(Fetch({"k1": signer.public_key()})).verify(_token(other_signer))


def test_SEC_15_SIGNIN_an_unknown_key_id_is_refused(signer):
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(Fetch({"k1": signer.public_key()})).verify(_token(signer, kid="k2"))


@pytest.mark.parametrize("kid", [None, "", 7, ["k1"]])
def test_SEC_15_SIGNIN_a_missing_or_malformed_key_id_is_refused(signer, kid):
    head = _b64(json.dumps({"alg": "RS256", "kid": kid}).encode())
    body = _b64(json.dumps(_claims()).encode())
    signature = signer.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(Fetch({"k1": signer.public_key()})).verify(f"{head}.{body}.{_b64(signature)}")


BAD_CLAIMS = {
    "aud_other_project": {"aud": "someone-elses-project"},
    "aud_list_with_project": {"aud": [PROJECT, "other"]},
    "aud_missing": {"aud": ...},
    "aud_number": {"aud": 7},
    "iss_other_project": {"iss": f"https://securetoken.google.com/{PROJECT}-evil"},
    "iss_prefix_only": {"iss": "https://securetoken.google.com/"},
    "iss_trailing_slash": {"iss": f"https://securetoken.google.com/{PROJECT}/"},
    "iss_app_check": {"iss": f"https://firebaseappcheck.googleapis.com/{PROJECT}"},
    "iss_other_host": {"iss": f"https://accounts.google.com/{PROJECT}"},
    "iss_missing": {"iss": ...},
    "expired": {"exp": NOW - 60},
    "exp_missing": {"exp": ...},
    "exp_string": {"exp": "soon"},
    "exp_bool": {"exp": True},
    "iat_in_the_future": {"iat": NOW + 600},
    "iat_missing": {"iat": ...},
    "iat_string": {"iat": "now"},
    "auth_time_in_the_future": {"auth_time": NOW + 600},
    "auth_time_missing": {"auth_time": ...},
    "auth_time_string": {"auth_time": "earlier"},
    "nbf_in_the_future": {"nbf": NOW + 600},
    "sub_missing": {"sub": ...},
    "sub_empty": {"sub": ""},
    "sub_number": {"sub": 7},
    "sub_list": {"sub": ["a"]},
    "sub_too_long": {"sub": "u" * 129},
    "provider_password": {"firebase": {"sign_in_provider": "password"}},
    "provider_custom": {"firebase": {"sign_in_provider": "custom"}},
    "provider_phone": {"firebase": {"sign_in_provider": "phone"}},
    "provider_github": {"firebase": {"sign_in_provider": "github.com"}},
    "provider_missing": {"firebase": {}},
    "provider_number": {"firebase": {"sign_in_provider": 1}},
    "firebase_claim_missing": {"firebase": ...},
    "firebase_claim_a_string": {"firebase": "google.com"},
    "google_email_not_verified": {"email_verified": False},
    "google_email_verified_missing": {"email_verified": ...},
    "google_email_verified_string": {"email_verified": "true"},
}


@pytest.mark.parametrize("name", sorted(BAD_CLAIMS))
def test_SEC_15_SIGNIN_a_validly_signed_token_with_a_wrong_claim_is_refused(signer, name):
    verifier = _verifier(Fetch({"k1": signer.public_key()}))
    with pytest.raises(firebase_auth.TokenRefused):
        verifier.verify(_token(signer, **BAD_CLAIMS[name]))


def test_SEC_15_SIGNIN_a_token_that_cannot_pass_its_claims_is_refused_before_any_key_is_fetched(signer):
    fetch = Fetch({"k1": signer.public_key()})
    verifier = _verifier(fetch)
    for name in ("aud_other_project", "iss_other_project", "iss_app_check", "sub_empty"):
        with pytest.raises(firebase_auth.TokenRefused):
            verifier.verify(_token(signer, **BAD_CLAIMS[name]))
    assert fetch.calls == 0


def test_SEC_15_SIGNIN_the_project_is_the_one_the_verifier_was_made_for(signer):
    other = firebase_auth.FirebaseIdTokenVerifier(
        "another-project", fetch=Fetch({"k1": signer.public_key()}), clock=lambda: 0.0, wall=lambda: NOW
    )
    with pytest.raises(firebase_auth.TokenRefused):
        other.verify(_token(signer))


def test_SEC_15_SIGNIN_an_anonymous_token_needs_no_email_or_email_verified_claim(signer):
    claims = _verifier(Fetch({"k1": signer.public_key()})).verify(_token(signer, provider="anonymous"))
    assert "email" not in claims and "email_verified" not in claims


# --- refused: not a JWT, too long ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "",
        " ",
        "abc",
        "a.b",
        "a.b.c.d",
        "...",
        "a..c",
        "é.é.é",
        "Bearer a.b.c",
        "{}",
        "null",
        "\x00.\x00.\x00",
        "a.b.c\n",
    ],
)
def test_SEC_15_SIGNIN_things_that_are_not_a_jwt_are_refused_without_any_fetch(token):
    fetch = Fetch({})
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(fetch).verify(token)
    assert fetch.calls == 0


def test_SEC_15_SIGNIN_header_or_claims_that_are_not_json_objects_are_refused_without_any_fetch(signer):
    fetch = Fetch({"k1": signer.public_key()})
    for head, body in [
        (_b64(b"[]"), _b64(json.dumps(_claims()).encode())),
        (_b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode()), _b64(b"[]")),
        (_b64(b"not json"), _b64(b"not json")),
        (_b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode()), _b64(b"\xff\xfe")),
    ]:
        with pytest.raises(firebase_auth.TokenRefused):
            _verifier(fetch).verify(f"{head}.{body}.{_b64(b'sig')}")
    assert fetch.calls == 0


def test_SEC_15_SIGNIN_a_too_long_token_is_refused_without_being_parsed_or_any_fetch(signer):
    fetch = Fetch({"k1": signer.public_key()})
    huge = _token(signer, name="N" * (firebase_auth.MAX_TOKEN_CHARS + 10))
    assert len(huge) > firebase_auth.MAX_TOKEN_CHARS
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(fetch).verify(huge)
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(fetch).verify("x" * (firebase_auth.MAX_TOKEN_CHARS + 1))
    assert fetch.calls == 0


def test_SEC_15_SIGNIN_a_refusal_code_never_carries_text_from_the_token(signer):
    marker = "SECRETMARKER" + "Z9" * 6
    for token in (_token(signer, aud=marker), _token(signer, sub=...), _token(signer, kid=marker), marker + ".b.c"):
        with pytest.raises(firebase_auth.TokenRefused) as info:
            _verifier(Fetch({"k1": signer.public_key()})).verify(token)
        assert re.fullmatch(r"[a-z_]{1,40}", info.value.code), info.value.code
        assert marker not in str(info.value) and marker not in repr(info.value)


# --- property tests --------------------------------------------------------------------------------------------


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(token=st.text(max_size=6000))
def test_SEC_15_SIGNIN_property_no_string_makes_the_verifier_raise_anything_but_a_refusal(token):
    verifier = _verifier(Fetch({}))
    try:
        verifier.verify(token)
    except firebase_auth.TokenRefused as exc:
        assert re.fullmatch(r"[a-z_]{1,40}", exc.code)
    else:  # pragma: no cover
        pytest.fail("a random string was accepted as a Firebase ID token")


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    parts=st.lists(
        st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_", max_size=200),
        min_size=1,
        max_size=5,
    ),
)
def test_SEC_15_SIGNIN_property_dotted_base64_noise_is_always_refused(parts, signer):
    fetch = Fetch({"k1": signer.public_key()})
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(fetch).verify(".".join(parts))


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(position=st.integers(min_value=0, max_value=10_000), replacement=st.sampled_from("AZaz09-_"))
def test_SEC_15_SIGNIN_property_changing_one_character_of_a_genuine_token_is_refused(position, replacement, signer):
    token = _token(signer)
    head, body, signature = token.split(".")
    segment = (head, body)[position % 2]  # header or claims: a changed character changes the signed bytes
    index = position % (len(segment) - 1)  # not the last character: its low bits may be base64 padding
    if segment[index] == replacement:
        return
    changed = segment[:index] + replacement + segment[index + 1 :]
    forged = ".".join((changed, body, signature) if segment is head else (head, changed, signature))
    with pytest.raises(firebase_auth.TokenRefused):
        _verifier(Fetch({"k1": signer.public_key()})).verify(forged)


# --- the Principal ---------------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_a_google_sign_in_is_a_full_session_owner_on_the_given_channel():
    for channel in ("web", "mobile_web"):
        principal = firebase_auth.principal_from_claims(_claims("google.com"), channel=channel)
        assert isinstance(principal, deps.Principal)
        assert principal.user_id == firebase_auth.user_id_for(_claims()["sub"])
        assert principal.role == "owner"
        assert principal.channel == channel
        assert principal.full_session is True


def test_SEC_15_SIGNIN_an_anonymous_demo_session_is_never_a_full_session():
    principal = firebase_auth.principal_from_claims(_claims("anonymous"), channel="web")
    assert principal.full_session is False
    assert principal.role == "owner"
    assert principal.user_id == firebase_auth.user_id_for(_claims("anonymous")["sub"])


def test_SEC_15_SIGNIN_the_principal_never_carries_the_email_or_the_token_claims():
    principal = firebase_auth.principal_from_claims(_claims("google.com"), channel="web")
    text = repr(principal)
    assert "person@example.test" not in text and "A Person" not in text


@settings(max_examples=100, deadline=None)
@given(provider=st.text(max_size=30) | st.sampled_from(["google.com", "anonymous"]))
def test_SEC_15_SIGNIN_property_only_google_com_makes_a_full_session(provider):
    claims = _claims("google.com", firebase={"sign_in_provider": provider})
    principal = firebase_auth.principal_from_claims(claims, channel="web")
    assert principal.full_session is (provider == "google.com")


UID = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),  # Firebase uids: up to 128 printable characters
    min_size=1,
    max_size=128,
)


@settings(max_examples=200, deadline=None)
@given(uid=UID)
def test_SEC_15_SIGNIN_property_every_uid_maps_to_a_valid_stable_user_id(uid):
    mapped = firebase_auth.user_id_for(uid)
    assert USER_ID.fullmatch(mapped), mapped
    assert firebase_auth.user_id_for(uid) == mapped


@settings(max_examples=60, deadline=None)
@given(uids=st.sets(UID, min_size=2, max_size=25))
def test_SEC_15_SIGNIN_property_different_uids_never_share_a_user_id(uids):
    mapped = {firebase_auth.user_id_for(u) for u in uids}
    assert len(mapped) == len(uids), "two people must never be the same user"


def test_SEC_15_SIGNIN_user_id_for_does_not_collide_with_the_dev_owner():
    from tilo_api import dev  # noqa: PLC0415

    for uid in ("dev_owner", "u_dev_owner", "dev-owner", "devowner", "DEV_OWNER"):
        assert firebase_auth.user_id_for(uid) != dev.DEV_OWNER
