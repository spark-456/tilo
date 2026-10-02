"""One masker for everything that leaves a browser worker (PRD 12.3, 16.1 rule 4, SEC-14).

Placeholders are `[masked:<kind>]`. Pure, idempotent, never raises on any str. Page content is
untrusted, so every pattern is linear: no unbounded prefix before a keyword, bounded repeats,
and a card window never grows past 19 digits.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from itertools import accumulate
from typing import Any
from urllib.parse import unquote

# Text over this many characters is cut (and marked) after masking, so one call stays bounded
# (about 0.6 s of CPU on hostile input). It stays above 200,000: the hostile-input tests put a
# card at the very end of that much text. A window past the cut is masked first, so a secret
# that straddles the cut is masked whole before anything is dropped.
MAX_TEXT_CHARS = 200 * 1024
TRUNCATED_MARKER = " [truncated]"
_CUT_WINDOW = 8192  # longer than any secret shape the patterns below can match across the cut
_CUT_HEADROOM = 64  # re-masking the cut tail may add a few placeholder characters
_CUT_TAIL = 256  # the cut can leave a partial token this close to the end: that tail is masked again
_CUT_PARTIAL = 4200  # a window that ends mid-secret: drop this much of the masked end (userinfo is up to 4,096)

# Every shape here needs a word in _HINT_WORDS (its lower-case marker), or the gate skips it on
# text that holds nothing else; test_FR_CON_07_more_secret_shapes_are_masked is the canary.
_FREE_SECRETS = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
    # any case, but then the token must hold a digit or punctuation, so prose ("bearer instruments") stays
    r"|\b(?i:bearer)\s+(?=[A-Za-z0-9._~+/=-]*[\d._~+/=-])[A-Za-z0-9._~+/=-]{8,}"
    r"|\b(?i:sk)-[A-Za-z0-9_-]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|\bya29\.[A-Za-z0-9_-]{20,}"
)
# A quoted value runs to its closing quote, an escaped quote does not close it, and with no
# closing quote it runs to the end of the line; any length is masked whole. Linear: each
# character is consumed once and nothing backtracks.
_QUOTED = r"([\"'])((?:(?!\2)[^\\\n]|\\.)+)(\2?)"
# The keyword is matched directly (no prefix scan), so a long word cannot make this quadratic.
_KEY_VALUE = re.compile(
    r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|otp)[\"']?\s{0,8}[=:]\s{0,8})"
    rf"(?:{_QUOTED}|([^\s&\"']+))"
)
# `Authorization:` and `Cookie:` values run to the end of the line. Only a known scheme word, with a
# credential-looking value after it, stays; any other first word is the credential and is masked.
# The scheme is possessive, so an already masked value is left alone (idempotent).
_SCHEMES = "basic|bearer|digest|token|negotiate|ntlm|hoba|mutual|vapid|dpop|aws4-hmac-sha256"
_AUTH_HEADER = re.compile(
    r"(?i)(\b(?:authorization|(?:set-)?cookie)[\"']?\s{0,8}[=:]\s{0,8}+)"
    rf"(?:{_QUOTED}|((?:(?:{_SCHEMES})[ \t]+(?=[A-Za-z0-9._~+/=\"'\[]))?+)(?!\[masked:)[^\r\n]+)"
)
# `scheme://userinfo@` anywhere in text (a path, a query, page copy): the userinfo, of any length and
# with at most one space, is dropped.
_URL_USERINFO = re.compile(
    r"(?<![A-Za-z0-9+.-])([A-Za-z][A-Za-z0-9+.-]{0,63}://)(?!\[masked:secret\]@)[^\s/?#]+(?: [^\s/?#]+)?@"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,8}")
_PHONE = re.compile(r"(?<![\w+])\+\d[\d ()-]{6,24}\d")
# Digit groups of 2+ digits joined by one space or dash; a lone digit is never part of a card layout.
_DIGIT_RUN = re.compile(r"(?<!\w)\d{2,}(?:[ -]\d{2,})*")
# Every secret shape the free-secret and key-value passes can match contains one of these words
# (lower-cased); a card needs 13 digits with at most one separator between neighbours. Plain
# `in` scans and one anchored regex are several times cheaper than running every pass on short strings.
_HINT_WORDS = (
    *("bearer", "sk-", "akia", "asia", "eyj", "ya29", "password", "passwd", "pwd", "secret", "token", "otp"),
    *("apikey", "api_key", "api-key", "ghp_", "gho_", "ghu_", "ghs_", "ghr_"),
)
_DIGITS13 = re.compile(r"\d(?:[ -]?\d){12}")
_SEPARATOR = re.compile(r"[ -]")
_SEPARATORS = str.maketrans("", "", " -")


def _luhn_prefixes(digits: str) -> tuple[list[int], list[int]]:
    """Prefix sums of Luhn terms, doubling even (a) or odd (b) indexes, so a window checks in O(1)."""
    vals = [int(c) for c in digits]
    dbl = [v * 2 - 9 if v > 4 else v * 2 for v in vals]
    even, odd = vals[:], vals[:]
    even[0::2] = dbl[0::2]
    odd[1::2] = dbl[1::2]
    return [0, *accumulate(even)], [0, *accumulate(odd)]


def _mask_cards(text: str) -> str:
    """Mask the longest Luhn-valid 13 to 19 digit window made of whole digit groups."""
    out: list[str] = []
    last = 0
    for run in _DIGIT_RUN.finditer(text):
        body = run.group()
        digits = body.translate(_SEPARATORS)  # the run holds digits and single separators only
        if len(digits) < 13:
            continue
        sizes = list(map(len, _SEPARATOR.split(body)))
        if len(sizes) == 1 and not 13 <= sizes[0] <= 19:
            continue  # one long group: no window of whole groups fits
        pa, pb = (list(map((10).__rmod__, p)) for p in _luhn_prefixes(digits))  # residues mod 10
        ends = [0, *accumulate(sizes)]  # ends[k]: digits before group k
        n = len(sizes)  # group k starts at offset ends[k] + k in the run, and group k-1 ends at ends[k] + k - 1
        i = 0
        while i < n:
            lo = ends[i]
            hit = None
            for k in range(bisect_right(ends, lo + 19) - 1, bisect_left(ends, lo + 13) - 1, -1):
                e = ends[k]
                p = pb if e & 1 else pa  # double the digits an odd distance from the end
                if p[e] == p[lo]:  # the window's digit sum is 0 mod 10
                    hit = k - 1
                    break
            if hit is None:
                i += 1
                continue
            out.append(text[last : run.start() + ends[i] + i])
            out.append("[masked:card]")
            last = run.start() + ends[hit + 1] + hit
            i = hit + 1
    out.append(text[last:])
    return "".join(out)


_MASK = "[masked:secret]"


def _kv(m: re.Match[str]) -> str:
    return m[1] + (f"{m[2]}{_MASK}{m[4]}" if m[2] else _MASK)


def _auth(m: re.Match[str]) -> str:
    return m[1] + (f"{m[2]}{_MASK}{m[4]}" if m[2] else m[5] + _MASK)


def _mask(text: str) -> str:
    low = text.casefold()
    ascii_only = text.isascii()  # (?i) also folds U+017F, U+0131 and U+212A, so non-ASCII text runs every pass
    words = not ascii_only or any(map(low.__contains__, _HINT_WORDS))
    card = sum(map(str.isdigit, text)) > 12 and _DIGITS13.search(text) is not None
    if "://" in text:
        text = _URL_USERINFO.sub(r"\1[masked:secret]@", text)
    if words:
        text = _FREE_SECRETS.sub(_MASK, text)
    if not ascii_only or "authorization" in low or "cookie" in low:
        text = _AUTH_HEADER.sub(_auth, text)
    if words:
        text = _KEY_VALUE.sub(_kv, text)
    if card:
        text = _mask_cards(text)
    if "@" in text:
        text = _EMAIL.sub("[masked:email]", text)
    return _PHONE.sub("[masked:phone]", text) if "+" in text else text


def mask_text(text: str) -> str:
    """Mask `text`. If the masked text is over MAX_TEXT_CHARS (it can grow) or the raw text runs past
    the window, it is cut and marked; the result never exceeds the cap by more than the marker, and
    masking it again changes nothing. A text that already ends in the marker is masked without it."""
    if len(text) < 5:  # the shortest thing any pattern masks is `a@b.c` or `otp=1`
        return text
    marked = text.endswith(TRUNCATED_MARKER)
    body = text[: -len(TRUNCATED_MARKER)] if marked else text
    window = MAX_TEXT_CHARS + _CUT_WINDOW
    masked = _mask(body[:window])
    past_window = len(body) > window
    if len(masked) <= MAX_TEXT_CHARS and not past_window:
        return masked + (TRUNCATED_MARKER if marked else "")
    limit = MAX_TEXT_CHARS - _CUT_HEADROOM
    if past_window:  # the window end can hold a partial secret, and masking may have moved it far back
        limit = max(0, min(limit, len(masked) - _CUT_PARTIAL))
    cut = masked[:limit]
    return cut[:-_CUT_TAIL] + _mask(cut[-_CUT_TAIL:]) + TRUNCATED_MARKER  # the tail may be a partial token


def mask_decoded(text: str) -> str:
    """mask_text for a string that may be percent-encoded: if the decoded form holds a secret the
    whole string is replaced, since the encoded form cannot be masked piecewise."""
    decoded = unquote(text)
    if decoded != text and mask_text(decoded) != decoded:
        return "[masked:secret]"
    return mask_text(text)


_PLAIN = (int, float, bool, type(None))


def mask_data(value: Any) -> Any:
    """Copy of `value` with every string and string dict key masked; dict, list and tuple are
    walked, other scalars kept. Iterative, so depth is unbounded; a shared container (or a
    cycle) is copied once and stays shared."""
    out: list[Any] = [None]
    seen: dict[int, Any] = {}  # id(source) -> its copy (for a tuple, a list standing in until it is built)
    refs: list[tuple[Any, Any, int]] = []  # (parent, slot, id(source tuple)): slots to point at the built tuple
    tuples: dict[int, list[Any]] = {}
    stack: list[tuple[Any, Any, Any]] = [(value, out, 0)]
    while stack:
        src, dst, slot = stack.pop()
        if isinstance(src, str):
            dst[slot] = mask_text(src)
        elif not isinstance(src, dict | list | tuple):
            dst[slot] = src
        elif id(src) in seen:
            dst[slot] = seen[id(src)]
            if isinstance(src, tuple):
                refs.append((dst, slot, id(src)))
        elif isinstance(src, dict):
            copy: Any = {}
            seen[id(src)] = dst[slot] = copy
            counts: dict[Any, int] = {}  # per masked key: the last `#n` suffix handed out, so collisions stay linear
            for k, v in src.items():
                key = mask_text(k) if isinstance(k, str) else k
                if key in copy:  # two keys that mask alike must both survive
                    n = counts.get(key, 1) + 1
                    base, key = key, f"{key}#{n}"
                    while key in copy:
                        n += 1
                        key = f"{base}#{n}"
                    counts[base] = n
                if type(v) is str:
                    copy[key] = mask_text(v)
                elif type(v) in _PLAIN:
                    copy[key] = v
                else:
                    copy[key] = None  # holds the slot (and the key) until the child is copied
                    stack.append((v, copy, key))
        else:
            copy = seen[id(src)] = dst[slot] = [None] * len(src)
            if isinstance(src, tuple):
                tuples[id(src)] = copy
                refs.append((dst, slot, id(src)))
            stack.extend((v, copy, i) for i, v in enumerate(src))
    built: dict[int, tuple[Any, ...]] = {}
    standing = {id(items): sid for sid, items in tuples.items()}  # stand-in list -> source tuple id
    for root in tuples:  # post-order, so a tuple is built after the tuples it holds
        todo = [root]
        while todo:
            sid = todo[-1]
            if sid in built:
                todo.pop()
                continue
            wait = [standing[id(x)] for x in tuples[sid] if id(x) in standing and standing[id(x)] not in built]
            if wait:
                todo.extend(wait)
                continue
            built[sid] = tuple(built[standing[id(x)]] if id(x) in standing else x for x in tuples[sid])
            todo.pop()
    for parent, slot, sid in refs:
        parent[slot] = built[sid]
    return out[0]
