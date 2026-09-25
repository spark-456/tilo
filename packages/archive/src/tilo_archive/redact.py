"""Secret and payment-card redaction (FR-MEM-05, SEC-14, PRD 16.1 rule 4).

Not a general DLP: covers exactly (1) values under secret-named keys, (2)
the nine patterns in `scripts/secret_scan.py` (reproduced here by hand --
a package must not import from `scripts/`) plus bearer tokens and JWTs, and
(3) Luhn-valid payment card numbers (13-19 digits).
"""

from __future__ import annotations

import logging
import re
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
    (re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9\-_.=]+", re.IGNORECASE), "bearer_token"),
    (re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "jwt"),
]

# 13-19 digits, spaces/dashes allowed; Luhn checked separately before redacting.
_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")


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


def _redact_cards(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"[ -]", "", raw)
        if not (13 <= len(digits) <= 19) or not _luhn_valid(digits):
            return raw
        return f"[REDACTED:card ****{digits[-4:]}]"

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
        return {
            k: ("[REDACTED:secret_field]" if _is_secret_key(k) else _redact_value(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
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
    if not isinstance(text, str) or len(text) > MAX_SCAN_CHARS:
        return []
    found = [kind for pattern, kind in _PATTERNS if pattern.search(text)]
    for match in _CARD_RE.finditer(text):
        digits = re.sub(r"[ -]", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            found.append("card")
            break
    return found


def redact_prompt(text: str) -> str:
    """Redacts secrets out of prompt text before it reaches a model call."""
    return _redact_string(text if isinstance(text, str) else str(text))


class RedactingFilter(logging.Filter):
    """Redacts a log record's `msg` and `args` in place; never drops it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_string(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: (_redact_string(v) if isinstance(v, str) else v) for k, v in record.args.items()}
            else:
                record.args = tuple(_redact_string(a) if isinstance(a, str) else a for a in record.args)
        return True
