"""Secret and payment-card redaction (FR-MEM-05, SEC-14, PRD 16.1 rule 4).

Not a general DLP: covers exactly (1) values under secret-named keys, (2)
the nine patterns in `scripts/secret_scan.py` (reproduced here by hand --
a package must not import from `scripts/`) plus bearer tokens and JWTs, and
(3) Luhn-valid payment card numbers (13-19 digits).
"""

from __future__ import annotations

import bisect
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
]

# JWTs are found by `_find_jwt_spans` below, not a regex in `_PATTERNS`: see
# its docstring for why (round-2's length-capped regex, `\beyJ...{5,1024}+`,
# stayed linear-time but then silently stopped matching any real JWT with a
# segment over 1024 characters, e.g. a Keycloak/Azure token with many
# claims).
_JWT_SEGMENT_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
_JWT_MIN_SEGMENT_LEN = 5
_EYJ_START_RE = re.compile(r"\beyJ")

# A run of digits with single space/dash separators allowed between them, of
# any length: unbounded, not capped at some maximum digit count. A cap
# (round 3's `{12,24}`, 13-25 digits) let a card that shares one run with
# other numbers -- a leading "N " prefix, a trailing date, another card
# right after -- split across two separate regex matches once the combined
# run passed the cap, so a window search inside either half alone could
# never see the whole card and it left the archive unmasked. The run is
# still bounded overall by MAX_SCAN_CHARS on the text it is found in, and
# `_card_windows` below does a bounded amount of work per digit in the run,
# so removing the cap here does not reintroduce unbounded scan cost.
_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d)*")


def _is_secret_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _jwt_run_ends(text: str) -> list[int]:
    """`run_ends[i]` is the index of the first character at or after `i`
    that is not a JWT-segment character (`len(text)` if none) -- the end of
    the maximal base64url run starting at `i`. One linear backward pass."""
    n = len(text)
    run_ends = [n] * (n + 1)
    for i in range(n - 1, -1, -1):
        run_ends[i] = run_ends[i + 1] if text[i] in _JWT_SEGMENT_CHARS else i
    return run_ends


def _find_jwt_spans(text: str) -> list[tuple[int, int]]:
    """Locates non-overlapping JWT spans (start, end) in `text`.

    A single `\\beyJ...\\....\\...` regex is quadratic on adversarial text
    made entirely of JWT-segment characters with no dots: every "eyJ" is a
    fresh candidate, and each one scans forward before failing to find a
    ".". Capping the scan per candidate (round 2's fix) keeps it linear but
    then silently stops matching real JWTs whose header or payload segment
    is longer than the cap.

    This instead finds every "." and the end of every base64url run once,
    up front (two linear passes), then checks each "eyJ" candidate in O(1)
    by comparing those precomputed positions -- no re-scanning, so there is
    no segment-length cap to get wrong."""
    if "eyJ" not in text:
        return []
    dots = [i for i, ch in enumerate(text) if ch == "."]
    run_ends = _jwt_run_ends(text)
    spans: list[tuple[int, int]] = []
    last_end = 0
    for m in _EYJ_START_RE.finditer(text):
        start = m.start()
        if start < last_end:
            continue
        idx1 = bisect.bisect_left(dots, start)
        if idx1 >= len(dots):
            continue
        dot1 = dots[idx1]
        if dot1 - start < _JWT_MIN_SEGMENT_LEN or run_ends[start] != dot1:
            continue
        idx2 = idx1 + 1
        if idx2 >= len(dots):
            continue
        dot2 = dots[idx2]
        if dot2 - (dot1 + 1) < _JWT_MIN_SEGMENT_LEN or run_ends[dot1 + 1] != dot2:
            continue
        end = run_ends[dot2 + 1]
        if end - (dot2 + 1) < _JWT_MIN_SEGMENT_LEN:
            continue
        spans.append((start, end))
        last_end = end
    return spans


def _redact_jwts(text: str) -> str:
    spans = _find_jwt_spans(text)
    if not spans:
        return text
    parts = []
    pos = 0
    for start, end in spans:
        parts.append(text[pos:start])
        parts.append("[REDACTED:jwt]")
        pos = end
    parts.append(text[pos:])
    return "".join(parts)


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


_MIN_CARD_DIGITS = 13
_MAX_CARD_DIGITS = 19


