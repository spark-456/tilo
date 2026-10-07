"""tilo_redact: the one shared secret redactor (FR-MEM-05, SEC-14; PRD 13.2, 16.1 rule 4, 16.2). Standard library only,
so providers, archive, memory, api, connectors, harness, evals and logging can all use it without a cycle.

    redact(text)          text with every secret replaced by REDACTED; unchanged when it holds none
    redact_value(obj)     the same over a JSON tree (a new tree): every string and key, and a secure field whole
    RedactingFilter       a `logging.Filter` that redacts a record's message, traceback and extra fields

What goes (each rule is deterministic, and the result is idempotent: `redact(redact(t)) == redact(t)`):
  - a private key block, to its END line or, with none, to the end of the text;
  - the well-known token shapes of `scripts/secret_scan.py` (Google, GitHub, Meta, NVIDIA, `sk-` keys, a service
    account marker), AWS access key ids and JWTs;
  - `Authorization: <scheme> <credential>` and a bare `Bearer <token>`;
  - the value of a labelled secret (`password=`, `api_key:`, `client_secret`, `access_token`, `refresh_token`, quoted or
    not, in JSON or a query string) and of a quoted `"secret"`, `"token"`, `"authorization"` or `"cookie"` JSON key;
  - a card number: 13 to 19 digits (plain, or in groups under one separator, a space or a dash), Luhn-valid, not
    touching a letter, digit, `_`, `.` or `-` (so digests, ULIDs, ids and decimals are safe). It leaves REDACTED and
    its last four digits.
  - in a tree, the whole value of a key named (any case) password, secret, token, access_token, refresh_token,
    client_secret, api_key, authorization or cookie, whatever it holds. Other keys (`max_output_tokens`, `authz`) stay.

What stays: emails and phone numbers (PRD 16.1 rule 4 is about secrets; recipients are the data the archive holds),
JSON numbers (only text is scanned), and any Luhn-failing digit run. The artifact store, connectors and run bundle
REFUSE content this would change (MF-06, AR-07), so a false positive breaks real work. A number that cannot be a card
is therefore not one: it never starts with 0 (no card IIN does), and a plain 13-digit run from 1500000000000 to
1999999999999 is an epoch-millisecond timestamp (2017 to 2033), about one in ten of which passes Luhn, so it is kept
(BQ-FRMEM05-1).
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "[REDACTED]"

SECURE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "authorization",
        "cookie",
    }
)

_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)")
_AUTH = re.compile(r"\bAuthorization\s*:\s*(?:Bearer|Basic|Digest|Token)\s+\S+", re.I)
_BEARER = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=-]{20,}", re.I)
_TOKENS = re.compile(
    "|".join(
        [
            r"AIza[0-9A-Za-z_-]{35,}",
            r"\bAQ\.[0-9A-Za-z_-]{40,}",
            r"ya29\.[0-9A-Za-z_-]{20,}",
            r"1//0[0-9A-Za-z_-]{30,}",
            r"\bsk-[A-Za-z0-9_-]{20,}",
            r"\bgh[pousr]_[A-Za-z0-9]{36,}",
            r"\bEAA[A-Za-z0-9]{60,}",
            r"\bnvapi-[A-Za-z0-9_-]{20,}",
            r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])",
            r'"type"\s*:\s*"service_account"',
            r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*",
        ]
    )
)
_CARD = re.compile(r"(?<![\w.-])(?:\d{13,19}|\d{4,6}(?P<sep>[ -])\d{4,6}(?:(?P=sep)\d{1,6}){1,3})(?![\w-])(?!\.\d)")
_EPOCH_MS = re.compile(r"1[5-9]\d{11}")
_VALUE = r"""(?:"([^"\n]+)"|'([^'\n]+)'{unquoted})"""
_LABELLED = re.compile(
    r"""(?<![A-Za-z0-9_])((?:password|passwd|api[_-]?key|client[_-]?secret|(?:access|refresh)[_-]?token)["']?\s*[:=]\s*)"""
    + _VALUE.format(unquoted=r"""|([^\s&"'<>]+)"""),
    re.I,
)
_JSON_KEY = re.compile(r"""(["'](?:secret|token|authorization|cookie)["']\s*:\s*)""" + _VALUE.format(unquoted=""), re.I)


def _luhn(digits: str) -> bool:
    total = sum((d * 2 - 9 if d > 4 else d * 2) if i % 2 else d for i, d in enumerate(map(int, digits[::-1])))
    return total % 10 == 0


def _card(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if not 13 <= len(digits) <= 19 or digits[0] == "0" or _EPOCH_MS.fullmatch(raw) or not _luhn(digits):
        return raw
    return f"{REDACTED} (ends {digits[-4:]})"


def _labelled(match: re.Match[str]) -> str:
    quote = '"' if match.group(2) else "'" if match.group(3) else ""
    return f"{match.group(1)}{quote}{REDACTED}{quote}"


def redact(text: str) -> str:
    """`text` with every secret replaced by REDACTED (see the module docstring); `text` itself when it holds none."""
    text = _PEM.sub(REDACTED, text)
    for pattern in (_AUTH, _BEARER, _TOKENS):
        text = pattern.sub(REDACTED, text)
    text = _CARD.sub(_card, text)
    return _JSON_KEY.sub(_labelled, _LABELLED.sub(_labelled, text))


def redact_value(obj: Any) -> Any:
    """A new tree like `obj` with every string (and key) redacted and every secure field's value replaced whole."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {
            (redact(k) if isinstance(k, str) else k): (
                REDACTED if isinstance(k, str) and k.lower() in SECURE_KEYS else redact_value(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list | tuple):
        return type(obj)(redact_value(item) for item in obj)
    return obj


_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


class RedactingFilter(logging.Filter):
    """Attach to a handler (PRD 16.1 rule 4: secrets never enter logs). Rewrites the record's message (after the
    %-arguments are applied; a non-string message too), its traceback and stack text, and any extra field, so a
    formatter built on `logging.Formatter.format` emits no secret. Never drops a record and never raises: if
    redaction itself fails, the message is replaced whole."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg, record.args = redact(record.getMessage()), None
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact(record.exc_text) if record.exc_text else record.exc_text
            record.stack_info = redact(record.stack_info) if record.stack_info else record.stack_info
            for name in set(vars(record)) - _STANDARD:
                setattr(record, name, redact_value(getattr(record, name)))
        except Exception:  # noqa: BLE001 (a logger must not fail the caller; fail closed instead)
            record.msg, record.args, record.exc_info, record.exc_text, record.stack_info = (
                REDACTED,
                None,
                None,
                None,
                None,
            )
        return True
