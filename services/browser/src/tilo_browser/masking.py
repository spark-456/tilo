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

# Text is cut to this many characters before masking, so the cost per call is bounded (256 KiB, about 0.5 s worst case).
MAX_TEXT_CHARS = 1 << 18
TRUNCATED_MARKER = " [truncated]"

_FREE_SECRETS = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\bsk-[A-Za-z0-9_-]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|\bya29\.[A-Za-z0-9_-]{20,}"
)
# The keyword is matched directly (no prefix scan), so a long word cannot make this quadratic.
# A quoted value is taken whole (bounded), so `"password": "a b c"` leaves no tail.
_KEY_VALUE = re.compile(
    r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|otp)[\"']?\s{0,8}[=:]\s{0,8})"
    r"(\"[^\"\n]{1,512}\"|'[^'\n]{1,512}'|[\"']?[^\s&\"']+)"
)
# `Authorization: <scheme> <credentials>`; the scheme is possessive so a masked value is left alone.
_AUTH_HEADER = re.compile(
    r"(?i)(\bauthorization[\"']?\s{0,8}[=:]\s{0,8}[\"']?(?:(?:basic|bearer|digest|token)\s{1,8})?+)"
    r"(?!\[masked:)[A-Za-z0-9._~+/=-]{4,}"
)
# `scheme://userinfo@` anywhere in text (a path, a query, page copy): the userinfo is dropped.
_URL_USERINFO = re.compile(r"(?<![A-Za-z0-9+.-])([A-Za-z][A-Za-z0-9+.-]{0,15}://)[^\s/?#]{1,4096}@")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,8}")
_PHONE = re.compile(r"(?<![\w+])\+\d[\d ()-]{6,24}\d")
# Digit groups of 2+ digits joined by one space or dash; a lone digit is never part of a card layout.
_DIGIT_RUN = re.compile(r"(?<!\w)\d{2,}(?:[ -]\d{2,})*")
_GROUP = re.compile(r"\d+")
_NON_DIGIT = re.compile(r"\D+")


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
        digits = _NON_DIGIT.sub("", body)
        if len(digits) < 13:
            continue
        spans = [(g.start(), g.end()) for g in _GROUP.finditer(body)]
        pa, pb = _luhn_prefixes(digits)
        ends = [0, *accumulate(e - s for s, e in spans)]  # ends[k]: digits before group k
        i = 0
        while i < len(spans):
            lo = ends[i]
            hit = None
            for k in range(bisect_right(ends, lo + 19) - 1, bisect_left(ends, lo + 13) - 1, -1):
                p = pb if (ends[k] - 1) % 2 == 0 else pa  # double the digits an odd distance from the end
                if (p[ends[k]] - p[lo]) % 10 == 0:
                    hit = k - 1
                    break
            if hit is None:
                i += 1
                continue
            out.append(text[last : run.start() + spans[i][0]])
            out.append("[masked:card]")
            last = run.start() + spans[hit][1]
            i = hit + 1
    out.append(text[last:])
    return "".join(out)


def _mask_value(m: re.Match[str]) -> str:
    value = m.group(2)
    quote = value[0] if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0] else ""
    return f"{m.group(1)}{quote}[masked:secret]{quote}"


def _cap(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS or (
        len(text) <= MAX_TEXT_CHARS + len(TRUNCATED_MARKER) and text.endswith(TRUNCATED_MARKER)
    ):
        return text
    return text[:MAX_TEXT_CHARS] + TRUNCATED_MARKER


def mask_text(text: str) -> str:
    text = _URL_USERINFO.sub(r"\1[masked:secret]@", _cap(text))
    text = _FREE_SECRETS.sub("[masked:secret]", text)
    text = _AUTH_HEADER.sub(r"\1[masked:secret]", text)
    text = _KEY_VALUE.sub(_mask_value, text)
    text = _mask_cards(text)
    text = _EMAIL.sub("[masked:email]", text)
    return _PHONE.sub("[masked:phone]", text)


def mask_decoded(text: str) -> str:
    """mask_text for a string that may be percent-encoded: if the decoded form holds a secret the
    whole string is replaced, since the encoded form cannot be masked piecewise."""
    decoded = unquote(text)
    if decoded != text and mask_text(decoded) != decoded:
        return "[masked:secret]"
    return mask_text(text)


def mask_data(value: Any) -> Any:
    """Copy of `value` with every string and string dict key masked; dict, list and tuple are
    walked, other scalars kept. Iterative, so depth is unbounded; a shared list or dict (or a
    cycle) is copied once."""
    out: list[Any] = [None]
    seen: dict[int, Any] = {}
    tuples: list[tuple[list[Any], Any, Any]] = []  # (items, parent, slot), parents before children
    stack: list[tuple[Any, Any, Any]] = [(value, out, 0)]
    while stack:
        src, dst, slot = stack.pop()
        if isinstance(src, str):
            dst[slot] = mask_text(src)
        elif not isinstance(src, dict | list | tuple):
            dst[slot] = src
        elif id(src) in seen:
            dst[slot] = seen[id(src)]
        elif isinstance(src, dict):
            copy: Any = {}
            seen[id(src)] = dst[slot] = copy
            used: set[Any] = set()
            for k, v in src.items():
                key = mask_text(k) if isinstance(k, str) else k
                while key in used:  # two secret keys must not collapse into one entry
                    key = f"{key}#"
                used.add(key)
                stack.append((v, copy, key))
        else:
            copy = dst[slot] = [None] * len(src)
            if isinstance(src, list):
                seen[id(src)] = copy
            else:
                tuples.append((copy, dst, slot))
            stack.extend((v, copy, i) for i, v in enumerate(src))
    for items, parent, slot in reversed(tuples):  # a child tuple is rebuilt before its parent
        parent[slot] = tuple(items)
    return out[0]