def _group_boundaries(positions: list[int]) -> tuple[list[int], set[int]]:
    """`positions` are the character offsets of every digit inside a
    `_CARD_RE` match, in order. A digit's index into `positions` is a *left*
    boundary when nothing but a single space/dash separates it from the
    previous digit's edge (or it is the run's first digit); it is a *right*
    boundary the same way looking forward. Two adjacent digits with no gap
    at all (part of the same unbroken number) are never a boundary between
    them, so a window can never start or end mid-number.

    Returns the left-boundary indices (ascending) and the set of
    right-boundary indices, so every whole-group-aligned window --
    anywhere in the run, not only at its very start or end -- can be
    enumerated by pairing each left boundary with a right boundary."""
    n = len(positions)
    left = [0] if n else []
    right: set[int] = set()
    for i in range(n):
        if i > 0 and positions[i] != positions[i - 1] + 1:
            left.append(i)
        if i == n - 1 or positions[i + 1] != positions[i] + 1:
            right.add(i)
    return left, right


def _card_windows(raw: str) -> list[tuple[int, int]]:
    """Every Luhn-valid, group-boundary-aligned 13-19 digit card window in
    `raw`, as (start, end) character spans, longest and earliest first.

    Unlike a single "best" window, this enumerates all of them: `raw` can
    hold more than one card-shaped number (two real cards back to back, or a
    card next to an unrelated Luhn-valid-by-chance number), and checking
    only a window anchored at the very start or end of `raw` -- the
    previous approach -- missed a card sitting between two other numbers,
    or let a coincidentally-valid window at one edge pre-empt the real card
    at the other. Every left/right boundary pair at every length in range
    is checked, which is only ever `O(boundaries * 7)` work since a window
    is at most 19 digits.
    """
    positions = [i for i, ch in enumerate(raw) if ch.isdigit()]
    n = len(positions)
    if n < _MIN_CARD_DIGITS:
        return []
    left, right = _group_boundaries(positions)
    windows = []
    for start_idx in left:
        max_len = min(_MAX_CARD_DIGITS, n - start_idx)
        for length in range(_MIN_CARD_DIGITS, max_len + 1):
            end_idx = start_idx + length - 1
            if end_idx not in right:
                continue
            digits = "".join(raw[p] for p in positions[start_idx : end_idx + 1])
            if _luhn_valid(digits):
                windows.append((positions[start_idx], positions[end_idx] + 1))
    return windows


def _redact_cards(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        windows = _card_windows(raw)
        if not windows:
            return raw
        # Multiple card-shaped windows can overlap only in pathological,
        # constructed text; merging them into non-overlapping spans before
        # masking guarantees every digit any valid window covers is hidden,
        # never just the first one found.
        spans: list[list[int]] = []
        for start, end in sorted(windows):
            if spans and start <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], end)
            else:
                spans.append([start, end])
        parts = []
        pos = 0
        for start, end in spans:
            last4 = "".join(ch for ch in raw[start:end] if ch.isdigit())[-4:]
            parts.append(raw[pos:start])
            parts.append(f"[REDACTED:card ****{last4}]")
            pos = end
        parts.append(raw[pos:])
        return "".join(parts)

    return _CARD_RE.sub(_replace, text)


def _redact_string(text: str) -> str:
    if len(text) > MAX_SCAN_CHARS:
        return "[REDACTED:oversize]"
    for pattern, kind in _PATTERNS:
        text = pattern.sub(f"[REDACTED:{kind}]", text)
    text = _redact_jwts(text)
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
    if _find_jwt_spans(text):
        found.append("jwt")
    for match in _CARD_RE.finditer(text):
        if _card_windows(match.group(0)):
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
        # Structural redact() first: a non-str msg (e.g. a dict passed as
        # the whole log message) and dict/mapping or positional args get
        # their secret-named keys and nested values redacted before
        # %-formatting assembles the final line.
        if not isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            # The full structural `redact()` (not just string args): a dict
            # or list arg needs its secret-named keys and nested values
            # redacted too, the same as an archive payload would.
            if isinstance(record.args, dict):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(a) for a in record.args)

        # A secret can still only become visible once msg and args are
        # combined -- e.g. `log.info("Authorization: Bearer %s", token)`,
        # where neither the msg nor the bare token alone matches the bearer
        # pattern -- or hide inside an object's own __str__, e.g.
        # `log.info("err %s", exc)` with a secret in the exception message.
        # Render once with the stdlib's own getMessage() (which applies
        # %-formatting, or just str()s a non-str msg), scan *that* for every
        # pattern, and only when it still finds something, replace msg with
        # the fully redacted line and clear args so nothing downstream
        # re-renders the unredacted original. When the structural pass above
        # already made the composed line clean, msg/args are left as they
        # are -- e.g. a mapping arg's individual entries stay inspectable.
        try:
            composed = record.getMessage()
        except Exception:
            composed = str(record.msg)
        scanned = _redact_string(composed)
        if scanned != composed:
            record.msg = scanned
            record.args = ()

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
