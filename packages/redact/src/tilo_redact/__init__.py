"""tilo_redact: the one shared secret redactor (FR-MEM-05, SEC-14; PRD 13.2, 16.1 rule 4, 16.2). Standard library only,
so providers, archive, memory, api, connectors, harness, evals and logging can all use it without a cycle.

    redact(text)          text with every secret replaced by REDACTED; unchanged when it holds none
    redact_value(obj)     the same over a JSON tree (a new tree): every string and key, and a secure field whole
    RedactingFilter       a `logging.Filter` that redacts a record's message, traceback and extra fields

What goes (each rule is deterministic, and the result is idempotent: `redact(redact(t)) == redact(t)`):
  - a private key block (PEM, PGP, any `... PRIVATE KEY` label): to its END line; with none, only its header and the
    base64 lines after it, so the text that follows an untrusted header survives;
  - the token shapes of `scripts/secret_scan.py` plus Google access, refresh and auth-code tokens (`ya29.c.`, `4/0A`),
    Firebase refresh tokens, GitHub (incl. fine-grained), Slack and AWS keys, JWTs and a bare `Bearer` token;
  - the userinfo of any `scheme://user:pass@host`; and the value of an `Authorization`, `Proxy-Authorization`, `Cookie`
    or `Set-Cookie` header, to the end of its line, whatever its scheme;
  - the value of a labelled secret, one key rule for both modes (`SECURE_KEYS`): the key matches in any case, with `_`,
    `-` or camelCase (`api_key`, `X-Api-Key`, `accessToken`), and its value is quoted (also JSON-in-JSON `\\"` and
    `&quot;`, with backslash escapes), unquoted, in a form body or in a query string. `code`, `key`, `signature`,
    `pass` and `pwd` are only secrets as `?x=` or `&x=` parameters (and `pass`, `pwd` also as tree keys);
  - a card number: 13 to 19 digits (plain, or in groups under a space or dash), Luhn-valid, not touching a letter,
    digit, `_`, `.` or `-` (so digests, ULIDs, ids and decimals are safe). It leaves REDACTED and its last four digits.
  - in a tree, the whole value of a secure key, whatever it holds. Other keys (`max_output_tokens`, `authz`) stay.

What stays: emails and phone numbers (PRD 16.1 rule 4 is about secrets; recipients are the data the archive holds),
JSON numbers (only text is scanned), and any Luhn-failing digit run. The artifact store, connectors and run bundle
REFUSE content this would change (MF-06, AR-07), so a false positive breaks real work. A number that cannot be a card
is therefore not one: it never starts with 0 (no card IIN does), and a plain 13-digit run from 1500000000000 to
1999999999999 is an epoch-millisecond timestamp (2017 to 2033), about one in ten of which passes Luhn, so it is kept
(BQ-FRMEM05-1). A prose "password: none" is redacted on purpose: the redactor fails closed.

Out of scope, and so a miss: a secret wrapped in base64, URL-encoding (except `%5B`/`%5D` around a key) or any other
encoding, and Unicode look-alikes. The raw archive is append-only, so a secret this misses is stored for good: add the
shape here, with a keeps test, before the archive sees it. Every pattern is linear: a prefix is anchored where the
body could restart inside itself, and quantifiers are possessive.
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "[REDACTED]"
MAX_DEPTH = 200  # redact_value refuses a deeper tree (or a cycle) with a ValueError, never a RecursionError

_STRONG = (  # keys whose value is a secret wherever they appear, as words joined by `_`
    "password passwd passphrase secret secret_key client_secret token access_token refresh_token id_token auth_token "
    "api_key private_key authorization cookie aws_secret_access_key aws_session_token"
).split()
_EXACT = ("pass", "pwd")  # too common as a word or suffix: a tree key by itself, and a text label only in a query
_QUERY = (*_EXACT, "code", "key", "signature", "x_goog_signature", "x_amz_signature", "x_amz_security_token")
SECURE_KEYS = frozenset((*_STRONG, *_EXACT))  # normalised: lower case, `_` for `-` and camelCase breaks
_ENDS = tuple(key.replace("_", "") for key in _STRONG)  # `xapikey`, `setcookie`, `proxyauthorization`, `dbpassword`


def _secure(key: str) -> bool:
    """The one key rule, for tree keys: case, `_`, `-` and camelCase do not matter, and a longer key may end in one."""
    flat = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key.strip()).lower().replace("-", "").replace("_", "")
    return flat.endswith(_ENDS) or flat in {"pass", "pwd"}


def _label(keys: tuple[str, ...] | list[str]) -> str:
    return "|".join(r"(?:[_-]|%5[Ff])?".join(key.split("_")) for key in sorted(keys, key=len, reverse=True))


_NAME = r"(?:(?!PRIVATE KEY)[A-Z0-9]++ )*+PRIVATE KEY(?: BLOCK)?"
_NL = r"(?:\r?\n|\\n)"
_HEADERS = "Proc-Type|DEK-Info|Version|Comment|Charset|Hash"
_PEM = re.compile(
    rf"-----BEGIN {_NAME}-----(?:(?:(?!-----BEGIN |-----END {_NAME}-----)[\s\S])*+-----END {_NAME}-----"
    rf"|(?:{_NL}[ \t]*+(?:[A-Za-z0-9+/=]{{16,}}+[^\r\n\\]*+"  # a key line, and anything else on it
    rf"|(?:[A-Za-z0-9+/=]++|(?:{_HEADERS}): [^\r\n\\]*+)?[ \t]*+(?={_NL}|\Z)))*+)"
)
_USERINFO = re.compile(r"(?<![A-Za-z0-9+.-])([A-Za-z][A-Za-z0-9+.-]{0,31}://)[^\s/?#]{1,1024}@")
_HEADER = re.compile(
    r"""(?<![\w"'\\-])((?:proxy-)?authorization|(?:set-)?cookie)([ \t]{0,8}:[ \t]{0,8}+)[^\r\n]+""", re.I
)
_B = r"[A-Za-z0-9._~+/=-]"  # a bearer token's characters: a capital `Bearer` takes 8, any case takes 20 or a digit
_BEARER = rf"\bBearer\s{{1,8}}{_B}{{8,}}+|\b(?i:bearer)\s{{1,8}}(?:{_B}{{20,}}+|(?={_B}*[\d._~+/=-]){_B}{{8,}}+)"
_TOKENS = re.compile(
    "|".join(
        [
            _BEARER,
            r"AIza[0-9A-Za-z_-]{35,}+",
            r"(?<![A-Za-z0-9])AQ\.[0-9A-Za-z_-]{40,}+",
            r"ya29\.[0-9A-Za-z_.-]{20,}+",
            r"1//0[0-9A-Za-z_-]{30,}+",
            r"(?<![A-Za-z0-9/_-])4/0A[0-9A-Za-z_-]{30,}+",
            r"AMf-vB[0-9A-Za-z_-]{50,}+",
            r"(?<![A-Za-z0-9-])sk-[A-Za-z0-9_-]{20,}+",
            r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,}+",
            r"github_pat_[A-Za-z0-9_]{22,}+",
            r"xox[abposr]-[A-Za-z0-9-]{10,}+",
            r"hooks\.slack\.com/services/[A-Za-z0-9/]{20,}+",
            r"(?<![A-Za-z0-9])EAA[A-Za-z0-9]{60,}+",
            r"(?<![A-Za-z0-9])nvapi-[A-Za-z0-9_-]{20,}+",
            r"(?<![A-Za-z0-9])A[KS]IA[0-9A-Z]{16}(?![A-Za-z0-9])",
            r'"type"\s*:\s*"service_account"',
            r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]++\.[A-Za-z0-9_-]++\.[A-Za-z0-9_-]*+",
        ]
    )
)
_SEP = "[ \u00a0\u2009\u202f-]"  # a space, no-break space, thin space, narrow no-break space or dash
_CARD = re.compile(rf"(?<![\w.-])(?:\d{{13,19}}|\d{{4,6}}{_SEP}\d{{4,6}}(?:{_SEP}\d{{1,6}}){{1,3}})(?![\w-])(?!\.\d)")
_EPOCH_MS = re.compile(r"1[5-9]\d{11}")
_EQ = r"""\\++["']|&quot;|&apos;|&#0*3[49];"""  # a quote as JSON-in-JSON or HTML spells it
_VALUE = (
    rf"""(?:(?P<eq>{_EQ})(?:(?!{_EQ})[^\n])++"""  # runs to the next such quote or the end of the line
    r"""|(?P<q>["'])(?:(?!(?P=q))[^\\\n]|\\.)++"""  # a backslash escapes: an escaped quote does not close it
    r"""|[^\s&"'<>]++)"""
)
_LABELLED = re.compile(
    rf"""(?:(?<![A-Za-z0-9])|(?<=%5[Bb]))(?:{_label(_STRONG)})(?:{_EQ}|["'\]]|%5[Dd])?[ \t]{{0,8}}[:=][ \t]{{0,8}}"""
    rf"""|(?<=[?&])(?:{_label(_QUERY)})=""",
    re.I,
)
_LABELLED_VALUE = re.compile(_VALUE)


