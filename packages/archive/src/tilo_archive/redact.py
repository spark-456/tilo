"""Secret and payment-card redaction (FR-MEM-05, SEC-14, PRD 16.1 rule 4).

Not a general DLP: covers exactly (1) values under secret-named keys, (2)
the nine patterns in `scripts/secret_scan.py` (reproduced here by hand --
a package must not import from `scripts/`) plus bearer tokens and JWTs, and
(3) Luhn-valid payment card numbers (13-19 digits).
"""

from __future__ import annotations

import logging
import re
import traceback
from typing import Any

MAX_SCAN_CHARS = 1_000_000
_MAX_DEPTH = 64

# Case-insensitive substrings of a dict key that mark its value as secret.
_SECRET_KEY_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
    "client_secret",
    "refresh_token",
    "access_token",
    "pin",
)

# (compiled pattern, kind) -- independent copy of secret_scan.py's patterns,
# plus bearer tokens and JWTs.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private_key"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "google_api_key"),
    (re.compile(r"ya29\.[0-9A-Za-z_\-]{20,}"), "google_oauth_access_token"),
    (re.compile(r"1//0[0-9A-Za-z_\-]{30,}"), "google_oauth_refresh_token"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), "api_secret_key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"), "github_token"),
    (re.compile(r"\bEAA[A-Za-z0-9]{60,}"), "meta_whatsapp_token"),
    (re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}"), "nvidia_nim_key"),
    (re.compile(r"\"type\"\s*:\s*\"service_account\""), "service_account_key"),
    # Optional quotes around the header name and the value cover both a raw
    # "Authorization: Bearer x" header line and a JSON-quoted
    # "Authorization": "Bearer x" field. Charset includes RFC 6750's token68
    # set (+ / ~ alongside - . _ and = padding).
    (re.compile(r'Authorization"?\s*:\s*"?Bearer\s+[A-Za-z0-9\-_.~+/=]+', re.IGNORECASE), "bearer_token"),
    # Anchored to the real JWT shape (header JSON always starts "{" -> "eyJ"
    # once base64-encoded). "\b" alone is not enough to keep this linear:
    # since "-" is itself in the segment class below, "\b" still matches at
    # every "eyJ" that immediately follows a "-", so on adversarial input
    # like "eyJ-" repeated many times a new match attempt restarts at every
    # occurrence; even with possessive quantifiers (no backtracking within
    # one attempt), each attempt was unbounded ("{5,}+") and so scanned all
    # the way to the end of the remaining text before failing -- O(attempts
    # x remaining length), i.e. quadratic. Bounding each segment to a
    # generous but finite width (1024 -- past the longest signature a real
    # JWT produces, RS512's ~683 base64 chars, with headroom) caps the work
    # of *every* attempt, matched or not, to O(1024) regardless of how much
    # text follows: total cost is O(text length), not O(text length^2). A
    # tighter start anchor (e.g. rejecting "eyJ" preceded by another
    # class character) was considered instead, but it would also reject a
    # genuine JWT glued directly onto an identifier (e.g. "trace-eyJ..."),
    # which this redactor must still catch.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,1024}+\.[A-Za-z0-9_-]{5,1024}+\.[A-Za-z0-9_-]{5,1024}+\b"), "jwt"),
]

# 13-25 raw digits (spaces/dashes allowed as separators): wide enough to also
# sweep in a trailing CVV/expiry or a leading stray digit, which _card_span
# then trims back to the actual 13-19 digit Luhn-valid card.
_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,24}(?!\d)")


def _is_secret_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _card_span(raw: str) -> tuple[int, int, str] | None:
    """Locates a contiguous Luhn-valid 13-19 digit card inside `raw`, which
    may carry extra digits swept in by the outer `_CARD_RE` match: a
    trailing CVV/expiry (try the longest prefix window first) or a leading
    stray digit (fall back to the longest suffix window). Returns the
    (start, end) character span of just the card digits within `raw`, and
    the card's own digit string -- or None if no window is Luhn-valid."""
    positions = [i for i, ch in enumerate(raw) if ch.isdigit()]
    n = len(positions)
    if n < 13:
        return None
    for length in range(min(19, n), 12, -1):
        digits = "".join(raw[p] for p in positions[:length])
        if _luhn_valid(digits):
            return positions[0], positions[length - 1] + 1, digits
    for length in range(min(19, n), 12, -1):
        digits = "".join(raw[p] for p in positions[n - length :])
        if _luhn_valid(digits):
            return positions[n - length], positions[-1] + 1, digits
    return None


def _redact_cards(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        span = _card_span(raw)
        if span is None:
            return raw
        start, end, digits = span
        return raw[:start] + f"[REDACTED:card ****{digits[-4:]}]" + raw[end:]

    return _CARD_RE.sub(_replace, text)


def _redact_string(text: str) -> str:
    if len(text) > MAX_SCAN_CHARS:
        return "[REDACTED:oversize]"
    for pattern, kind in _PATTERNS:
        text = pattern.sub(f"[REDACTED:{kind}]", text)
    return _redact_cards(text)


def _redact_value(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return "[REDACTED:too_deep]"
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for k, v in value.items():
            # The key text itself is scanned too (not just checked against the
            # secret-name markers): a credential pattern can turn up as a map
            # key, not only as a value.
            new_key = _redact_string(k) if isinstance(k, str) else k
            result[new_key] = "[REDACTED:secret_field]" if _is_secret_key(k) else _redact_value(v, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        # A tuple is redacted the same as a list: canonical_json's
        # json.dumps would otherwise serialise it as a JSON array verbatim,
        # unredacted, since only dict/list were walked here.
        return [_redact_value(v, depth + 1) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def redact(value: Any) -> Any:
    """Deep copy of any JSON-like `value` with secrets/card numbers replaced.
    Never raises, whatever the shape -- NaN/Infinity rejection is the archive
    writer's job, not this function's."""
    return _redact_value(value, 0)


def find_secrets(text: str) -> list[str]:
    """Kinds of secret found in `text` (possibly with duplicates), or []."""
    if not isinstance(text, str):
        return []
    if len(text) > MAX_SCAN_CHARS:
        # Fail closed: oversize text is never scanned piecemeal, so it is
        # reported as a finding rather than silently coming back clean.
        return ["oversize"]
    found = [kind for pattern, kind in _PATTERNS if pattern.search(text)]
    for match in _CARD_RE.finditer(text):
        if _card_span(match.group(0)) is not None:
            found.append("card")
            break
    return found


def redact_prompt(text: str) -> str:
    """Redacts secrets out of prompt text before it reaches a model call."""
    return _redact_string(text if isinstance(text, str) else str(text))


class RedactingFilter(logging.Filter):
    """Redacts a log record's `msg`, `args` and any exception traceback in
    place; never drops the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_string(record.msg)
        if record.args:
            # The full structural `redact()` (not just string args): a dict
            # or list arg needs its secret-named keys and nested values
            # redacted too, the same as an archive payload would.
            if isinstance(record.args, dict):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(a) for a in record.args)
        if isinstance(record.exc_info, tuple) and len(record.exc_info) == 3:
            try:
                formatted = "".join(traceback.format_exception(*record.exc_info))
            except Exception:
                formatted = "[unformattable traceback]"
            # Replace the raw traceback everywhere a formatter could read it
            # from: pre-render exc_text redacted, and drop exc_info so
            # nothing downstream re-renders the unredacted original.
            record.exc_text = _redact_string(formatted)
            record.exc_info = None
        return True
