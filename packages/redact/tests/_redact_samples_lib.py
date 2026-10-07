"""Fake secrets for the FR-MEM-05 / SEC-14 tests. Every one is assembled at runtime from pieces (CLAUDE.md hard rule:
the repo secret scan runs on test files), so no literal in this tree is a secret. `build(kind, tail)` gives the text
and the exact strings that must not survive redaction; `tail` is alphanumeric, 64 to 80 characters."""

from __future__ import annotations

import base64
import importlib.util
import json
import re
import string
import textwrap
from pathlib import Path
from typing import NamedTuple

from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("secret_scan_under_test", REPO_ROOT / "scripts" / "secret_scan.py")
assert _spec is not None and _spec.loader is not None
SECRET_SCAN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SECRET_SCAN)

ALNUM = string.ascii_letters + string.digits
TAIL = st.text(alphabet=ALNUM, min_size=64, max_size=80)
FIXED_TAIL = (ALNUM * 2)[:72]
PROSE = st.text(alphabet=string.ascii_letters + " .,;:!?-\n", max_size=40)  # no digits, so a card is the only number


class Sample(NamedTuple):
    text: str
    vanish: tuple[str, ...]  # none of these may appear in the redacted text
    card: str | None = None  # a card number's digits: at most its last four may remain


def luhn_complete(body: str) -> str:
    total = sum((d * 2 - 9 if d * 2 > 9 else d * 2) if i % 2 == 0 else d for i, d in enumerate(map(int, body[::-1])))
    return body + str((10 - total % 10) % 10)


def card_number(tail: str, spaced: str = "") -> tuple[str, str]:
    """(shown, digits): a Luhn-valid number of 13 to 19 digits from `tail`, shown plain or in groups of four."""
    size = 13 + ord(tail[-1]) % 7
    # Leading digit 2..9: no real card starts with 1 (BQ-FRMEM05-1 keeps a 13-digit epoch-ms run, which starts with 1).
    body = str(2 + ord(tail[0]) % 8) + "".join(str(ord(c) % 10) for c in tail[1 : size - 1])
    digits = luhn_complete(body)
    return (spaced.join(digits[i : i + 4] for i in range(0, size, 4)) if spaced else digits), digits


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _pem(tail: str, label: str, closed: bool) -> Sample:
    body = textwrap.wrap(base64.b64encode(tail.encode()).decode(), 64)
    head = "-----BEGIN " + label + "-----"
    text = "\n".join([head, *body, *(["-----END " + label + "-----"] if closed else [])])
    return Sample(text, (head, *body))


def _jwt(tail: str) -> Sample:
    signature = _b64url(tail.encode()[:32])
    parts = [_b64url(b'{"alg":"HS256","typ":"JWT"}'), _b64url(json.dumps({"sub": "u_" + tail[:8]}).encode()), signature]
    return Sample(".".join(parts), (".".join(parts), signature))


def _token(prefix: str, size: int, tail: str, *, upper: bool = False) -> Sample:
    secret = prefix + (tail.upper() if upper else tail)[:size]
    return Sample(secret, (secret,))


def _labelled(template: str, tail: str, words: int = 1) -> Sample:
    value = " ".join(
        ["Zq" + tail[i * 14 : i * 14 + 14] for i in range(words)]
    )  # no known shape: only the label gives it away
    return Sample(template.format(v=value), (value,))


def _card(tail: str, spaced: str) -> Sample:
    shown, digits = card_number(tail, spaced)
    return Sample(f"paid with {shown} today", (shown, digits), digits)


def build(kind: str, tail: str) -> Sample:
    return KINDS[kind](tail)


KINDS = {  # the first ten are one each for scripts/secret_scan.py's ten patterns
    "google_oauth_access": lambda t: _token("ya" + "29.", 30, t),
    "google_oauth_refresh": lambda t: _token("1/" + "/0", 40, t),
    "google_api_key": lambda t: _token("AI" + "za", 35, t),
    "google_aq_key": lambda t: _token("AQ" + ".", 45, t),
    "api_secret_key": lambda t: _token("s" + "k-", 30, t),
    "github_token": lambda t: _token("gh" + "p_", 36, t),
    "meta_access_token": lambda t: _token("EA" + "A", 64, t),
    "nvidia_key": lambda t: _token("nv" + "api-", 40, t),
    "service_account": lambda t: Sample('{"type": "service' + '_account"}', ('"type": "service' + '_account"',)),
    "pem_private_key": lambda t: _pem(t, "PRIVATE KEY", True),
    "pem_rsa_private_key": lambda t: _pem(t, "RSA PRIVATE KEY", True),
    "pem_unterminated": lambda t: _pem(t, "PRIVATE KEY", False),
    "aws_access_key": lambda t: _token("AK" + "IA", 16, t, upper=True),
    "jwt": _jwt,
    "bearer_bare": lambda t: Sample("Bearer " + t[:40], (t[:40],)),
    "authorization_header": lambda t: Sample("Authorization: Bearer " + t[:40], (t[:40],)),
    "password_equals": lambda t: _labelled("password={v}", t),
    "password_colon": lambda t: _labelled("Password: {v}", t),
    "password_json": lambda t: _labelled('{{"password": "{v}"}}', t),
    "password_json_two_words": lambda t: _labelled('{{"password": "{v}"}}', t, words=2),
    "api_key_equals": lambda t: _labelled("api_key={v}", t),
    "client_secret_json": lambda t: _labelled('"client_secret": "{v}"', t),
    "refresh_token_colon": lambda t: _labelled("refresh_token: {v}", t),
    "access_token_in_query": lambda t: _labelled("https://example.com/cb?access_token={v}&x=1", t),
    "card_plain": lambda t: _card(t, ""),
    "card_spaced": lambda t: _card(t, " "),
    "card_dashed": lambda t: _card(t, "-"),
}


def leaks(out: str, sample: Sample) -> list[str]:
    found = [v for v in sample.vanish if v in out]
    if sample.card is not None:
        left = re.sub(r"\D", "", out)  # the text around a card holds no other digit
        if left and left != sample.card[-4:]:
            found.append(f"card digits left: {len(left)}")
    return found


def scan_hits(text: str) -> list[str]:
    return [label for pattern, label in SECRET_SCAN.COMPILED if pattern.search(text)]