def _labelled(text: str) -> str:
    out, last = [], 0
    for m in _LABELLED.finditer(text):  # the value is matched where the label ends, so each part is read once
        if m.start() < last:  # inside a value already removed
            continue
        value = _LABELLED_VALUE.match(text, m.end())
        if value is None:
            continue
        quote = value.group("eq") or value.group("q") or ""
        out += [text[last : m.end()], quote, REDACTED]
        last = value.end()
    out.append(text[last:])
    return "".join(out)


def _luhn(digits: str) -> bool:
    total = sum((d * 2 - 9 if d > 4 else d * 2) if i % 2 else d for i, d in enumerate(map(int, digits[::-1])))
    return total % 10 == 0


def _card(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if not 13 <= len(digits) <= 19 or digits[0] == "0" or _EPOCH_MS.fullmatch(raw) or not _luhn(digits):
        return raw
    return f"{REDACTED} (ends {digits[-4:]})"


def redact(text: str) -> str:
    """`text` with every secret replaced by REDACTED (see the module docstring); `text` itself when it holds none."""
    low = text.lower()
    if "-----begin" in low:
        text = _PEM.sub(REDACTED, text)
    if "://" in text:
        text = _USERINFO.sub(rf"\1{REDACTED}@", text)
    if "authorization" in low or "cookie" in low:
        text = _HEADER.sub(rf"\1\2{REDACTED}", text)
    return _labelled(_CARD.sub(_card, _TOKENS.sub(REDACTED, text)))


def redact_value(obj: Any, _depth: int = 0) -> Any:
    """A new tree like `obj` with every string (and key) redacted and every secure field's value replaced whole.
    Dicts, lists, tuples, sets, bytes and scalars are walked; any other type, and a tree deeper than MAX_DEPTH (or one
    that holds itself), is refused with a TypeError or ValueError, never passed through unredacted. Two keys that redact
    to one string both stay (the second gets a `#2` suffix)."""
    if _depth > MAX_DEPTH:
        raise ValueError(f"redact_value: tree is deeper than {MAX_DEPTH} levels")
    if isinstance(obj, str):
        return redact(obj)
    if obj is None or isinstance(obj, bool | int | float):
        return obj
    deeper = _depth + 1
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for key, value in obj.items():
            new = base = redact_value(key, deeper)
            for n in range(2, len(out) + 3):
                if new not in out:
                    break
                new = f"{redact(str(base))}#{n}"
            out[new] = REDACTED if isinstance(key, str) and _secure(key) else redact_value(value, deeper)
        return out
    if isinstance(obj, list | tuple):
        items = [redact_value(item, deeper) for item in obj]
        return items if isinstance(obj, list) else tuple(items)
    if isinstance(obj, set | frozenset):
        return type(obj)(redact_value(item, deeper) for item in obj)
    if isinstance(obj, bytes | bytearray):  # lossless: bytes that are not text survive as they are
        return type(obj)(redact(bytes(obj).decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape"))
    raise TypeError(f"redact_value: cannot redact a {type(obj).__name__}")


_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


class RedactedError(Exception):
    """Stands in for a logged exception whose traceback text has been redacted (`str()` is that text)."""


def _log_safe(value: Any) -> Any:
    try:
        return redact_value(value)
    except (TypeError, ValueError):
        return redact(repr(value))  # an object, or a tree too deep: its text, redacted


class RedactingFilter(logging.Filter):
    """Attach to a handler (PRD 16.1 rule 4: secrets never enter logs). Rewrites the record's message (after the
    %-arguments are applied; a non-string message too), its traceback and stack text, and any extra field, so a
    formatter built on `logging.Formatter.format` emits no secret. `record.exc_info` is replaced by a redacted stand-in,
    so a formatter that calls `formatException(record.exc_info)` itself is safe too. Never drops a record and never
    raises: if redaction itself fails, the message is replaced whole."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg, record.args = redact(record.getMessage()), None
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = redact(record.exc_text)
                record.exc_info = (RedactedError, RedactedError(record.exc_text), None)
            record.stack_info = redact(record.stack_info) if record.stack_info else record.stack_info
            for name in set(vars(record)) - _STANDARD:
                setattr(record, name, _log_safe(getattr(record, name)))
        except Exception:  # noqa: BLE001 (a logger must not fail the caller; fail closed instead)
            record.msg, record.args, record.exc_info, record.exc_text, record.stack_info = (
                REDACTED,
                None,
                None,
                None,
                None,
            )
        return True
