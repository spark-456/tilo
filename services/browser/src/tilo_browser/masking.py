"""One masker for everything that leaves a browser worker (PRD 12.3, 16.1 rule 4, SEC-14).

Placeholders are `[masked:<kind>]`. Pure, idempotent, never raises on any str. Page content is
untrusted, so every pattern is linear: no unbounded prefix before a keyword, bounded repeats,
and a card window never grows past 19 digits.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

_FREE_SECRETS = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\bsk-[A-Za-z0-9_-]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|\bya29\.[A-Za-z0-9_-]{20,}"
)
# The keyword is matched directly (no prefix scan), so a long word cannot make this quadratic.
_KEY_VALUE = re.compile(
    r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|otp)[\"']?\s{0,8}[=:]\s{0,8}[\"']?)[^\s&\"']+"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,8}")
_PHONE = re.compile(r"(?<![\w+])\+\d[\d ()-]{6,24}\d")
# Digit groups of 2+ digits joined by one space or dash; a lone digit is never part of a card layout.
_DIGIT_RUN = re.compile(r"(?<!\w)\d{2,}(?:[ -]\d{2,})*")
_GROUP = re.compile(r"\d+")


def _luhn_prefixes(digits: str) -> tuple[list[int], list[int]]:
    """Prefix sums of Luhn terms, doubling even (a) or odd (b) indexes, so a window checks in O(1)."""
    a, b = [0], [0]
    for k, ch in enumerate(digits):
        d = int(ch)
        dd = d * 2 - 9 if d > 4 else d * 2
        a.append(a[-1] + (dd if k % 2 == 0 else d))
        b.append(b[-1] + (dd if k % 2 == 1 else d))
    return a, b


def _mask_cards(text: str) -> str:
    """Mask the longest Luhn-valid 13 to 19 digit window made of whole digit groups."""
    out: list[str] = []
    last = 0
    for run in _DIGIT_RUN.finditer(text):
        spans = [(g.start(), g.end()) for g in _GROUP.finditer(run.group())]
        if sum(e - s for s, e in spans) < 13:
            continue
        digits = "".join(run.group()[s:e] for s, e in spans)
        pa, pb = _luhn_prefixes(digits)
        starts = [0]
        for s, e in spans:
            starts.append(starts[-1] + e - s)
        i = 0
        while i < len(spans):
            hit = None
            for j in range(i, len(spans)):
                lo, hi = starts[i], starts[j + 1]
                if hi - lo > 19:
                    break
                if hi - lo >= 13:
                    p = pb if (hi - 1) % 2 == 0 else pa  # double the digits an even distance from the end
                    if (p[hi] - p[lo]) % 10 == 0:
                        hit = j
            if hit is None:
                i += 1
                continue
            out.append(text[last : run.start() + spans[i][0]])
            out.append("[masked:card]")
            last = run.start() + spans[hit][1]
            i = hit + 1
    out.append(text[last:])
    return "".join(out)


def mask_text(text: str) -> str:
    text = _FREE_SECRETS.sub("[masked:secret]", text)
    text = _KEY_VALUE.sub(r"\1[masked:secret]", text)
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
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {k: mask_data(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_data(v) for v in value]
    return value
